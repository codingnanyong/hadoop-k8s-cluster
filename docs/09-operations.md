# 🛠️ 운영 가이드

[← README로 돌아가기](../README.md)

## 📊 클러스터 상태 확인

### 전체 Pod 상태

```bash
kubectl get pods -n hadoop
```

### HDFS 상태

```bash
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')

# DataNode 등록 현황 및 용량 확인
kubectl exec -n hadoop $NN_POD -- hdfs dfsadmin -report

# 파일시스템 상태 확인
kubectl exec -n hadoop $NN_POD -- hdfs dfs -ls /
```

### YARN 상태

```bash
RM_POD=$(kubectl get pod -n hadoop -l app=yarn-resourcemanager -o jsonpath='{.items[0].metadata.name}')

# NodeManager 목록 확인
kubectl exec -n hadoop $RM_POD -- yarn node -list

# 실행 중인 애플리케이션 확인
kubectl exec -n hadoop $RM_POD -- yarn application -list
```

## 📁 HDFS 파일 작업

```bash
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')

# 디렉터리 생성
kubectl exec -n hadoop $NN_POD -- hdfs dfs -mkdir -p /user/hadoop

# 로컬 파일 → HDFS 업로드
kubectl exec -n hadoop $NN_POD -- bash -c "echo 'hello hadoop' | hdfs dfs -put - /user/hadoop/test.txt"

# HDFS 파일 읽기
kubectl exec -n hadoop $NN_POD -- hdfs dfs -cat /user/hadoop/test.txt

# 파일 목록 조회
kubectl exec -n hadoop $NN_POD -- hdfs dfs -ls /user/hadoop/

# 파일 블록 위치 확인
kubectl exec -n hadoop $NN_POD -- hdfs fsck /user/hadoop/test.txt -files -blocks -locations
```

## 🏃 MapReduce 잡 실행

### Pi 예제 (기본 동작 확인용)

```bash
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')

# 작은따옴표로 감싸서 glob 확장을 Pod 내부 쉘에서 처리하도록 함
kubectl exec -n hadoop $NN_POD -- \
  bash -c 'yarn jar /opt/hadoop/share/hadoop/mapreduce/hadoop-mapreduce-examples-*.jar pi 4 100'
```

성공 시 마지막 출력:

```bash
Estimated value of Pi is 3.14250000000000000000
```

### WordCount 예제

```bash
# 입력 데이터 준비
kubectl exec -n hadoop $NN_POD -- hdfs dfs -mkdir -p /input
kubectl exec -n hadoop $NN_POD -- bash -c \
  "echo 'hadoop yarn hdfs hadoop mapreduce' | hdfs dfs -put - /input/words.txt"

# WordCount 실행
kubectl exec -n hadoop $NN_POD -- \
  bash -c 'yarn jar /opt/hadoop/share/hadoop/mapreduce/hadoop-mapreduce-examples-*.jar wordcount /input /output'

# 결과 확인
kubectl exec -n hadoop $NN_POD -- hdfs dfs -cat /output/part-r-00000
```

### 잡 상태 모니터링

```bash
RM_POD=$(kubectl get pod -n hadoop -l app=yarn-resourcemanager -o jsonpath='{.items[0].metadata.name}')

# 전체 애플리케이션 목록
kubectl exec -n hadoop $RM_POD -- yarn application -list -appStates ALL

# 특정 잡 상세 정보
kubectl exec -n hadoop $RM_POD -- yarn application -status <application_id>

# 잡 로그 확인
kubectl exec -n hadoop $RM_POD -- yarn logs -applicationId <application_id>
```

## ⚙️ 설정 변경 방법

### 1. ConfigMap 수정

```bash
# 파일 수정 후 apply
kubectl apply -n hadoop -f k8s/config/hadoop-configmap.yaml

# 또는 직접 편집
kubectl edit configmap hadoop-config -n hadoop
```

### 2. 관련 Pod 재시작

설정 변경 후 반드시 관련 Pod를 재시작해야 반영된다.

```bash
# HDFS 전체 재시작
kubectl rollout restart deployment hdfs-namenode -n hadoop
kubectl rollout restart deployment hdfs-datanode-worker-01 hdfs-datanode-worker-02 hdfs-datanode-worker-03 -n hadoop

# YARN 전체 재시작
kubectl rollout restart deployment yarn-resourcemanager -n hadoop
kubectl rollout restart deployment yarn-nodemanager-worker-01 yarn-nodemanager-worker-02 -n hadoop
```

### 실험 가능한 주요 설정

| 설정                                       | 기본값            | 설명                                                         |
| ------------------------------------------ | ----------------- | ------------------------------------------------------------ |
| `yarn.nodemanager.resource.memory-mb`      | `32768`           | NodeManager당 최대 메모리 (MB)                               |
| `yarn.nodemanager.resource.cpu-vcores`     | `8`               | NodeManager당 최대 vCore 수                                  |
| `yarn.scheduler.maximum-allocation-mb`     | `32768`           | 컨테이너 1개당 최대 메모리                                   |
| `yarn.scheduler.maximum-allocation-vcores` | `8`               | 컨테이너 1개당 최대 vCore                                    |
| `dfs.replication`                          | `3`               | HDFS 블록 복제 수 (DataNode 수 이하로 설정; 3 DN이면 최대 3) |
| `yarn.resourcemanager.scheduler.class`     | CapacityScheduler | FairScheduler로 변경 가능                                    |

## 🔄 재시작 절차

### 안전한 순서

```text
재시작 순서: NameNode → DataNode → ResourceManager → NodeManager
```

```bash
# 1. NameNode 재시작 (메타데이터 PVC에서 자동 복구)
kubectl rollout restart deployment hdfs-namenode -n hadoop
kubectl rollout status deployment hdfs-namenode -n hadoop

# 2. DataNode 재시작 (clusterID 검증 후 등록)
kubectl rollout restart deployment hdfs-datanode-worker-01 hdfs-datanode-worker-02 hdfs-datanode-worker-03 -n hadoop

# 3. YARN 재시작
kubectl rollout restart deployment yarn-resourcemanager yarn-nodemanager-worker-01 yarn-nodemanager-worker-02 yarn-nodemanager-worker-03 -n hadoop
```

## 📈 YARN 리소스 실험

ConfigMap에서 메모리/CPU 설정을 바꿔가며 잡 실행 동작 변화를 관찰한다.

```bash
# 예시: 메모리를 줄여서 컨테이너 수 변화 관찰
# yarn-site.xml에서 yarn.nodemanager.resource.memory-mb = 8192 로 변경 후

kubectl apply -n hadoop -f k8s/config/hadoop-configmap.yaml
kubectl rollout restart deployment yarn-nodemanager-worker-01 yarn-nodemanager-worker-02 -n hadoop

# 동일한 pi 잡 실행 후 YARN Web UI에서 컨테이너 수 / 메모리 배분 확인
```

## 🔥 Spark 운영

### Spark Pod 상태 확인

```bash
kubectl get pods -n hadoop | grep spark
```

### Spark Thrift Server 재시작

```bash
kubectl rollout restart deployment spark-thriftserver -n hadoop
# 정상 기동 확인
kubectl logs -n hadoop -l app=spark-thriftserver --tail=10
```

### Spark History Server 재시작

```bash
kubectl rollout restart deployment spark-history-server -n hadoop
```

### YARN에서 Spark 잡 목록 확인

```bash
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $NN_POD -- yarn application -list -appStates ALL
```

### HDFS에서 Spark 데이터 관리

```bash
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')

# 이벤트 로그 확인
kubectl exec -n hadoop $NN_POD -- hdfs dfs -ls /spark-logs

# 오래된 로그 정리 (30일 이상)
kubectl exec -n hadoop $NN_POD -- hdfs dfs -ls /spark-logs | \
  awk '{print $NF}' | xargs -I{} hdfs dfs -rm -r {}

# Spark staging 영역 확인
kubectl exec -n hadoop $NN_POD -- hdfs dfs -ls /spark-staging
```
