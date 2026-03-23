# 🦁 ZooKeeper + HBase

[← README로 돌아가기](../README.md)

## 📐 개요

```text
클라이언트 (HBase Shell / Java API)
    │
    ▼
HBase Master (:16000, :16010)
    │  리전 배치 / 장애 감지
    ▼
HBase RegionServer × 2  (:16020, :16030)
    │  Row 데이터 실제 저장 및 서빙
    ▼
HDFS (/hbase)         ← HBase 데이터가 HDFS에 저장됨

    ↕  (모든 컴포넌트가 ZooKeeper를 통해 조율)

ZooKeeper (:2181)
    ├── /hbase/master         ← 현재 Active Master 주소
    ├── /hbase/rs             ← 등록된 RegionServer 목록
    └── /hbase/meta-region-server ← meta 테이블 위치
```

### ZooKeeper 역할

| 기능              | 설명                                        |
| ----------------- | ------------------------------------------- |
| Master 선출       | 여러 Master 중 Active Master 1개 결정       |
| RegionServer 등록 | RS 목록 관리, 장애 감지 (ZNode 만료)        |
| Meta 테이블 위치  | `hbase:meta` 테이블이 어느 RS에 있는지 기록 |
| 클라이언트 안내   | 클라이언트가 ZK에서 Master/RS 주소 조회     |

## 📁 파일 구성

```text
k8s/
├── zookeeper/
│   └── zookeeper.yaml              # ZooKeeper Deployment + Service
└── hbase/
    ├── hbase-configmap.yaml        # hbase-site.xml
    ├── hbase-master.yaml           # HMaster Deployment + Service (NodePort 30610)
    ├── hbase-regionserver-worker-01.yaml
    ├── hbase-regionserver-worker-02.yaml
    └── hbase-regionserver-worker-03.yaml
```

## ⚙️ hbase-site.xml 주요 설정

```xml
<!-- HBase 데이터 저장 위치 (기존 HDFS 재사용) -->
<property>
  <name>hbase.rootdir</name>
  <value>hdfs://hdfs-namenode:8020/hbase</value>
</property>

<!-- ZooKeeper 주소 (Kubernetes Service DNS) -->
<property>
  <name>hbase.zookeeper.quorum</name>
  <value>zookeeper</value>
</property>

<!-- 분산 모드 -->
<property>
  <name>hbase.cluster.distributed</name>
  <value>true</value>
</property>

<!-- WAL provider (개발 환경 호환성) -->
<property>
  <name>hbase.wal.provider</name>
  <value>filesystem</value>
</property>
```

## 🔑 Kubernetes Hostname 고정 (HBase Master)

HBase Master는 ZooKeeper에 자신의 hostname을 등록합니다.
RegionServer가 이 hostname으로 Master에 접속하므로 **DNS 해석 가능한 이름**이어야 합니다.

```yaml
spec:
  hostname: hbase-master # Pod hostname 고정
  nodeSelector:
    kubernetes.io/hostname: worker-01
```

Pod hostname을 `hbase-master`로 고정하면:

- ZooKeeper에 `hbase-master,16000,<startcode>`로 등록
- Kubernetes Service `hbase-master`가 같은 이름 → DNS 해석 성공
- RegionServer가 `hbase-master:16000`으로 정상 접속

### RegionServer hostname

RegionServer는 Pod IP를 hostname으로 사용합니다:

```yaml
env:
  - name: MY_POD_IP
    valueFrom:
      fieldRef:
        fieldPath: status.podIP
command: ["bash", "-c"]
args:
  - |
    export HBASE_OPTS="-Dhbase.regionserver.hostname=${MY_POD_IP}"
    exec /hbase/bin/hbase regionserver start
```

Pod IP는 Kubernetes Flannel 네트워크에서 클러스터 내 모든 Pod가 직접 접근 가능합니다.

## 🚀 배포

### 사전 조건 — HDFS /hbase 디렉토리

```bash
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $NN_POD -- hdfs dfs -mkdir -p /hbase
kubectl exec -n hadoop $NN_POD -- hdfs dfs -chmod 777 /hbase
```

> ⚠️ `/hbase` 권한이 755이면 HBase Master(root 유저)가 쓰기 실패합니다. 반드시 777로 설정.

### 배포 순서

```bash
# 1. ZooKeeper 먼저 (HBase가 의존)
kubectl apply -n hadoop -f k8s/zookeeper/zookeeper.yaml

# ZooKeeper Ready 확인
kubectl get pods -n hadoop -l app=zookeeper
# → 1/1 Running

# 2. HBase 배포
kubectl apply -n hadoop -f k8s/hbase/
```

### 기동 확인

```bash
# Pod 상태
kubectl get pods -n hadoop | grep -E 'zookeeper|hbase'

# ZooKeeper 상태
ZK_POD=$(kubectl get pod -n hadoop -l app=zookeeper -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $ZK_POD -- sh -c "echo ruok | nc localhost 2181"
# → imok

# HBase 클러스터 상태
HM_POD=$(kubectl get pod -n hadoop -l app=hbase-master -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $HM_POD -- bash -c "echo 'status' | /hbase/bin/hbase shell 2>/dev/null | grep -E 'active|servers'"
# → 1 active master, 0 backup masters, 2 servers
```

## 🖥️ HBase Shell 사용법

### 접속

```bash
HM_POD=$(kubectl get pod -n hadoop -l app=hbase-master -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it -n hadoop $HM_POD -- /hbase/bin/hbase shell
```

### 기본 명령어

```ruby
# 클러스터 상태
status

# 테이블 목록
list

# 테이블 생성 (컬럼 패밀리 'cf' 1개)
create 'users', 'cf'

# 데이터 삽입
put 'users', 'user1', 'cf:name', '홍길동'
put 'users', 'user1', 'cf:age',  '30'
put 'users', 'user2', 'cf:name', '김영희'
put 'users', 'user2', 'cf:age',  '25'

# 단건 조회 (Row Key 기반, 밀리초 응답)
get 'users', 'user1'

# 전체 스캔
scan 'users'

# 특정 컬럼만 조회
scan 'users', {COLUMNS => ['cf:name']}

# 행 수 카운트
count 'users'

# 행 삭제
delete 'users', 'user1', 'cf:age'

# 테이블 비활성화 후 삭제
disable 'users'
drop 'users'

# 종료
exit
```

## 📊 HBase vs HDFS 데이터 저장 비교

|                 | HDFS (파일)          | HBase (테이블)                              |
| --------------- | -------------------- | ------------------------------------------- |
| **접근 방식**   | 파일 단위 순차 읽기  | Row Key로 단건 조회                         |
| **응답 속도**   | 수 초 ~ 수 분        | 수 밀리초                                   |
| **데이터 구조** | 비정형 파일          | Row × Column Family × Qualifier × Timestamp |
| **수정**        | 불가 (append-only)   | 가능 (put으로 버전 추가)                    |
| **용도**        | 배치 분석, 로그 저장 | 실시간 단건 조회, 시계열                    |

## 🌐 Web UI

| URL                       | 내용                                                            |
| ------------------------- | --------------------------------------------------------------- |
| http://YOUR_NODE_IP:30610 | HBase Master UI — 클러스터 상태, RegionServer 목록, 테이블 목록 |

## ✅ 검증 명령어

```bash
HM_POD=$(kubectl get pod -n hadoop -l app=hbase-master -o jsonpath='{.items[0].metadata.name}')

# 클러스터 전체 테스트
kubectl exec -n hadoop $HM_POD -- bash -c "
echo \"
create 'test', 'cf'
put 'test', 'r1', 'cf:v', 'hello'
get 'test', 'r1'
disable 'test'
drop 'test'
exit
\" | /hbase/bin/hbase shell 2>/dev/null | grep -E 'Created|CELL|value'
"
# 기대 출력:
# Created table test
# CELL
# value=hello
```
