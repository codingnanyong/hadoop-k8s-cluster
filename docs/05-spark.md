# 🔥 Spark

[← README로 돌아가기](../README.md)

## 📐 개요

**Spark**는 인메모리 분산 처리 엔진으로, Hadoop의 MapReduce보다 빠른 배치·SQL 처리를 제공합니다.
이 환경에서는 YARN 위에서 실행되며, Spark Thrift Server를 통해 DBeaver 같은 SQL 클라이언트로 접속할 수 있습니다.

| 컴포넌트                 | 역할                                                  |
| ------------------------ | ----------------------------------------------------- |
| **spark-client**         | `spark-submit` 명령어 실행용 Pod                      |
| **Spark Thrift Server**  | JDBC 서버 (DBeaver / SQL 클라이언트 연결, 포트 10000) |
| **Spark History Server** | 완료된 잡 Web UI (포트 18080 → NodePort 30180)        |

> **01-architecture.md** 와의 차이: architecture.md는 Spark이 YARN·HDFS·Hive Metastore와 어떻게 연결되는지를 보여줍니다. 이 문서는 Spark 컴포넌트별 배포 설정과 DBeaver 연결 방법을 다룹니다.

```text
spark-client Pod
    │  spark-submit --master yarn
    ▼
ResourceManager (잡 접수 + 스케줄링)
    │  Spark jars → hdfs:///spark-staging 업로드
    ▼
NodeManager: ApplicationMaster (Spark Driver) 실행
    │  HDFS에서 jars 다운로드
    ▼
NodeManager × 2: Spark Executor 컨테이너 실행
```

> YARN 컨테이너(= JVM 프로세스) 안에서 Spark가 동작한다.
> 새로운 Kubernetes Pod가 생성되는 것이 **아니다**.

## 📁 파일 구성

```text
k8s/spark/
├── spark-configmap.yaml          # spark-defaults.conf 설정
├── spark-client.yaml             # spark-submit 전용 Pod
├── spark-thriftserver.yaml       # JDBC 서버 (DBeaver 연결용)
├── spark-thriftserver-service.yaml  # NodePort 30100
└── spark-history-server.yaml     # 완료 잡 이력 Web UI (NodePort 30180)
```

## ⚙️ spark-defaults.conf 주요 설정

```properties
spark.master                  yarn
spark.submit.deployMode       cluster
spark.hadoop.fs.defaultFS     hdfs://hdfs-namenode:8020
spark.yarn.stagingDir         hdfs:///spark-staging
spark.eventLog.enabled        true
spark.eventLog.dir            hdfs:///spark-logs
```

## 🚀 배포

### 사전 조건 — HDFS 디렉토리 생성

```bash
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $NN_POD -- hdfs dfs -mkdir -p /spark-staging /spark-logs
kubectl exec -n hadoop $NN_POD -- hdfs dfs -chmod 777 /spark-staging /spark-logs
```

### 배포 명령

```bash
kubectl apply -n hadoop -f k8s/spark/
```

## 🏃 spark-submit 잡 실행

### Pod 접속

```bash
SP_POD=$(kubectl get pod -n hadoop -l app=spark-client -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it -n hadoop $SP_POD -- bash
```

### SparkPi 테스트

```bash
# cluster 모드 (권장)
/opt/spark/bin/spark-submit \
  --master yarn \
  --deploy-mode cluster \
  --class org.apache.spark.examples.SparkPi \
  /opt/spark/examples/jars/spark-examples_2.12-3.5.3.jar 10
```

> ⚠️ **`--deploy-mode client` 는 이 환경에서 동작하지 않는다.**
> 이유: client 모드에서는 Executor가 Driver(spark-client Pod)의 hostname으로
> 접속을 시도하는데, Pod hostname이 NodeManager에서 DNS 조회되지 않아 연결 실패한다.
> cluster 모드를 사용하면 Driver도 NodeManager 안에서 실행되어 정상 동작한다.

### kubectl 외부에서 실행 (로컬 PC)

```bash
kubectl exec -n hadoop \
  $(kubectl get pod -n hadoop -l app=spark-client -o jsonpath='{.items[0].metadata.name}') \
  -- bash -c '/opt/spark/bin/spark-submit \
    --master yarn --deploy-mode cluster \
    --class org.apache.spark.examples.SparkPi \
    /opt/spark/examples/jars/spark-examples_2.12-3.5.3.jar 10'
```

## 🔌 Spark Thrift Server (DBeaver 연결)

JDBC/ODBC 인터페이스를 제공하는 HiveServer2 호환 서버.
DBeaver 등 SQL 클라이언트에서 Spark SQL을 직접 실행할 수 있다.

### 접속 정보

| 항목     | 값                                        |
| -------- | ----------------------------------------- |
| JDBC URL | `jdbc:hive2://YOUR_NODE_IP:30100/default` |
| Host     | `YOUR_NODE_IP`                            |
| Port     | `30100`                                   |
| Database | `default`                                 |
| Username | `spark`                                   |
| Password | (없음)                                    |

### DBeaver 연결 방법

1. `Database` → `New Database Connection`
2. **Apache Spark** 또는 **Apache Hive** 선택
3. 위 접속 정보 입력
4. 드라이버 자동 다운로드 → **Download** 클릭
5. `Test Connection` 확인

### Spark SQL 예시

```sql
-- 데이터베이스 목록
SHOW DATABASES;

-- HDFS 파일 직접 쿼리 (파일이 있어야 함)
SELECT * FROM parquet.`hdfs:///warehouse/mytable`;
SELECT * FROM csv.`hdfs:///data/sample.csv`;
SELECT * FROM json.`hdfs:///data/logs.json`;

-- 영구 테이블 생성
CREATE TABLE IF NOT EXISTS orders (
  order_id BIGINT,
  customer STRING,
  amount   DOUBLE,
  dt       DATE
) USING parquet
LOCATION 'hdfs:///warehouse/orders';

INSERT INTO orders VALUES (1, '홍길동', 15000, '2026-01-01');
SELECT * FROM orders;
```

> ⚠️ `SELECT * FROM json.hdfs:///data/logs.json` 실행 전 해당 파일이
> HDFS에 실제로 존재하는지 확인해야 한다.

### 상태 확인

```bash
kubectl logs -n hadoop -l app=spark-thriftserver --tail=20
```

정상 기동 시 마지막 줄:

```bash
HiveThriftServer2 started
ThriftBinaryCLIService on port 10000 with 5...500 worker threads
```

## 📊 Spark History Server

완료된 Spark 잡의 실행 이력, 스테이지별 통계, DAG 시각화를 웹 UI로 제공한다.

### 접속

```bash
http://YOUR_NODE_IP:30180
```

> YARN Web UI(`http://YOUR_NODE_IP:30890/cluster/apps`)에서도 완료된 잡을 클릭하면
> History Server로 연결된다.

### 실행 중인 잡 UI 접근

실행 중인 Spark 잡의 UI는 YARN 프록시를 통해 접근한다:

```bash
http://YOUR_NODE_IP:30890/cluster/apps
→ 애플리케이션 클릭 → Spark UI 접근
```

> ⚠️ Thrift Server의 NodePort(30404)로 직접 접근 시 YARN 내부 주소
> (`yarn-resourcemanager:8090`)로 리다이렉트되어 외부에서 접근 불가.
> 반드시 YARN Web UI를 통해 접근한다.

## ✅ 검증 명령어

```bash
# 1. Spark 잡 실행 확인
SP_POD=$(kubectl get pod -n hadoop -l app=spark-client -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $SP_POD -- bash -c \
  '/opt/spark/bin/spark-submit --master yarn --deploy-mode cluster \
   --class org.apache.spark.examples.SparkPi \
   /opt/spark/examples/jars/spark-examples_2.12-3.5.3.jar 10 2>&1 | grep "final status"'

# 기대 출력: final status: SUCCEEDED

# 2. Thrift Server 동작 확인
kubectl logs -n hadoop -l app=spark-thriftserver --tail=5

# 3. History Server 동작 확인
kubectl logs -n hadoop -l app=spark-history-server --tail=5
```
