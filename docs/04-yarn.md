# 🔄 YARN

[← README로 돌아가기](../README.md)

## 📐 개요

**YARN(Yet Another Resource Negotiator)**은 클러스터의 CPU·메모리 자원을 관리하고 잡을 스케줄링하는 Hadoop의 자원 관리 레이어입니다.

```text
클라이언트 (spark-submit, yarn jar 등)
    │  잡 제출
    ▼
ResourceManager (:8032)    ← 자원 할당 결정, 잡 스케줄링
    │  컨테이너 실행 명령
    ▼
NodeManager × 3            ← JVM 컨테이너(프로세스) 실행
    worker-01  yarn-nodemanager-worker-01
    worker-02  yarn-nodemanager-worker-02
    worker-03  yarn-nodemanager-worker-03
    │
    └── ApplicationMaster (잡 드라이버)
        └── Executor/Task 컨테이너
```

| 컴포넌트              | 역할                                                            |
| --------------------- | --------------------------------------------------------------- |
| **ResourceManager**   | 전체 클러스터 자원 현황 파악, 잡 큐 관리                        |
| **NodeManager**       | 각 노드의 CPU·메모리 보고, 컨테이너 실행·종료                   |
| **ApplicationMaster** | 잡 1개당 1개 생성, 실제 태스크 조율 (Spark의 경우 Spark Driver) |

> **YARN 컨테이너는 새 Kubernetes Pod가 아닙니다.** NodeManager Pod 안에서 실행되는 JVM 프로세스입니다.

## 🎛️ ResourceManager

### 파일: `k8s/yarn/resourcemanager.yaml`

worker-01에 고정 배치되며 클러스터 전체 잡 스케줄링을 담당한다.

### 파일: `k8s/yarn/resourcemanager-service.yaml`

> ⚠️ **AM ↔ RM 통신을 위해 8030 포트가 반드시 포함되어야 한다.**
> 누락 시 잡이 `ACCEPTED` 상태에서 영원히 멈춘다.

| 포트 이름         | 포트 | 용도                                   |
| ----------------- | ---- | -------------------------------------- |
| `scheduler`       | 8030 | ApplicationMaster ↔ RM 통신 (**필수**) |
| `resourcetracker` | 8031 | NodeManager ↔ RM 자원 보고             |
| `rpc`             | 8032 | 클라이언트 → RM 잡 제출                |
| `admin`           | 8033 | 관리 명령                              |
| `web`             | 8090 | Web UI (NodePort **30890**)            |

## ⚙️ NodeManager

### 파일: `k8s/yarn/nodemanager-worker-01.yaml`, `nodemanager-worker-02.yaml`, `nodemanager-worker-03.yaml`

NodeManager는 Kubernetes 환경에서 두 가지 특수한 처리가 필요하다.

### 문제 1: NodeManager가 Pod hostname으로 등록되는 문제

**원인**: Kubernetes CoreDNS가 Pod IP에 대한 PTR 레코드를 Pod hostname으로 반환한다.
Hadoop은 IP를 역방향 DNS 조회하여 NodeId를 결정하므로, Pod hostname이 NodeId가 된다.
하지만 Pod hostname은 다른 컴포넌트에서 DNS 조회가 되지 않아 AM 컨테이너 실행 실패로 이어진다.

**해결**: `/etc/hosts`에 `IP → IP` 매핑을 추가하여 역방향 DNS 조회 결과를 IP로 고정한다.

```bash
# /etc/hosts 수정 전
10.244.0.5  yarn-nodemanager-worker-01-557c8ccf78-784mv

# /etc/hosts 수정 후 (IP 매핑 라인 추가)
10.244.0.5  10.244.0.5                               ← 역방향 조회 시 이 줄이 먼저 매칭됨
10.244.0.5  yarn-nodemanager-worker-01-557c8ccf78-784mv ← forward 조회는 여전히 동작
```

### 문제 2: ConfigMap이 심볼릭 링크로 마운트되어 `sed -i` 실패

**원인**: Kubernetes ConfigMap은 컨테이너에 심볼릭 링크로 마운트된다.
`sed -i`는 파일을 임시 파일로 교체하는 방식이라 bind-mount에서 실패한다.

**해결**: 먼저 ConfigMap 파일을 일반 파일로 복사한 뒤 `sed`로 편집한다.

### 시작 스크립트 전체 흐름

```yaml
securityContext:
  runAsUser: 0 # /etc/hosts 수정에 root 권한 필요

command: ["bash", "-c"]
args:
  - |
    # ① /etc/hosts에 IP→IP 매핑 삽입 (역방향 DNS 고정)
    cat /etc/hosts \
      | sed "/^${MY_POD_IP}[[:space:]]/i ${MY_POD_IP}\t${MY_POD_IP}" \
      > /tmp/hosts.new && cat /tmp/hosts.new > /etc/hosts

    # ② ConfigMap 심볼릭 링크 → 일반 파일로 복사
    mkdir -p /tmp/hadoop-conf
    for f in /etc/hadoop/*.xml; do
      cat "$f" > "/tmp/hadoop-conf/$(basename $f)"
    done

    # ③ yarn-site.xml에 Pod IP 기반 NM 주소 주입
    sed -i "s|[[:space:]]*</configuration>|\
      <property><name>yarn.nodemanager.hostname</name><value>${MY_POD_IP}</value></property>\
      <property><name>yarn.nodemanager.address</name><value>${MY_POD_IP}:8041</value></property>\
      <property><name>yarn.nodemanager.webapp.address</name><value>${MY_POD_IP}:8042</value></property>\
      <property><name>yarn.nodemanager.localizer.address</name><value>${MY_POD_IP}:8040</value></property>\
      </configuration>|" /tmp/hadoop-conf/yarn-site.xml

    # ④ 수정된 설정 디렉터리로 NM 시작
    export HADOOP_CONF_DIR=/tmp/hadoop-conf
    yarn nodemanager

env:
  - name: MY_POD_IP
    valueFrom:
      fieldRef:
        fieldPath: status.podIP # Kubernetes Downward API
```

## 🚀 배포

```bash
kubectl apply -n hadoop -f k8s/yarn/
```

## ✅ 상태 확인

### Pod 상태

```bash
kubectl get pods -n hadoop -l 'app in (yarn-resourcemanager,yarn-nodemanager-worker-01,yarn-nodemanager-worker-02,yarn-nodemanager-worker-03)'
```

### NodeManager 등록 확인

```bash
RM_POD=$(kubectl get pod -n hadoop -l app=yarn-resourcemanager -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $RM_POD -- yarn node -list
```

정상 출력 (Node-Id가 IP:port 형식이어야 함):

```bash
Total Nodes:3
         Node-Id      Node-State  Node-Http-Address
10.244.0.5:8041         RUNNING  10.244.0.5:8042
10.244.1.3:8041         RUNNING  10.244.1.3:8042
10.244.2.7:8041         RUNNING  10.244.2.7:8042
```

> ⚠️ Node-Id가 `yarn-nodemanager-worker-01-xxxxx:8041` 처럼 hostname 형식이면
> AM이 NM에 접속 못해 잡이 실패한다. Pod IP 주입 스크립트를 확인하라.

### ResourceManager 로그 확인

```bash
kubectl logs -n hadoop -l app=yarn-resourcemanager --tail=30
```

## 🌐 Web UI 확인

http://YOUR_NODE_IP:30890 접속 후 확인 항목:

- **Cluster Metrics**: 등록된 노드 수, 총 메모리/vCore
- **Nodes**: 각 NodeManager 상태
- **Applications**: 실행 중 / 완료된 잡 목록
