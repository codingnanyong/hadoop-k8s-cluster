"""IPI Temperature Matching - PySpark 구현

기존 pandas 로우-by-로우 매칭을 Spark DataFrame 범위 조인으로 대체.
결과는 _spark suffix 테이블에 적재하여 pandas 결과와 병렬 검증.

사용법:
    spark-submit ipi_temperature_matching_spark.py \
        <target_date> <suffix> <jdbc_url> <pg_user> <pg_password>

예시 (자격 증명은 인자로만 전달 — 저장소에 커밋하지 마세요):
    spark-submit ... script.py 2025-01-15 _spark \
        jdbc:postgresql://YOUR_PG_HOST:5432/quality_dw YOUR_USER YOUR_PASSWORD
"""
import sys
from datetime import datetime

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window


# ════════════════════════════════════════════════════════════════
# Configuration (pandas 구현과 동일한 값)
# ════════════════════════════════════════════════════════════════

MACHINE_NO_LIST       = ["MCA34"]
LOOKBACK_MINUTES      = 7
ALLOWED_REASON_CDS    = ["good", "Burning", "Sink mark"]

GOOD_PRODUCT_TABLE    = "silver.ipi_good_product"
OSND_TABLE            = "silver.ipi_defective_cross_validated"
TEMPERATURE_TABLE     = "silver.ipi_anomaly_transformer_result"
DEFECT_CODE_TABLE     = "silver.ip_defect_code"


# ════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 6:
        print("Usage: script.py <target_date> <suffix> <jdbc_url> <pg_user> <pg_password>")
        sys.exit(1)

    target_date  = sys.argv[1]          # e.g. 2025-01-15
    suffix       = sys.argv[2]          # e.g. _spark
    jdbc_url     = sys.argv[3]
    pg_user      = sys.argv[4]
    pg_password  = sys.argv[5]

    TARGET_MAIN   = f"gold.ipi_temperature_matching{suffix}"
    TARGET_DETAIL = f"gold.ipi_temperature_matching_detail{suffix}"

    pg_props = {
        "user":     pg_user,
        "password": pg_password,
        "driver":   "org.postgresql.Driver",
        "batchsize": "1000",
    }

    spark = SparkSession.builder \
        .appName(f"ipi_temperature_matching_{target_date}{suffix}") \
        .getOrCreate()
    spark.sparkContext.setLogLevel("WARN")

    extract_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== IPI Temperature Matching Spark ===")
    print(f"  날짜: {target_date} | suffix: {suffix}")
    print(f"  출력: {TARGET_MAIN}, {TARGET_DETAIL}")

    # ── 1. 데이터 추출 ───────────────────────────────────────────

    df_good = spark.read.jdbc(jdbc_url, GOOD_PRODUCT_TABLE, properties=pg_props) \
        .filter(F.to_date("rst_ymd") == target_date) \
        .filter(F.col("mc_cd").isin(MACHINE_NO_LIST)) \
        .select("so_id", "rst_ymd", "mc_cd", "st_num", "st_side", "mold_id")

    df_osnd_raw = spark.read.jdbc(jdbc_url, OSND_TABLE, properties=pg_props) \
        .filter(F.to_date("osnd_dt") == target_date) \
        .filter(F.col("machine_cd").isin(MACHINE_NO_LIST)) \
        .select("osnd_id", "osnd_dt", "machine_cd", "station", "station_rl",
                "mold_id", "reason_cd", "size_cd", "lr_cd", "osnd_bt_qty")

    # 온도 데이터: 당일 + lookback 시간 포함
    df_temp = spark.read.jdbc(jdbc_url, TEMPERATURE_TABLE, properties=pg_props) \
        .filter(
            (F.col("measurement_time") >= F.expr(
                f"TIMESTAMP '{target_date} 00:00:00' - INTERVAL {LOOKBACK_MINUTES} MINUTES"
            )) &
            (F.col("measurement_time") <= F.expr(f"TIMESTAMP '{target_date} 23:59:59'"))
        ) \
        .filter(F.col("machine_code").isin(MACHINE_NO_LIST)) \
        .select("machine_code", "mc", "prop", "measurement_time", "temperature") \
        .withColumn("mc_prop", F.concat(F.col("mc"), F.lit("_"), F.col("prop"))) \
        .cache()

    df_defect = spark.read.jdbc(jdbc_url, DEFECT_CODE_TABLE, properties=pg_props) \
        .select("defect_cd", "defect_name")

    good_cnt = df_good.count()
    osnd_cnt = df_osnd_raw.count()
    temp_cnt = df_temp.count()
    print(f"  추출: 양품={good_cnt:,} | OSND={osnd_cnt:,} | 온도={temp_cnt:,}")

    # ── 2. 양품 → OSND 형식 변환 후 통합 ────────────────────────

    df_good_as_osnd = df_good \
        .withColumnRenamed("so_id",    "osnd_id") \
        .withColumnRenamed("rst_ymd",  "osnd_dt") \
        .withColumnRenamed("mc_cd",    "machine_cd") \
        .withColumnRenamed("st_num",   "station") \
        .withColumnRenamed("st_side",  "station_rl") \
        .withColumn("reason_cd",    F.lit("good")) \
        .withColumn("size_cd",      F.lit(None).cast("string")) \
        .withColumn("lr_cd",        F.lit(None).cast("string")) \
        .withColumn("osnd_bt_qty",  F.lit(None).cast("integer")) \
        .select("osnd_id", "osnd_dt", "machine_cd", "station", "station_rl",
                "mold_id", "reason_cd", "size_cd", "lr_cd", "osnd_bt_qty")

    df_merged = df_osnd_raw.union(df_good_as_osnd) \
        .withColumn("osnd_dt",  F.to_timestamp("osnd_dt")) \
        .withColumn("station",  F.col("station").cast("integer"))

    # ── 3. 불량 코드 매핑 + 필터 ────────────────────────────────

    df_defect_b = df_defect \
        .withColumnRenamed("defect_cd",   "d_cd") \
        .withColumnRenamed("defect_name", "d_name")

    df_merged = df_merged \
        .join(F.broadcast(df_defect_b), df_merged["reason_cd"] == df_defect_b["d_cd"], "left") \
        .withColumn("reason_cd", F.coalesce(F.col("d_name"), F.col("reason_cd"))) \
        .drop("d_cd", "d_name") \
        .filter(F.col("reason_cd").isin(ALLOWED_REASON_CDS))

    merged_cnt = df_merged.count()
    print(f"  통합 후 (필터): {merged_cnt:,} rows")

    if merged_cnt == 0:
        print("  처리할 데이터가 없습니다. 종료.")
        spark.stop()
        return

    # ── 4. mc_prop 패턴 & 시간 범위 컬럼 생성 ───────────────────

    df_osnd_prepped = df_merged \
        .withColumn("station_rl_upper", F.upper(F.col("station_rl"))) \
        .withColumn("time_start",
                    F.col("osnd_dt") - F.expr(f"INTERVAL {LOOKBACK_MINUTES} MINUTES")) \
        .withColumn("mc_prop_L",
                    F.concat(F.lit("st_"), F.col("station").cast("string"),
                             F.lit("_Plate Temperature L"), F.col("station_rl_upper"))) \
        .withColumn("mc_prop_U",
                    F.concat(F.lit("st_"), F.col("station").cast("string"),
                             F.lit("_Plate Temperature U"), F.col("station_rl_upper"))) \
        .cache()

    df_temp_join = df_temp.select("machine_code", "mc_prop", "measurement_time", "temperature")

    # ── 5. 범위 조인 (L / U) ────────────────────────────────────

    def range_join(df_osnd, mc_prop_col, temp_type_label):
        """OSND × 온도 범위 조인 → 상세 레코드"""
        return df_osnd.join(
            df_temp_join,
            (df_temp_join["machine_code"] == df_osnd["machine_cd"]) &
            (df_temp_join["mc_prop"]      == df_osnd[mc_prop_col]) &
            (df_temp_join["measurement_time"] >= df_osnd["time_start"]) &
            (df_temp_join["measurement_time"] <= df_osnd["osnd_dt"]),
            "left"
        ).select(
            df_osnd["osnd_id"],
            df_osnd["osnd_dt"],
            F.lit(temp_type_label).alias("temp_type"),
            df_temp_join["measurement_time"],
            df_temp_join["temperature"],
        )

    df_joined_L = range_join(df_osnd_prepped, "mc_prop_L", "L")
    df_joined_U = range_join(df_osnd_prepped, "mc_prop_U", "U")

    # ── 6. 통계 집계 (count / avg / min / max) ──────────────────

    def agg_stats(df_joined, prefix):
        not_null = F.when(F.col("temperature").isNotNull(), F.col("temperature"))
        return df_joined.groupBy("osnd_id", "osnd_dt").agg(
            F.count(F.when(F.col("temperature").isNotNull(), 1)).alias(f"temp_{prefix}_count"),
            F.avg(not_null).alias(f"temp_{prefix}_avg"),
            F.min(not_null).alias(f"temp_{prefix}_min"),
            F.max(not_null).alias(f"temp_{prefix}_max"),
        )

    df_stats_L = agg_stats(df_joined_L, "L")
    df_stats_U = agg_stats(df_joined_U, "U")

    # ── 7. Main 테이블 ───────────────────────────────────────────

    df_main = df_osnd_prepped \
        .drop("station_rl_upper", "time_start", "mc_prop_L", "mc_prop_U") \
        .join(df_stats_L, ["osnd_id", "osnd_dt"], "left") \
        .join(df_stats_U, ["osnd_id", "osnd_dt"], "left") \
        .withColumn("etl_extract_time", F.lit(extract_time).cast("timestamp"))

    main_cnt = df_main.count()
    print(f"  Main 저장: {main_cnt:,} rows → {TARGET_MAIN}")

    df_main.write.jdbc(jdbc_url, TARGET_MAIN, mode="append", properties=pg_props)

    # ── 8. Detail 테이블 ─────────────────────────────────────────

    w_seq = Window.partitionBy("osnd_id", "osnd_dt", "temp_type").orderBy("measurement_time")

    df_detail = df_joined_L.union(df_joined_U) \
        .filter(F.col("temperature").isNotNull()) \
        .withColumn("seq_no", F.row_number().over(w_seq)) \
        .withColumn("etl_extract_time", F.lit(extract_time).cast("timestamp"))

    detail_cnt = df_detail.count()
    print(f"  Detail 저장: {detail_cnt:,} rows → {TARGET_DETAIL}")

    df_detail.write.jdbc(jdbc_url, TARGET_DETAIL, mode="append", properties=pg_props)

    # ── 9. Hive Metastore 등록 (JDBC 페더레이션 테이블) ──────────
    # DBeaver / Spark Thrift Server에서 직접 SELECT 가능하도록 등록
    # 이미 등록된 경우 스킵 (IF NOT EXISTS)

    def register_metastore_jdbc_table(hive_db: str, hive_table: str, pg_schema_table: str):
        """PostgreSQL 테이블을 Hive Metastore에 JDBC 페더레이션 테이블로 등록"""
        spark.sql(f"CREATE DATABASE IF NOT EXISTS {hive_db}")
        spark.sql(f"""
            CREATE TABLE IF NOT EXISTS {hive_db}.{hive_table}
            USING JDBC
            OPTIONS (
                url         '{jdbc_url}',
                dbtable     '{pg_schema_table}',
                user        '{pg_user}',
                password    '{pg_password}',
                driver      'org.postgresql.Driver'
            )
        """)
        print(f"  Metastore 등록: {hive_db}.{hive_table} → {pg_schema_table}")

    hive_db = "quality_gold"
    # TARGET_MAIN   = "gold.ipi_temperature_matching_spark"
    main_hive_table   = TARGET_MAIN.replace("gold.", "").replace(".", "_")    # ipi_temperature_matching_spark
    detail_hive_table = TARGET_DETAIL.replace("gold.", "").replace(".", "_")  # ipi_temperature_matching_detail_spark

    register_metastore_jdbc_table(hive_db, main_hive_table,   TARGET_MAIN)
    register_metastore_jdbc_table(hive_db, detail_hive_table, TARGET_DETAIL)

    print(f"  DBeaver에서 조회: SELECT * FROM {hive_db}.{main_hive_table} LIMIT 100;")
    print(f"=== 완료: main={main_cnt:,} | detail={detail_cnt:,} ===")
    spark.stop()


if __name__ == "__main__":
    main()
