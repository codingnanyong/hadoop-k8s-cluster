# 🐝 Hive Metastore

[← README로 돌아가기](../README.md)

## 📐 개요

Hive Metastore는 **테이블 스키마와 HDFS 위치를 영구 저장**하는 서비스입니다.
Spark Thrift Server가 재시작되어도 테이블 정의가 유지됩니다.

```text
DBeaver
    │  CREATE TABLE / SELECT
    ▼
Spark Thrift Server
    │  테이블 메타데이터 조회/저장
    ▼
Hive Metastore (:9083)
    │  JDBC (PostgreSQL driver)
    ▼
PostgreSQL (호스트/클러스터 내 서비스 — 예: YOUR_PG_HOST:5432 / DB: metastore)

Spark Thrift Server
    │  실제 데이터 읽기
    ▼
HDFS (hdfs:///warehouse/...)
```

### Hive Metastore가 없으면

```
Spark Thrift Server 재시작
    └── 테이블 정의 전부 사라짐 ❌  (내장 Derby 임시 DB 초기화)

Hive Metastore 있으면
    └── PostgreSQL에 영구 저장 → 재시작 후에도 테이블 유지 ✅
```

## 📁 파일 구성

```text
k8s/hive/
├── hive-configmap.yaml              # 비밀 없는 기본 hive-site (hive-site-base.xml)
├── hive-metastore-db-secret.example.yaml   # 복사 후 값 채우기 (실파일은 gitignore)
└── hive-metastore.yaml              # initContainer가 Secret으로 전체 hive-site.xml 생성
```

**JDBC URL / 사용자 / 비밀번호는 Git에 넣지 마세요.** `hive-metastore-db-secret.yaml`은 로컬에서만 유지합니다.

## ⚙️ 설정 요약

- **ConfigMap** (`hive-site-base.xml`): `hive.metastore.uris`, warehouse, `fs.defaultFS` 등 비밀이 아닌 항목만 포함합니다.
- **Secret** (`hive-metastore-db`): `connection-url`, `username`, `password` 키 — Metastore Pod의 `render-hive-site` initContainer가 이 값으로 `javax.jdo.*` 속성을 생성합니다.

## 🔑 PostgreSQL 사전 작업

관리자 계정으로 `metastore` 데이터베이스를 만듭니다 (호스트·포트·유저는 환경에 맞게 변경):

```bash
psql "postgresql://ADMIN_USER:ADMIN_PASSWORD@YOUR_PG_HOST:5432/postgres" \
  -c "CREATE DATABASE metastore OWNER hive_owner;"
```

## 🚀 배포

### 사전 조건 — HDFS warehouse 디렉토리 생성

```bash
NN_POD=$(kubectl get pod -n hadoop -l app=hdfs-namenode -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hadoop $NN_POD -- hdfs dfs -mkdir -p /warehouse
kubectl exec -n hadoop $NN_POD -- hdfs dfs -chmod 777 /warehouse
```

### Secret 생성 후 적용

```bash
cp k8s/hive/hive-metastore-db-secret.example.yaml k8s/hive/hive-metastore-db-secret.yaml
# hive-metastore-db-secret.yaml 편집 (JDBC URL, 사용자, 비밀번호)
kubectl apply -f k8s/hive/hive-metastore-db-secret.yaml
kubectl apply -n hadoop -f k8s/hive/hive-configmap.yaml
kubectl apply -n hadoop -f k8s/hive/hive-metastore.yaml
```

## 🔌 DBeaver (Spark Thrift Server)

| 항목            | 값 (예시 — 노드 IP는 환경에 맞게)                    |
| --------------- | ---------------------------------------------------- |
| JDBC URL        | `jdbc:hive2://YOUR_NODE_IP:30100/default`            |
| Host            | `YOUR_NODE_IP`                                       |
| Port            | `30100`                                              |
| User / Password | Thrift Server 설정에 따름 (기본은 비어 있을 수 있음) |

Metastore DB(PostgreSQL) 접속 정보는 **Hive Metastore용 Secret**에만 두고, DBeaver에는 Spark Thrift 주소만 사용하는 구성이 일반적입니다.

---

문서의 `YOUR_NODE_IP`, `YOUR_PG_HOST` 등은 **자리 표시자**입니다. 실제 주소로 바꿔 사용하세요.
