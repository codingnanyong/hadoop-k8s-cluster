# 🔍 트러블슈팅

[← README로 돌아가기](../README.md)

## 🗂️ HDFS 관련

### ❌ DataNode가 NameNode에 등록되지 않음

**증상**: `hdfs dfsadmin -report`에서 `Live datanodes (0)`

#### 원인 A: clusterID 불일치

**확인 방법:**

```bash
# DataNode 로그에서 확인
kubectl logs -n hadoop <datanode-pod> | grep -iE "incompatible|clusterID|mismatch"
```

로그 예시:

```bash
Incompatible clusterIDs in /data/hdfs:
  namenode clusterID = CID-abc123
  datanode clusterID = CID-xyz789
```

**원인**: NameNode가 재포맷되어 새 clusterID가 생성됐지만 DataNode PVC에 이전 clusterID 데이터가 남아있음.

**해결**: DataNode의 데이터 디렉터리를 초기화한다.

```bash
DN_POD=$(kubectl get pod -n hadoop -l app=hdfs-datanode-worker-01 -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $DN_POD -- rm -rf /data/hdfs/current
kubectl rollout restart deployment hdfs-datanode-worker-01 hdfs-datanode-worker-02 hdfs-datanode-worker-03 -n hadoop
```

> ⚠️ **주의**: 이 작업은 DataNode의 모든 블록 데이터를 삭제한다.

#### 원인 B: hostname 역방향 DNS 조회 실패

**확인 방법:**

```bash
kubectl logs -n hadoop <datanode-pod> | grep -iE "denied|hostname|resolve"
```

로그 예시:

```bash
Datanode denied communication with namenode because hostname cannot be resolved
(ip=10.244.x.x, hostname=10.244.x.x)
```

**해결**: `hdfs-site.xml`에 아래 설정 추가

```xml
<property>
  <name>dfs.namenode.datanode.registration.ip-hostname-check</name>
  <value>false</value>
</property>
```

ConfigMap 업데이트 후 전체 재시작:

```bash
kubectl apply -n hadoop -f k8s/config/hadoop-configmap.yaml
kubectl rollout restart deployment hdfs-namenode hdfs-datanode-worker-01 hdfs-datanode-worker-02 hdfs-datanode-worker-03 -n hadoop
```

## 🔄 YARN 관련

### ❌ 잡이 ACCEPTED 상태에서 멈춤 (AM 미실행)

**증상**: `yarn application -status <app_id>` 에서 상태가 계속 `ACCEPTED`

**확인 방법:**

```bash
RM_POD=$(kubectl get pod -n hadoop -l app=yarn-resourcemanager -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $RM_POD -- yarn application -status <app_id>
```

#### 원인 A: NodeManager가 hostname으로 등록됨

**확인 방법:**

```bash
kubectl exec -n hadoop $RM_POD -- yarn node -list
```

Node-Id 컬럼이 아래처럼 hostname 형식이면 문제:

```bash
# ❌ 잘못된 경우 (DNS 조회 불가)
yarn-nodemanager-worker-01-557c8ccf78-784mv:8041

# ✅ 올바른 경우 (IP 형식)
10.244.0.5:8041
```

**해결**: NodeManager yaml의 시작 스크립트에서 `/etc/hosts` 수정 및 `MY_POD_IP` 주입이 정상 동작하는지 확인.
[YARN 배포 문서](04-yarn.md) 참고.

#### 원인 B: classpath 미설정

**증상**: AM 컨테이너가 클래스를 찾지 못해 바로 실패

**해결**: `yarn-site.xml`에 추가

```xml
<property>
  <name>yarn.application.classpath</name>
  <value>$HADOOP_CONF_DIR,$HADOOP_COMMON_HOME/share/hadoop/common/*,$HADOOP_COMMON_HOME/share/hadoop/common/lib/*,$HADOOP_HDFS_HOME/share/hadoop/hdfs/*,$HADOOP_HDFS_HOME/share/hadoop/hdfs/lib/*,$HADOOP_YARN_HOME/share/hadoop/yarn/*,$HADOOP_YARN_HOME/share/hadoop/yarn/lib/*</value>
</property>
```

#### 원인 C: ResourceManager Service에 8030 포트 누락

**증상**: 잡 Diagnostics에 아래 메시지

```bash
AM container is launched, waiting for AM container to Register with RM
```

**확인 방법:**

```bash
kubectl get service yarn-resourcemanager -n hadoop
```

8030 포트가 없으면:

```bash
kubectl apply -n hadoop -f k8s/yarn/resourcemanager-service.yaml
```

### ❌ 잡 실행 직후 FAILED: mapreduce_shuffle 오류

**증상**: 컨테이너 실행 시 바로 실패, 로그에 아래 메시지

```bash
InvalidAuxServiceException: The auxService:mapreduce_shuffle does not exist
```

**해결**: `yarn-site.xml`에 추가

```xml
<property>
  <name>yarn.nodemanager.aux-services</name>
  <value>mapreduce_shuffle</value>
</property>
<property>
  <name>yarn.nodemanager.aux-services.mapreduce_shuffle.class</name>
  <value>org.apache.hadoop.mapred.ShuffleHandler</value>
</property>
```

ConfigMap 업데이트 후 NodeManager 재시작:

```bash
kubectl apply -n hadoop -f k8s/config/hadoop-configmap.yaml
kubectl rollout restart deployment yarn-nodemanager-worker-01 yarn-nodemanager-worker-02 yarn-nodemanager-worker-03 -n hadoop
```

## 🐳 Kubernetes 관련

### ❌ `sed -i` 실패: Device or resource busy

**증상**: NodeManager 시작 스크립트에서 아래 에러

```bash
sed: cannot rename /etc/hosts...: Device or resource busy
```

**원인**: `/etc/hosts`는 Kubernetes가 bind-mount하여 제공한다.
`sed -i`는 파일을 삭제하고 새 파일로 교체하는 방식이라 bind-mount에서 실패한다.

**해결**: 임시 파일에 쓴 후 기존 파일에 덮어쓰기로 변경

```bash
# ❌ 실패하는 방법
sed -i "s/pattern/replacement/" /etc/hosts

# ✅ 동작하는 방법
cat /etc/hosts | sed "s/pattern/replacement/" > /tmp/hosts.new
cat /tmp/hosts.new > /etc/hosts
```

### ❌ ConfigMap 마운트된 파일을 `sed -i`로 편집 실패

**원인**: ConfigMap은 심볼릭 링크로 마운트된다. `sed -i`는 symlink에서 실패한다.

**해결**: 일반 파일로 복사 후 편집

```bash
mkdir -p /tmp/hadoop-conf
for f in /etc/hadoop/*.xml; do
  cat "$f" > "/tmp/hadoop-conf/$(basename $f)"
done
# 이후 /tmp/hadoop-conf/*.xml을 편집하고 HADOOP_CONF_DIR=/tmp/hadoop-conf로 설정
```

## 📋 빠른 진단 명령어 모음

```bash
# 전체 Pod 상태
kubectl get pods -n hadoop -o wide

# 특정 Pod 로그 (최근 50줄)
kubectl logs -n hadoop <pod-name> --tail=50

# HDFS 상태 한 줄 요약
kubectl exec -n hadoop $(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}') \
  -- hdfs dfsadmin -report 2>/dev/null | grep -E "Live|Configured Capacity|DFS Used"

# YARN 노드 상태
kubectl exec -n hadoop $(kubectl get pod -n hadoop -l app=yarn-resourcemanager -o jsonpath='{.items[0].metadata.name}') \
  -- yarn node -list 2>/dev/null

# PV/PVC 상태
kubectl get pv,pvc -n hadoop
```

## 🔥 Spark 관련

### `bash: spark-submit: command not found`

**원인**: 컨테이너 `PATH`에 `/opt/spark/bin`이 없음.

**해결**: `spark-client.yaml` 및 `spark-thriftserver.yaml`의 `env` 항목에 아래 추가.

```yaml
- name: PATH
  value: /opt/spark/bin:/opt/java/openjdk/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
```

### `--deploy-mode client` 에서 `UnknownHostException: spark-client-xxxxx`

**원인**: client 모드에서 Spark Driver는 `spark-client` Pod 위에서 실행된다.
Executor(NodeManager 컨테이너)가 Driver에게 다시 접속할 때 Pod hostname(`spark-client-xxxxx`)을
DNS 조회하는데, NodeManager 환경에서 해당 hostname이 해석되지 않아 연결 실패.

**해결**: `--deploy-mode cluster` 사용. Driver가 NodeManager 안에서 실행되므로 hostname 문제 없음.

Thrift Server처럼 반드시 client 모드가 필요한 경우에는 아래 옵션으로 IP 직접 통신:

```bash
--conf spark.driver.host=${MY_POD_IP}   # Downward API로 Pod IP 주입
--conf spark.driver.bindAddress=0.0.0.0
```

### Spark UI NodePort로 접근 시 내부 주소로 리다이렉트

**현상**: `http://YOUR_NODE_IP:30404` 접근 시 `http://yarn-resourcemanager:8090/proxy/...`로 리다이렉트.

**원인**: 실행 중인 Spark 잡의 UI는 YARN ResourceManager 프록시를 통해 제공된다.
프록시가 클러스터 내부 hostname으로 리다이렉트하므로 외부에서 접근 불가.

**해결**:

- **실행 중 잡**: YARN Web UI → `http://YOUR_NODE_IP:30890/cluster/apps` → 해당 Application 클릭
- **완료된 잡**: Spark History Server → `http://YOUR_NODE_IP:30180`

NodePort 30404는 불필요하므로 `spark-thriftserver-service.yaml`에서 제거함.

### DBeaver `PATH_NOT_FOUND` 오류

**현상**: `SELECT * FROM json.hdfs:///data/logs.json;` 실행 시

```
[PATH_NOT_FOUND] Path does not exist: hdfs://hdfs-namenode:8020/data/logs.json
```

**원인**: HDFS에 해당 파일이 실제로 존재하지 않음.

**해결**: 파일을 먼저 HDFS에 업로드한 후 쿼리 실행.

```bash
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $NN_POD -- bash -c '
hdfs dfs -mkdir -p /data
echo "[{\"id\":1,\"city\":\"Seoul\",\"value\":100},{\"id\":2,\"city\":\"Busan\",\"value\":200}]" \
  | hdfs dfs -put - /data/logs.json
'
```

업로드 확인 후 DBeaver에서 재실행:

```sql
SELECT * FROM json.`hdfs:///data/logs.json`;
```

## 🐝 Hive Metastore 관련

### `No suitable driver` — JDBC 드라이버 없음

**현상**: Hive Metastore Pod가 CrashLoopBackOff

```
Exception in thread "main" MetaException(message:java.sql.SQLException: No suitable driver)
```

**원인**: `apache/hive:4.0.0` 이미지에 PostgreSQL JDBC 드라이버가 포함되어 있지 않음.
이미지 내에 `wget`/`curl`도 없어서 컨테이너 내에서 직접 다운로드 불가.

**해결**: `initContainer`(alpine)에서 드라이버를 다운로드 후 `emptyDir` 볼륨으로 공유.

```yaml
initContainers:
  - name: download-jdbc
    image: alpine:3.19
    command: ["sh", "-c"]
    args:
      - |
        wget -q -O /jdbc/postgresql-jdbc.jar \
          https://jdbc.postgresql.org/download/postgresql-42.7.3.jar
    volumeMounts:
      - name: jdbc-driver
        mountPath: /jdbc
containers:
  - name: hive-metastore
    volumeMounts:
      - name: jdbc-driver
        mountPath: /opt/hive/lib/postgresql-jdbc.jar
        subPath: postgresql-jdbc.jar
volumes:
  - name: jdbc-driver
    emptyDir: {}
```

### DBeaver `Error retrieving next row` (CREATE TABLE 실행 시)

**현상**: DBeaver에서 CREATE TABLE 실행 후 `Error retrieving next row` 표시

**원인**: DDL 문은 행을 반환하지 않는데 DBeaver Hive JDBC 드라이버가 결과 행을 읽으려다 발생하는 클라이언트 측 표시 오류. 실제 서버에서 테이블은 정상 생성됨.

**확인**: `SHOW TABLES;` 실행 후 테이블이 보이면 정상.

**해결**: 무시해도 됨. Spark Thrift Server 로그에 실제 에러 여부 확인:

```bash
kubectl logs -n hadoop -l app=spark-thriftserver --tail=20 | grep -i error
```

### `WARN HiveExternalCatalog: Couldn't find corresponding Hive SerDe for data source provider csv`

**현상**: CSV 테이블 생성 시 WARN 로그 출력

```bash
Persisting data source table into Hive metastore in Spark SQL specific format,
which is NOT compatible with Hive.
```

**원인**: CSV는 Hive 네이티브 SerDe가 없어 Spark SQL 전용 포맷으로 저장됨.

**영향**: Spark에서는 완전히 정상 동작. 순수 Hive CLI에서는 읽지 못할 수 있음(현재 환경에서는 Hive CLI 미사용이므로 무관).

**해결**: 무시해도 됨. Parquet 포맷으로 변환하면 경고 사라짐:

```sql
CREATE TABLE sales_parquet
USING parquet
LOCATION 'hdfs:///warehouse/sales_parquet'
AS SELECT * FROM sales;
```

## 🦁 ZooKeeper / HBase 문제

### ZooKeeper `nc: command not found`

**현상**: readinessProbe가 계속 실패, Pod가 Ready 상태가 되지 않음

```bash
sh: nc: command not found
```

**원인**: 일부 경량 이미지에 `nc`(netcat)가 없음. `zookeeper:3.8` 이미지는 기본 포함되어 있으나 다른 버전에서는 없을 수 있음.

**해결**: readinessProbe를 `tcpSocket`으로 변경:

```yaml
readinessProbe:
  tcpSocket:
    port: 2181
  initialDelaySeconds: 15
  periodSeconds: 10
```

### HBase Master `ImagePullBackOff` (apache/hbase)

**현상**:

```
Failed to pull image "apache/hbase:2.5.9": ... pull access denied
```

**원인**: Docker Hub의 `apache/hbase` 공식 이미지는 인증이 필요하거나 접근이 제한되어 있음.

**해결**: 공개 이미지인 `harisekhon/hbase:2.1`으로 교체:

```yaml
image: harisekhon/hbase:2.1
```

> ⚠️ `harisekhon/hbase`는 HBase 2.1 기반으로 경로가 `/hbase`이며, 공식 이미지(`/opt/hbase`)와 바이너리 경로가 다름.

---

### HBase RegionServer `Permission denied: user=root, access=WRITE, inode="/hbase"`

**현상**: RegionServer 로그에 아래 에러 출력 후 종료:

```bash
org.apache.hadoop.security.AccessControlException: Permission denied: user=root, access=WRITE, inode="/hbase"
```

**원인**: HDFS `/hbase` 디렉토리 권한이 755로, root 유저(컨테이너 실행 유저)가 쓰기 불가.

**해결**: NameNode Pod에서 권한 변경:

```bash
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $NN_POD -- hdfs dfs -chmod 777 /hbase
```

### HBase RegionServer `UnknownHostException: hbase-master-<hash>`

**현상**: RegionServer Pod 로그:

```bash
java.net.UnknownHostException: hbase-master-7cb4b5c664-j6tpw
```

**원인**: HBase Master가 ZooKeeper에 Kubernetes Pod의 자동 생성 hostname(예: `hbase-master-7cb4b5c664-j6tpw`)을 등록함. 이 이름은 다른 Pod에서 DNS로 해석 불가.

**해결**: `hbase-master.yaml`의 Pod spec에 hostname 고정:

```yaml
spec:
  template:
    spec:
      hostname: hbase-master # ← 이 줄 추가
      containers: ...
```

이렇게 하면 Master Pod가 `hbase-master`라는 이름으로 인식되고, 같은 이름의 Kubernetes Service를 통해 모든 Pod에서 DNS 해석 가능.

> **재배포 시 ZooKeeper ZNode 초기화 필요**: 이전 hostname이 ZK에 남아 있으면 충돌 발생.
>
> ```bash
> ZK_POD=$(kubectl get pod -n hadoop -l app=zookeeper -o jsonpath='{.items[0].metadata.name}')
> kubectl exec -n hadoop $ZK_POD -- /apache-zookeeper-*/bin/zkCli.sh deleteall /hbase
> ```
>
> 이후 `kubectl rollout restart deployment/hbase-master -n hadoop` 으로 재시작.

### HBase RegionServer가 ZooKeeper에 등록되지 않음

**현상**: `status` 명령에서 서버 수가 0으로 표시됨.

**확인**:

```bash
ZK_POD=$(kubectl get pod -n hadoop -l app=zookeeper -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $ZK_POD -- /apache-zookeeper-*/bin/zkCli.sh ls /hbase/rs
# []  ← 빈 경우 RegionServer 미등록
```

**원인**: ZooKeeper가 아직 기동 중이거나, RegionServer가 `hbase.zookeeper.quorum` 주소를 찾지 못함.

**해결**:

1. ZooKeeper Pod가 `1/1 Running`인지 확인
2. `hbase-site.xml`의 `hbase.zookeeper.quorum` 값이 `zookeeper` (Service명)인지 확인
3. RegionServer Pod 재시작: `kubectl rollout restart deployment/hbase-regionserver-worker-01 -n hadoop` (필요 시 `worker-02`/`worker-03` 배포도 동일)
