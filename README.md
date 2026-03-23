# 🐘 Hadoop on Kubernetes

**3노드(워커 `worker-01` ~ `worker-03`) kubeadm 클러스터**를 가정하고, HDFS **DataNode 3대** + YARN NodeManager 3대 + HBase RegionServer 3대와 Spark / Hive / Livy를 컨테이너로 운영하는 실습용 구성입니다.

> 🔒 **보안**: 이 저장소의 매니페스트와 문서는 **실제 IP, 호스트명, 디스크 경로, DB 비밀번호를 담지 않도록** 되어 있습니다. 배포 전에 `nodeSelector`의 `kubernetes.io/hostname`, PV `local.path`, Hive Secret 등을 **본인 환경에 맞게** 바꾸세요. Hive DB 자격 증명은 `hive-metastore-db-secret`으로만 주입합니다(예시: `hive-metastore-db-secret.example.yaml`).

## 📋 목차

| 문서 | 내용 |
|------|------|
| [🏗️ 아키텍처](docs/01-architecture.md) | 클러스터 전체 구성, 컴포넌트 역할, 저장소 구조 |
| [⚙️ 초기 설정](docs/02-setup.md) | 선행 조건, 네임스페이스, 스토리지 PV/PVC 생성 |
| [📦 HDFS](docs/03-hdfs.md) | NameNode / DataNode 설정 및 운영 |
| [🔄 YARN](docs/04-yarn.md) | ResourceManager / NodeManager 설정 및 운영 |
| [🔥 Spark](docs/05-spark.md) | Spark on YARN, Thrift Server, History Server |
| [🐝 Hive Metastore](docs/06-hive.md) | Hive Metastore, 테이블 영속성, DBeaver 연동 |
| [🦁 ZooKeeper + HBase](docs/07-zookeeper-hbase.md) | ZooKeeper, HBase Master/RegionServer, Shell 사용법 |
| [🌉 Livy](docs/08-livy.md) | Livy REST API, Airflow 연동, 배치 잡 제출 |
| [🛠️ 운영 가이드](docs/09-operations.md) | 상태 확인, 잡 실행, 설정 변경 방법 |
| [🔍 트러블슈팅](docs/10-troubleshooting.md) | 주요 장애 사례 및 해결 방법 |


## 🚀 현재 상태

### Pod 현황

```bash
kubectl get pods -n hadoop
```

| Pod | 노드 | 상태 |
|-----|------|------|
| hdfs-namenode | worker-01 | ✅ Running |
| hdfs-datanode-worker-01 | worker-01 | ✅ Running |
| hdfs-datanode-worker-02 | worker-02 | ✅ Running |
| hdfs-datanode-worker-03 | worker-03 | ✅ Running |
| yarn-resourcemanager | worker-01 | ✅ Running |
| yarn-nodemanager-worker-01 | worker-01 | ✅ Running |
| yarn-nodemanager-worker-02 | worker-02 | ✅ Running |
| yarn-nodemanager-worker-03 | worker-03 | ✅ Running |
| spark-client | worker-01 | ✅ Running |
| spark-thriftserver | worker-01 | ✅ Running |
| spark-history-server | worker-01 | ✅ Running |
| hive-metastore | worker-01 | ✅ Running |
| zookeeper | worker-01 | ✅ Running |
| hbase-master | worker-01 | ✅ Running |
| hbase-regionserver-worker-01 | worker-01 | ✅ Running |
| hbase-regionserver-worker-02 | worker-02 | ✅ Running |
| hbase-regionserver-worker-03 | worker-03 | ✅ Running |
| livy-server | worker-01 | ✅ Running |

### 🌐 Web UI

| 서비스 | URL | 용도 |
|--------|-----|------|
| HDFS NameNode UI | http://YOUR_NODE_IP:30870 | HDFS 파일시스템 현황 |
| YARN ResourceManager UI | http://YOUR_NODE_IP:30890 | 잡 현황 및 실행 중 Spark UI |
| Spark History Server | http://YOUR_NODE_IP:30180 | 완료된 Spark 잡 이력 |
| HBase Master UI | http://YOUR_NODE_IP:30610 | HBase 클러스터 현황 |
| Livy REST API | http://YOUR_NODE_IP:30998 | 배치 잡 제출 및 세션 관리 |

### 🔌 외부 접속 (JDBC)

| 서비스 | 접속 정보 | 용도 |
|--------|-----------|------|
| Spark Thrift Server | `jdbc:hive2://YOUR_NODE_IP:30100/default` | DBeaver / SQL 클라이언트 |

## 📁 디렉터리 구조

```text
hadoop/
├── README.md
├── docs/
│   ├── 01-architecture.md
│   ├── 02-setup.md
│   ├── 03-hdfs.md
│   ├── 04-yarn.md
│   ├── 05-spark.md
│   ├── 06-hive.md
│   ├── 07-zookeeper-hbase.md
│   ├── 08-livy.md
│   ├── 09-operations.md
│   └── 10-troubleshooting.md
└── k8s/
    ├── config/
    │   └── hadoop-configmap.yaml
    ├── storage/
    │   ├── storageclass-local-hdfs.yaml
    │   ├── pv/
    │   └── pvc/
    ├── hdfs/
    ├── yarn/
    ├── spark/
    ├── hive/
    │   ├── hive-configmap.yaml
    │   ├── hive-metastore.yaml
    │   └── hive-metastore-db-secret.example.yaml   # copy → hive-metastore-db-secret.yaml (gitignored)
    ├── zookeeper/
    │   └── zookeeper.yaml
    ├── hbase/
    │   ├── hbase-configmap.yaml
    │   ├── hbase-master.yaml
    │   ├── hbase-regionserver-worker-01.yaml
    │   ├── hbase-regionserver-worker-02.yaml
    │   └── hbase-regionserver-worker-03.yaml
    └── livy/                  ← NEW
        ├── livy-configmap.yaml
        └── livy.yaml
```

## ⚡ 빠른 시작 (전체 배포)

```bash
# 1. 네임스페이스
kubectl create namespace hadoop

# 2. 스토리지
kubectl apply -f k8s/storage/storageclass-local-hdfs.yaml
kubectl apply -f k8s/storage/pv/
kubectl apply -n hadoop -f k8s/storage/pvc/

# 3. ConfigMap
kubectl apply -n hadoop -f k8s/config/hadoop-configmap.yaml

# 4. HDFS
kubectl apply -n hadoop -f k8s/hdfs/

# 5. YARN
kubectl apply -n hadoop -f k8s/yarn/

# 6. Spark (HDFS 디렉토리 생성 후 배포)
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $NN_POD -- hdfs dfs -mkdir -p /spark-staging /spark-logs /warehouse /hbase
kubectl exec -n hadoop $NN_POD -- hdfs dfs -chmod 777 /spark-staging /spark-logs /warehouse /hbase
kubectl apply -n hadoop -f k8s/spark/

# 7. Hive Metastore (DB + Secret — 실제 값은 로컬에서만 설정)
#    PostgreSQL에 metastore DB 생성 (관리자 계정/호스트는 환경에 맞게 변경)
#    psql "postgresql://USER:PASSWORD@YOUR_PG_HOST:5432/postgres" -c "CREATE DATABASE metastore OWNER hive_owner;"
cp k8s/hive/hive-metastore-db-secret.example.yaml k8s/hive/hive-metastore-db-secret.yaml
#    hive-metastore-db-secret.yaml 편집 후:
kubectl apply -f k8s/hive/hive-metastore-db-secret.yaml
kubectl apply -n hadoop -f k8s/hive/hive-configmap.yaml
kubectl apply -n hadoop -f k8s/hive/hive-metastore.yaml

# 8. ZooKeeper
kubectl apply -n hadoop -f k8s/zookeeper/

# 9. HBase
kubectl apply -n hadoop -f k8s/hbase/

# 10. Livy (Airflow 연동용 REST API 서버)
kubectl apply -n hadoop -f k8s/livy/
# 최초 기동 시 init container가 Livy 바이너리를 다운로드 (약 1~2분)
```
