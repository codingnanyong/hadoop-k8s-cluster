# ⚙️ 초기 설치

[← README로 돌아가기](../README.md)

## ✅ 선행 조건

### 1. Kubernetes 클러스터

```bash
# 노드 상태 확인
kubectl get nodes

# 기대 결과 (DataNode 3대를 쓰려면 워커 노드가 최소 3개)
NAME      STATUS   ROLES           AGE
worker-01   Ready    control-plane   ...
worker-02   Ready    <none>          ...
worker-03   Ready    <none>          ...
```

### 2. 호스트 디렉터리 생성

각 노드에 HDFS 데이터를 저장할 디렉터리를 미리 생성해야 한다.

**worker-01에서 실행:**

```bash
sudo mkdir -p /var/lib/hadoop-k8s/hdfs-namenode      # NameNode 메타데이터
sudo mkdir -p /var/lib/hadoop-k8s/hdfs-data-worker-01  # DataNode 블록 데이터
sudo chmod 777 /var/lib/hadoop-k8s/hdfs-namenode
```

**worker-02에서 실행:**

```bash
sudo mkdir -p /var/lib/hadoop-k8s/hdfs-data-worker-02  # DataNode 블록 데이터
```

**worker-03에서 실행:**

```bash
sudo mkdir -p /var/lib/hadoop-k8s/hdfs-data-worker-03  # DataNode 블록 데이터
```

> 💡 **참고**: sudo 권한이 없는 환경에서는 아래처럼 privileged Pod를 임시로 띄워서 생성할 수 있다.

> ```bash
> kubectl run mkdir-job --image=busybox --restart=Never \
>   --overrides='{"spec":{"nodeSelector":{"kubernetes.io/hostname":"worker-01"},"hostPID":true,"containers":[{"name":"c","image":"busybox","command":["sh","-c","mkdir -p /host/var/lib/hadoop-k8s/hdfs-namenode && chmod 777 /host/var/lib/hadoop-k8s/hdfs-namenode"],"volumeMounts":[{"name":"root","mountPath":"/host"}],"securityContext":{"privileged":true}}],"volumes":[{"name":"root","hostPath":{"path":"/"}}]}}' -- sh
> kubectl logs mkdir-job && kubectl delete pod mkdir-job
> ```

## 🗂️ 네임스페이스 생성

```bash
kubectl create namespace hadoop
```

## 💾 스토리지 설정

### StorageClass

`local` 타입 PV를 위한 StorageClass. `WaitForFirstConsumer` 모드로 Pod 스케줄 이후 PVC가 바인딩된다.

```bash
kubectl apply -f k8s/storage/storageclass-local-hdfs.yaml
```

### PV 생성

```bash
kubectl apply -f k8s/storage/pv/
```

생성되는 PV 목록:

| PV 이름                      | 호스트    | 경로                                      | 크기  |
| ---------------------------- | --------- | ----------------------------------------- | ----- |
| `hdfs-namenode-pv`           | worker-01 | `/var/lib/hadoop-k8s/hdfs-namenode`       | 20Gi  |
| `hdfs-datanode-pv-worker-01` | worker-01 | `/var/lib/hadoop-k8s/hdfs-data-worker-01` | 500Gi |
| `hdfs-datanode-pv-worker-02` | worker-02 | `/var/lib/hadoop-k8s/hdfs-data-worker-02` | 500Gi |
| `hdfs-datanode-pv-worker-03` | worker-03 | `/var/lib/hadoop-k8s/hdfs-data-worker-03` | 500Gi |

### PVC 생성

```bash
kubectl apply -n hadoop -f k8s/storage/pvc/
```

### 상태 확인

```bash
kubectl get pv,pvc -n hadoop
```

기대 결과:

```bash
NAME                           CAPACITY  STATUS     CLAIM
hdfs-namenode-pv               20Gi      Available  (Pod 배포 전 상태)
hdfs-datanode-pv-worker-01       500Gi     Bound      hadoop/hdfs-datanode-pvc-worker-01
hdfs-datanode-pv-worker-02       500Gi     Bound      hadoop/hdfs-datanode-pvc-worker-02
hdfs-datanode-pv-worker-03       500Gi     Bound      hadoop/hdfs-datanode-pvc-worker-03
```

> ⚠️ `hdfs-namenode-pv`는 NameNode Pod가 worker-01에 스케줄된 후 `Bound` 상태로 전환된다.

## 📝 ConfigMap 설정

Hadoop 설정 파일 4개(`core-site.xml`, `hdfs-site.xml`, `yarn-site.xml`, `mapred-site.xml`)를 ConfigMap으로 관리한다.

```bash
kubectl apply -n hadoop -f k8s/config/hadoop-configmap.yaml
```

### 주요 설정값

| 설정 키                                                | 값                          | 파일          |
| ------------------------------------------------------ | --------------------------- | ------------- |
| `fs.defaultFS`                                         | `hdfs://hdfs-namenode:8020` | core-site.xml |
| `dfs.namenode.name.dir`                                | `file:/data/namenode`       | hdfs-site.xml |
| `dfs.datanode.data.dir`                                | `file:/data/hdfs`           | hdfs-site.xml |
| `dfs.replication`                                      | `3`                         | hdfs-site.xml |
| `dfs.namenode.datanode.registration.ip-hostname-check` | `false`                     | hdfs-site.xml |
| `yarn.nodemanager.resource.memory-mb`                  | `32768`                     | yarn-site.xml |
| `yarn.nodemanager.resource.cpu-vcores`                 | `8`                         | yarn-site.xml |
| `yarn.nodemanager.aux-services`                        | `mapreduce_shuffle`         | yarn-site.xml |

> **복제 수 3**: DataNode가 3대일 때 `dfs.replication=3`이 일반적입니다. **예전에 복제 수 2로만 쓰던 데이터**가 있으면, DN 추가 후 `hdfs dfs -setrep -R 3 /` 등으로 경로별 조정이 필요할 수 있습니다.

ConfigMap 수정 후에는 관련 Pod를 재시작해야 반영된다:

```bash
kubectl rollout restart deployment -n hadoop <deployment-name>
```
