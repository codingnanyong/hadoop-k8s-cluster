# 📦 HDFS

[← README로 돌아가기](../README.md)

## 📐 개요

**HDFS(Hadoop Distributed File System)**는 대용량 파일을 여러 노드에 분산 저장하는 파일시스템입니다.

```text
클라이언트
    │  파일 읽기/쓰기 요청
    ▼
NameNode (:8020)           ← 메타데이터 관리 (파일 이름, 블록 위치)
    │  블록 위치 안내
    ▼
DataNode × 3              ← 실제 데이터 블록 저장 (복제 계수 3)
    worker-01  /var/lib/hadoop-k8s/hdfs-data-worker-01
    worker-02  /var/lib/hadoop-k8s/hdfs-data-worker-02
    worker-03  /var/lib/hadoop-k8s/hdfs-data-worker-03
```

| 컴포넌트     | 역할                                                           |
| ------------ | -------------------------------------------------------------- |
| **NameNode** | 파일시스템 메타데이터 관리, 블록 위치 추적 (데이터 저장 안 함) |
| **DataNode** | 실제 파일 블록(128MB 단위)을 디스크에 저장                     |
| **PVC**      | Pod 재시작 후에도 NameNode 메타데이터·DataNode 블록 유지       |

## 🗂️ NameNode

### 파일: `k8s/hdfs/namenode.yaml`

**핵심 설계 포인트:**

#### 1. 조건부 포맷

NameNode는 **최초 1회만** 포맷한다. 재시작 시 기존 메타데이터를 그대로 사용한다.

```yaml
command: ["bash", "-c"]
args:
  - |
    if [ ! -d "/data/namenode/current" ]; then
      hdfs namenode -format -force -nonInteractive
    fi
    hdfs namenode
```

> ⚠️ **주의**: 조건 경로(`/data/namenode/current`)가 PVC 마운트 경로와 일치해야 한다.
> `/tmp`처럼 ephemeral 경로를 사용하면 재시작마다 포맷 → clusterID 변경 → DataNode 등록 실패가 반복된다.

#### 2. PVC 마운트

```yaml
volumeMounts:
  - name: namenode-data
    mountPath: /data/namenode # dfs.namenode.name.dir 경로와 일치
volumes:
  - name: namenode-data
    persistentVolumeClaim:
      claimName: hdfs-namenode-pvc
```

### 파일: `k8s/hdfs/namenode-service.yaml`

NameNode에 접속하기 위한 Service. 외부 Web UI 접속을 위해 NodePort 사용.

| 포트 이름 | 포트 | 용도                                  |
| --------- | ---- | ------------------------------------- |
| `rpc`     | 8020 | HDFS 파일 작업 (클라이언트, DataNode) |
| `http`    | 9870 | Web UI (NodePort **30870**)           |

## 📦 DataNode

### 파일: `k8s/hdfs/datanode-worker-01.yaml`, `datanode-worker-02.yaml`, `datanode-worker-03.yaml`

각 DataNode는 해당 노드에 **고정 배치**되고 PVC를 통해 블록 데이터를 영속화한다.

#### nodeSelector로 노드 고정

```yaml
spec:
  nodeSelector:
    kubernetes.io/hostname: worker-01 # worker-02는 worker-02로 설정
```

#### PVC 마운트

```yaml
volumeMounts:
  - name: hdfs-data
    mountPath: /data/hdfs # dfs.datanode.data.dir 경로와 일치
volumes:
  - name: hdfs-data
    persistentVolumeClaim:
      claimName: hdfs-datanode-pvc-worker-01 # worker-02/03는 pvc-worker-02/03
```

> ⚠️ **주의**: `rm -rf /data/hdfs/*`는 clusterID 초기화 목적으로 디버깅 시 사용하던 코드다.
> 현재는 제거되었으며, NameNode PVC 영속화 이후 사용하면 **데이터가 전부 삭제**된다.

## 🚀 배포

```bash
kubectl apply -n hadoop -f k8s/hdfs/
```

## ✅ 상태 확인

### Pod 상태

```bash
kubectl get pods -n hadoop -l 'app in (hdfs-namenode,hdfs-datanode-worker-01,hdfs-datanode-worker-02,hdfs-datanode-worker-03)'
```

### DataNode 등록 확인

```bash
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $NN_POD -- hdfs dfsadmin -report
```

정상 출력:

```bash
Live datanodes (3):
  Name: 10.244.0.x:9866 ...
  Name: 10.244.1.x:9866 ...
  Name: 10.244.2.x:9866 ...
```

### NameNode 로그 확인

```bash
kubectl logs -n hadoop -l app=hdfs-namenode --tail=30
```

## 🔒 clusterID 관리

NameNode와 DataNode는 **동일한 clusterID**를 가져야 한다.

```bash
# NameNode clusterID 확인
cat /var/lib/hadoop-k8s/hdfs-namenode/current/VERSION | grep clusterID

# DataNode clusterID 확인 (Pod 내부에서)
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $NN_POD -- cat /data/namenode/current/VERSION
```

> ⚠️ **NameNode를 수동으로 재포맷하면 clusterID가 변경**되어 DataNode 등록이 실패한다.
> 포맷 후에는 DataNode의 `/data/hdfs` 디렉터리도 초기화해야 한다.

## 🌐 Web UI 확인

http://YOUR_NODE_IP:30870 접속 후 확인 항목:

- **Overview**: 총 용량, 사용량, Live Nodes 수
- **Datanodes**: 각 DataNode의 상태 및 블록 수
- **Browse Directory**: HDFS 파일시스템 탐색
