# 🌉 Apache Livy

## 📐 개요

Apache Livy는 Spark 클러스터에 **REST API**로 잡을 제출하는 브릿지 서버입니다.  
Airflow 같은 외부 오케스트레이터가 Kubernetes 내부의 YARN에 직접 접근하지 않고도 Spark 잡을 실행할 수 있게 합니다.

```textx
Airflow (Docker)
    │
    │  HTTP POST /batches  (LivyOperator)
    ▼
Livy Server (K8s Pod, :30998)
    │
    │  spark-submit --master yarn
    ▼
YARN ResourceManager → NodeManager → Spark Executor
```

| 컴포넌트      | 역할                           |
| ------------- | ------------------------------ |
| Livy REST API | 배치 잡·인터랙티브 세션 관리   |
| `/batches`    | spark-submit 방식의 단발성 잡  |
| `/sessions`   | PySpark 인터랙티브 세션 (REPL) |

## 🏗️ 구성

| 항목               | 값                                                              |
| ------------------ | --------------------------------------------------------------- |
| 이미지             | `apache/spark:3.5.3` (Spark와 동일)                             |
| Livy 버전          | 0.7.0-incubating                                                |
| 노드               | worker-01                                                       |
| ClusterIP 포트     | 8998                                                            |
| NodePort           | **30998**                                                       |
| Livy 바이너리 경로 | `/var/lib/hadoop-k8s/livy-cache` (hostPath, 재시작 후에도 유지) |

## 🚀 배포

```bash
# ConfigMap + Deployment + Service 배포
kubectl apply -n hadoop -f k8s/livy/livy-configmap.yaml
kubectl apply -n hadoop -f k8s/livy/livy.yaml

# 최초 기동: init container가 Livy 바이너리를 다운로드 (약 1~2분)
kubectl get pods -n hadoop -l app=livy-server -w
```

### 동작 확인

```bash
# REST API 응답 확인
curl http://YOUR_NODE_IP:30998/sessions   # {"from":0,"total":0,"sessions":[]}
curl http://YOUR_NODE_IP:30998/batches    # {"from":0,"total":0,"sessions":[]}
```

## 📡 REST API 사용법

### 배치 잡 제출

```bash
curl -X POST http://YOUR_NODE_IP:30998/batches \
  -H "Content-Type: application/json" \
  -d '{
    "file": "hdfs:///jars/spark-examples_2.12-3.5.3.jar",
    "className": "org.apache.spark.examples.SparkPi",
    "args": ["10"],
    "name": "my-spark-job",
    "conf": {
      "spark.executor.memory": "1g",
      "spark.driver.memory": "512m"
    }
  }'
```

> **주의**: `file` 경로는 반드시 `hdfs:///` 경로를 사용할 것.  
> 로컬 경로(`/opt/spark/...`)는 HDFS 경로로 해석되어 오류 발생.

### 잡 상태 조회

```bash
# 특정 배치 상태
curl http://YOUR_NODE_IP:30998/batches/{id}

# 로그 조회
curl "http://YOUR_NODE_IP:30998/batches/{id}/log?from=0&size=100"
```

### 상태 값

| 상태       | 의미                 |
| ---------- | -------------------- |
| `starting` | spark-submit 실행 중 |
| `running`  | YARN에서 실행 중     |
| `success`  | 완료                 |
| `dead`     | 실패                 |

## 🔌 Airflow 연동

### 1. Airflow Connection 등록

Airflow UI → **Admin → Connections → +**

| 항목            | 값             |
| --------------- | -------------- |
| Connection Id   | `livy_default` |
| Connection Type | `HTTP`         |
| Host            | `YOUR_NODE_IP` |
| Port            | `30998`        |

### 2. LivyOperator 사용 예시

```python
from airflow.providers.apache.livy.operators.livy import LivyOperator

spark_job = LivyOperator(
    task_id="run_spark_job",
    livy_conn_id="livy_default",
    file="hdfs:///jobs/my_spark_job.py",
    args=["{{ ds }}", "_spark"],
    conf={
        "spark.master": "yarn",
        "spark.submit.deployMode": "cluster",
        "spark.executor.memory": "2g",
        "spark.executor.cores": "2",
    },
    dag=dag,
)
```

### 3. HDFS에 PySpark 스크립트 업로드

```bash
# spark-client Pod에서
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')

# 1) 로컬 → NameNode Pod
kubectl cp /path/to/my_job.py hadoop/$NN_POD:/tmp/my_job.py

# 2) NameNode Pod → HDFS
kubectl exec -n hadoop $NN_POD -- hdfs dfs -mkdir -p /jobs
kubectl exec -n hadoop $NN_POD -- hdfs dfs -put -f /tmp/my_job.py /jobs/
```

## ⚠️ 주요 주의사항

### Livy 버전 호환성

Livy 0.7.0은 Hadoop 2.7.3 JAR을 내부적으로 포함합니다.  
Spark 3.5.x 배치 잡 제출은 정상 동작하나, 다음 경고는 무시 가능합니다:

```bash
WARNING: An illegal reflective access by hadoop-auth-2.7.3.jar
```

### Airflow Provider 버전

```bash
# Airflow 2.10.3에는 반드시 constraints 적용하여 설치
pip install apache-airflow-providers-apache-livy \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.3/constraints-3.12.txt"
# → apache-airflow-providers-apache-livy==3.9.2 설치됨
```

버전 미지정 시 pip가 Livy 4.x를 선택하여 **Airflow 2.x를 3.x로 업그레이드**하는 사고 발생.

## 🔍 트러블슈팅

| 증상                                         | 원인                                             | 해결                                         |
| -------------------------------------------- | ------------------------------------------------ | -------------------------------------------- |
| `mkdir: Permission denied` (CrashLoop)       | 컨테이너 실행 유저(UID 185)가 hostPath 쓰기 불가 | `securityContext: runAsUser: 0` 추가         |
| `File does not exist: hdfs:///opt/spark/...` | 로컬 경로를 HDFS 경로로 해석                     | `file` 항목에 `hdfs:///` 경로 사용           |
| `exitCode: 13` (YARN AM)                     | `local:///` 경로 문제                            | HDFS에 jar 업로드 후 `hdfs:///jars/...` 사용 |
| Livy Provider import 실패                    | pip가 Livy 4.x 설치 → Airflow 3.x 업그레이드     | constraints 파일로 재설치                    |
