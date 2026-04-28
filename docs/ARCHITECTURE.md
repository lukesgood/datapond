# DataPond Kubernetes 아키텍처 문서

**버전**: 2.0.0-k8s  
**작성일**: 2026-04-28  
**대상**: 개발자, DevOps, 아키텍트

---

## 📋 목차

1. [시스템 개요](#시스템-개요)
2. [전체 아키텍처](#전체-아키텍처)
3. [컴포넌트 구조](#컴포넌트-구조)
4. [네트워킹](#네트워킹)
5. [스토리지](#스토리지)
6. [보안](#보안)
7. [확장성](#확장성)
8. [고가용성](#고가용성)
9. [데이터 흐름](#데이터-흐름)
10. [기술 스택](#기술-스택)

---

## 시스템 개요

### 목적

DataPond는 데이터 분석, ML 실험, 워크플로우 관리를 위한 통합 플랫폼입니다. Kubernetes 네이티브 설계를 통해 확장성, 고가용성, 자동 복구를 제공합니다.

### 핵심 원칙

1. **Cloud Native**: Kubernetes 네이티브 설계
2. **Microservices**: 서비스별 독립 배포/스케일링
3. **Declarative**: Infrastructure as Code
4. **Immutable**: 컨테이너 기반 불변 인프라
5. **Observable**: 통합 모니터링/로깅
6. **Resilient**: 자동 복구 및 고가용성

---

## 전체 아키텍처

### 레이어 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    Ingress Layer                            │
│  (Traefik/Nginx - 단일 진입점, TLS 종료, 라우팅)              │
└─────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Application Layer                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Frontend │  │ Backend  │  │ Jupyter  │  │ Airflow  │   │
│  │ (Next.js)│  │(FastAPI) │  │   Lab    │  │Webserver │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                 │
│  │  MLflow  │  │  MinIO   │  │  Spark   │                 │
│  │          │  │(S3 API)  │  │ Master   │                 │
│  └──────────┘  └──────────┘  └──────────┘                 │
└─────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Data Layer                                │
│  ┌──────────────┐  ┌──────────┐  ┌──────────────────┐     │
│  │  PostgreSQL  │  │  Redis   │  │  Spark Workers   │     │
│  │  (Primary)   │  │  Cache   │  │  (Compute)       │     │
│  └──────────────┘  └──────────┘  └──────────────────┘     │
└─────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Storage Layer                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │PostgreSQL│  │  MinIO   │  │ Jupyter  │  │ Airflow  │   │
│  │   PVC    │  │   PVC    │  │   PVC    │  │   PVC    │   │
│  │  50Gi    │  │  100Gi   │  │  20Gi    │  │  20Gi    │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 논리적 구조

```
                    ┌─────────────────┐
                    │   Users/Clients │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │     Ingress     │
                    │  datapond.local │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
┌───────▼─────┐    ┌─────────▼───────┐    ┌──────▼──────┐
│  Frontend   │    │    Backend      │    │  Services   │
│  (UI/UX)    │───▶│    (API)        │───▶│ (Data/ML)   │
└─────────────┘    └─────────┬───────┘    └──────┬──────┘
                             │                    │
                    ┌────────▼────────────────────▼──┐
                    │    Data & Cache Layer          │
                    │  PostgreSQL + Redis             │
                    └─────────────────────────────────┘
```

---

## 컴포넌트 구조

### 1. Presentation Layer (프레젠테이션 계층)

#### Frontend (Next.js)

**역할**: 사용자 인터페이스

**기술 스택**:
- Next.js 14+ (React 18+)
- TypeScript
- Tailwind CSS
- React Query (TanStack Query)

**배포 구성**:
```yaml
Type: Deployment
Replicas: 2 (dev) / 3 (prod)
Resources:
  CPU: 200m (request) / 500m (limit)
  Memory: 256Mi (request) / 512Mi (limit)
Autoscaling: HPA (70% CPU)
Port: 3000
```

**주요 기능**:
- 대시보드 (통계, 차트)
- 데이터 탐색 UI
- 노트북 관리
- ML 실험 관리
- 워크플로우 모니터링

**통신**:
- Backend API (REST)
- Embedded Services (iframe)

---

#### Backend (FastAPI)

**역할**: 비즈니스 로직 및 API 서버

**기술 스택**:
- FastAPI (Python 3.11+)
- SQLAlchemy (ORM)
- Pydantic (Validation)
- asyncio (비동기 처리)

**배포 구성**:
```yaml
Type: Deployment
Replicas: 2 (dev) / 3 (prod)
Resources:
  CPU: 500m (request) / 1000m (limit)
  Memory: 512Mi (request) / 1Gi (limit)
Autoscaling: HPA (70% CPU)
Port: 8000
```

**주요 기능**:
- RESTful API 제공
- 데이터베이스 CRUD
- 인증/인가
- 외부 서비스 연동 (MLflow, Airflow)
- 비즈니스 로직 처리

**통신**:
- PostgreSQL (데이터 영속성)
- Redis (캐싱, 세션)
- MLflow (실험 추적)
- MinIO (파일 스토리지)

**API 엔드포인트**:
```
/api/health              - Health check
/api/v1/projects         - 프로젝트 관리
/api/v1/datasets         - 데이터셋 관리
/api/v1/notebooks        - 노트북 관리
/api/v1/experiments      - ML 실험 관리
/api/v1/workflows        - 워크플로우 관리
/api/v1/users            - 사용자 관리
```

---

### 2. Service Layer (서비스 계층)

#### JupyterLab

**역할**: 대화형 노트북 개발 환경

**기술 스택**:
- JupyterLab
- Python 3.11+
- scipy-notebook 기반
- 데이터 분석 라이브러리 (pandas, numpy, scikit-learn)

**배포 구성**:
```yaml
Type: Deployment
Replicas: 1
Resources:
  CPU: 1000m (request) / 2000m (limit)
  Memory: 2Gi (request) / 4Gi (limit)
Port: 8888
Persistence: 20Gi (PVC)
```

**주요 기능**:
- Python/R 노트북 실행
- 데이터 탐색
- 모델 개발
- 시각화

**접속**:
- URL: `/jupyter`
- Token: 설정 가능 (기본: `jupyter`)

---

#### MLflow

**역할**: ML 실험 추적 및 모델 관리

**기술 스택**:
- MLflow 2.10+
- PostgreSQL (backend store)
- MinIO (artifact store)

**배포 구성**:
```yaml
Type: Deployment
Replicas: 1
Resources:
  CPU: 500m (request) / 1000m (limit)
  Memory: 1Gi (request) / 2Gi (limit)
Port: 5000
Persistence: 20Gi (PVC)
```

**주요 기능**:
- 실험 추적 (metrics, parameters)
- 모델 버전 관리
- 모델 레지스트리
- Artifact 저장

**접속**:
- URL: `/mlflow`

**데이터 스토리지**:
- **Backend Store**: PostgreSQL (메타데이터)
- **Artifact Store**: MinIO S3 (모델, 로그)

---

#### Airflow

**역할**: 워크플로우 오케스트레이션

**기술 스택**:
- Apache Airflow 2.8+
- PostgreSQL (metadata DB)
- LocalExecutor (dev) / CeleryExecutor (prod)

**배포 구성**:
```yaml
Components:
  - Webserver (UI):
      Replicas: 1 (dev) / 3 (prod)
      CPU: 200m / 500m
      Memory: 512Mi / 1Gi
      Port: 8080
  
  - Scheduler (Task 관리):
      Replicas: 1 (dev) / 2 (prod)
      CPU: 200m / 500m
      Memory: 512Mi / 1Gi
  
  - Workers (Task 실행, prod only):
      Replicas: 0 (dev) / 4 (prod)
      CPU: 1000m / 2000m
      Memory: 2Gi / 4Gi

Persistence:
  - DAGs: 10Gi (PVC)
  - Logs: 10Gi (PVC)
```

**주요 기능**:
- DAG (Directed Acyclic Graph) 정의
- 스케줄링
- 의존성 관리
- 실행 모니터링

**접속**:
- URL: `/airflow`
- 계정: admin / admin (변경 필요)

---

#### Spark

**역할**: 분산 데이터 처리

**기술 스택**:
- Apache Spark 3.5
- Bitnami Spark 이미지

**배포 구성**:
```yaml
Components:
  - Master:
      Type: StatefulSet
      Replicas: 1
      CPU: 1000m / 2000m
      Memory: 2Gi / 4Gi
      Ports:
        - Spark: 7077
        - Web UI: 8080
  
  - Workers:
      Type: StatefulSet
      Replicas: 1 (dev) / 5 (prod)
      CPU: 500m / 1000m (dev) | 4000m / 8000m (prod)
      Memory: 1Gi / 2Gi (dev) | 8Gi / 16Gi (prod)
      Env:
        SPARK_WORKER_CORES: 1 (dev) / 4 (prod)
        SPARK_WORKER_MEMORY: 1G (dev) / 8G (prod)
```

**주요 기능**:
- 대용량 데이터 처리
- 분산 ML 학습
- ETL 작업
- 스트리밍 처리

**접속**:
- URL: `/spark`
- Master: `spark://spark-master:7077`

---

#### MinIO

**역할**: S3 호환 객체 스토리지

**기술 스택**:
- MinIO (S3 API)

**배포 구성**:
```yaml
Type: Deployment
Replicas: 1
Resources:
  CPU: 500m (request) / 1000m (limit)
  Memory: 1Gi (request) / 2Gi (limit)
Ports:
  - API: 9000
  - Console: 9001
Persistence: 100Gi (PVC)
```

**주요 기능**:
- MLflow artifacts 저장
- 파일 업로드/다운로드
- 버킷 관리
- S3 API 호환

**접속**:
- Console: `/minio-console`
- API: `http://minio:9000`

**버킷 구조**:
```
mlflow-artifacts/        # MLflow 실험 결과
  ├── 0/                 # Experiment ID
  │   └── <run-id>/
  │       ├── artifacts/
  │       └── metrics/
  └── models/            # 등록된 모델
```

---

### 3. Data Layer (데이터 계층)

#### PostgreSQL

**역할**: 주 데이터베이스 (OLTP)

**기술 스택**:
- PostgreSQL 16
- Alpine 기반

**배포 구성**:
```yaml
Type: StatefulSet
Replicas: 1 (dev) / 2 (prod, with replication)
Resources:
  CPU: 1000m / 2000m (dev) | 2000m / 4000m (prod)
  Memory: 2Gi / 4Gi (dev) | 4Gi / 8Gi (prod)
Port: 5432
Persistence: 50Gi (dev) / 200Gi (prod)
StorageClass: local-path
```

**데이터베이스 구조**:
```
├── datapond           # 메인 애플리케이션 DB
│   ├── users          # 사용자
│   ├── projects       # 프로젝트
│   ├── datasets       # 데이터셋
│   └── notebooks      # 노트북 메타데이터
├── mlflow             # MLflow 메타데이터
│   ├── experiments
│   ├── runs
│   └── metrics
└── airflow            # Airflow 메타데이터
    ├── dags
    ├── dag_run
    └── task_instance
```

**고가용성** (프로덕션):
- Streaming Replication (1 Primary + 1 Standby)
- Automatic Failover (pg_auto_failover 또는 Patroni)
- WAL Archiving

**백업 전략**:
- Full Backup: 매일
- WAL Archiving: 연속
- Point-in-Time Recovery (PITR) 지원

---

#### Redis

**역할**: 캐싱 및 세션 스토어

**기술 스택**:
- Redis 7
- Alpine 기반

**배포 구성**:
```yaml
Type: Deployment
Replicas: 1 (dev) / 3 (prod, with Sentinel)
Resources:
  CPU: 200m / 500m (dev) | 500m / 1000m (prod)
  Memory: 256Mi / 512Mi (dev) | 512Mi / 1Gi (prod)
Port: 6379
Persistence: 5Gi (dev) / 20Gi (prod)
```

**사용 목적**:
- API 응답 캐싱
- 세션 관리
- Rate limiting
- 임시 데이터 저장
- Celery broker (Airflow, prod)

**고가용성** (프로덕션):
- Redis Sentinel (3 replicas)
- Automatic Failover
- Read Replicas

---

## 네트워킹

### Ingress 라우팅

#### Path-based Routing

```yaml
Ingress: datapond.local

Routes:
  / (Root)                    → frontend:3000
  /api/*                      → backend:8000
  /jupyter/*                  → jupyter:8888
  /mlflow/*                   → mlflow:5000
  /airflow/*                  → airflow:8080
  /spark/*                    → spark-master:8080
  /minio-console/*            → minio:9001
```

#### Ingress 구성

**개발 환경**:
```yaml
IngressClass: traefik (K3s 기본)
TLS: disabled
Annotations:
  - traefik.ingress.kubernetes.io/router.middlewares: strip-prefix
```

**프로덕션**:
```yaml
IngressClass: nginx
TLS: enabled (cert-manager + Let's Encrypt)
Annotations:
  - cert-manager.io/cluster-issuer: letsencrypt-prod
  - nginx.ingress.kubernetes.io/ssl-redirect: "true"
  - nginx.ingress.kubernetes.io/rate-limit: "100"
```

---

### Service Mesh (내부 통신)

#### Service Discovery

모든 서비스는 Kubernetes Service를 통해 발견됩니다:

```
backend.datapond.svc.cluster.local:8000
postgres.datapond.svc.cluster.local:5432
redis.datapond.svc.cluster.local:6379
minio.datapond.svc.cluster.local:9000
mlflow.datapond.svc.cluster.local:5000
spark-master.datapond.svc.cluster.local:7077
```

#### 통신 패턴

```
Frontend → Backend:
  - HTTP/REST API
  - JSON payload
  
Backend → PostgreSQL:
  - PostgreSQL protocol
  - Connection pooling (SQLAlchemy)
  
Backend → Redis:
  - Redis protocol
  - Connection pooling (redis-py)
  
Backend → MLflow:
  - HTTP/REST API
  - MLflow tracking API
  
MLflow → PostgreSQL:
  - Backend store (메타데이터)
  
MLflow → MinIO:
  - S3 API
  - Artifact storage
  
Airflow → PostgreSQL:
  - Metadata store
  
Spark Worker → Spark Master:
  - Spark RPC protocol
```

---

### Network Policies (선택사항)

프로덕션 환경에서 네트워크 격리:

```yaml
# Backend만 PostgreSQL 접근 허용
PostgreSQL:
  Ingress:
    - From: backend
    - From: mlflow
    - From: airflow
  Egress: deny (default)

# Frontend는 Backend만 접근
Frontend:
  Ingress:
    - From: ingress
  Egress:
    - To: backend

# Backend 접근 제어
Backend:
  Ingress:
    - From: frontend
    - From: ingress
  Egress:
    - To: postgres
    - To: redis
    - To: mlflow
    - To: minio
```

---

## 스토리지

### 스토리지 계층

```
┌─────────────────────────────────────────────┐
│         Kubernetes Persistent Volume        │
│              (local-path / NFS)             │
└──────────────────┬──────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
┌───▼────┐  ┌──────▼───┐  ┌──────▼────┐
│ Block  │  │   File   │  │  Object   │
│Storage │  │ Storage  │  │  Storage  │
│(PVC)   │  │  (PVC)   │  │  (MinIO)  │
└────────┘  └──────────┘  └───────────┘
```

### PersistentVolume Claims

| Service | Size (dev) | Size (prod) | Access Mode | 용도 |
|---------|------------|-------------|-------------|------|
| **PostgreSQL** | 20Gi | 200Gi | ReadWriteOnce | 데이터베이스 |
| **Redis** | 2Gi | 20Gi | ReadWriteOnce | 캐시 영속화 |
| **JupyterLab** | 10Gi | 100Gi | ReadWriteOnce | 노트북 저장 |
| **MLflow** | 5Gi | 100Gi | ReadWriteOnce | 메타데이터 |
| **MinIO** | 20Gi | 500Gi | ReadWriteOnce | 객체 스토리지 |
| **Airflow DAGs** | 5Gi | 50Gi | ReadWriteMany | DAG 파일 |
| **Airflow Logs** | 5Gi | 100Gi | ReadWriteMany | 실행 로그 |

**총 스토리지**: ~70Gi (dev) / ~1070Gi (prod)

---

### StorageClass

#### 개발 환경 (K3s)

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-path
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
```

**특징**:
- Local node storage
- Dynamic provisioning
- 빠른 I/O
- 단일 노드 제한

#### 프로덕션 환경

**옵션 1: NFS**
```yaml
provisioner: nfs.csi.k8s.io
reclaimPolicy: Retain
volumeBindingMode: Immediate
```

**옵션 2: Ceph/Rook**
```yaml
provisioner: rook-ceph.rbd.csi.ceph.com
reclaimPolicy: Retain
```

**옵션 3: Cloud Provider**
- AWS: EBS (gp3)
- GCP: Persistent Disk (SSD)
- Azure: Azure Disk (Premium SSD)

---

### 백업 전략

#### PostgreSQL

```bash
# Full Backup (매일 새벽 2시)
pg_dump -h postgres -U datapond datapond > backup.sql

# WAL Archiving (연속)
archive_mode = on
archive_command = 'cp %p /backup/wal/%f'

# PITR (Point-in-Time Recovery)
pg_basebackup + WAL replay
```

#### PVC Snapshots

```yaml
# VolumeSnapshot (Kubernetes)
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: postgres-snapshot-20260428
spec:
  volumeSnapshotClassName: csi-snapclass
  source:
    persistentVolumeClaimName: postgres-pvc
```

#### MinIO

```bash
# mc mirror (MinIO Client)
mc mirror --watch datapond/mlflow-artifacts /backup/minio/
```

---

## 보안

### 1. 인증 및 인가

#### Secrets Management

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: datapond-secrets
type: Opaque
data:
  POSTGRES_PASSWORD: <base64>
  JWT_SECRET: <base64>
  MINIO_ROOT_PASSWORD: <base64>
  JUPYTER_TOKEN: <base64>
```

**보안 원칙**:
- ❌ values.yaml에 평문 비밀번호 저장 금지
- ✅ Kubernetes Secrets 사용
- ✅ 프로덕션: 외부 secret store (Vault, AWS Secrets Manager)
- ✅ Sealed Secrets (GitOps 시)

---

#### RBAC (Role-Based Access Control)

```yaml
# ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: datapond-backend
  namespace: datapond

---
# Role
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: datapond-app-role
  namespace: datapond
rules:
- apiGroups: [""]
  resources: ["pods", "services"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]

---
# RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: datapond-app-binding
  namespace: datapond
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: datapond-app-role
subjects:
- kind: ServiceAccount
  name: datapond-backend
  namespace: datapond
```

---

### 2. Network Security

#### TLS/SSL

**Ingress TLS** (프로덕션):
```yaml
spec:
  tls:
  - hosts:
    - datapond.yourdomain.com
    secretName: datapond-tls
```

**cert-manager** (Let's Encrypt):
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: datapond-cert
spec:
  secretName: datapond-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - datapond.yourdomain.com
```

---

#### Network Policies

```yaml
# PostgreSQL 접근 제한
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-network-policy
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: backend
    - podSelector:
        matchLabels:
          app: mlflow
    - podSelector:
        matchLabels:
          app: airflow
    ports:
    - protocol: TCP
      port: 5432
```

---

### 3. Pod Security

#### Security Context

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000
  capabilities:
    drop:
    - ALL
  readOnlyRootFilesystem: true
```

#### Resource Limits

```yaml
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi
    ephemeral-storage: 1Gi
```

---

### 4. 이미지 보안

```yaml
# 신뢰할 수 있는 레지스트리만 사용
image: docker.io/postgres:16-alpine

# 취약점 스캔 (Trivy)
$ trivy image postgres:16-alpine

# 이미지 서명 확인 (Notary/Cosign)
$ cosign verify <image>
```

---

## 확장성

### 1. Horizontal Scaling

#### HPA (Horizontal Pod Autoscaler)

**Frontend**:
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: frontend-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: frontend
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

**Backend**:
```yaml
minReplicas: 2
maxReplicas: 20
targetCPUUtilizationPercentage: 70
```

**스케일링 동작**:
```
트래픽 증가 → CPU 사용률 > 70% → Pod 증가
트래픽 감소 → CPU 사용률 < 70% → Pod 감소 (5분 쿨다운)
```

---

#### Cluster Autoscaler

멀티 노드 환경에서 노드 자동 증감:

```yaml
# AWS EKS
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-autoscaler
data:
  min-nodes: "3"
  max-nodes: "10"
  scale-down-delay: "10m"
```

---

### 2. Vertical Scaling

#### VPA (Vertical Pod Autoscaler)

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: backend-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backend
  updatePolicy:
    updateMode: "Auto"  # 또는 "Recreate"
```

---

### 3. 데이터베이스 스케일링

#### PostgreSQL

**Read Replicas**:
```
Primary (Write) → Replica 1 (Read)
               → Replica 2 (Read)
               → Replica 3 (Read)
```

**Connection Pooling**:
```yaml
# PgBouncer
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pgbouncer
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: pgbouncer
        image: pgbouncer/pgbouncer
        env:
        - name: MAX_CLIENT_CONN
          value: "1000"
        - name: DEFAULT_POOL_SIZE
          value: "25"
```

#### Redis

**Redis Cluster** (프로덕션):
```
Master 1 → Replica 1
Master 2 → Replica 2
Master 3 → Replica 3
```

---

### 4. 스토리지 스케일링

**PVC 확장**:
```bash
# PVC 크기 증가
kubectl patch pvc postgres-pvc -p '{"spec":{"resources":{"requests":{"storage":"100Gi"}}}}'

# StatefulSet 재시작
kubectl rollout restart statefulset postgres
```

---

## 고가용성

### 1. 복제본 전략

| Component | Dev | Prod | Strategy |
|-----------|-----|------|----------|
| Frontend | 1-2 | 3-5 | Active-Active |
| Backend | 1-2 | 3-10 | Active-Active |
| PostgreSQL | 1 | 2-3 | Primary-Standby |
| Redis | 1 | 3 | Sentinel |
| Airflow Web | 1 | 3 | Active-Active |
| Airflow Scheduler | 1 | 2 | Active-Standby |
| Spark Master | 1 | 1 | Single (HA via checkpoint) |
| Spark Workers | 1 | 5+ | Active-Active |

---

### 2. 헬스 체크

```yaml
# Liveness Probe (컨테이너 생존 확인)
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

# Readiness Probe (트래픽 수신 준비 확인)
readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
  failureThreshold: 3
```

**동작**:
- Liveness 실패 → Pod 재시작
- Readiness 실패 → Service에서 제거 (트래픽 차단)

---

### 3. 롤링 업데이트

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 1      # 최대 1개 Pod까지 unavailable
    maxSurge: 1            # 최대 1개 추가 Pod 생성 가능
```

**업데이트 프로세스**:
```
1. 새 Pod 1개 생성
2. 새 Pod Ready 확인
3. 기존 Pod 1개 종료
4. 반복 (모든 Pod 교체)
```

**제로 다운타임 보장**.

---

### 4. Pod Disruption Budget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: backend-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: backend
```

**효과**:
- 노드 드레인 시 최소 2개 Pod 유지
- 자발적 중단 제어

---

### 5. 멀티 AZ/Region (프로덕션)

```yaml
# Node Affinity (다른 AZ에 배포)
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchExpressions:
        - key: app
          operator: In
          values:
          - backend
      topologyKey: topology.kubernetes.io/zone
```

---

## 데이터 흐름

### 1. 사용자 요청 흐름

```
User Browser
    │
    ▼
Ingress (datapond.local)
    │
    ├─────▶ Frontend (/) ───────────────┐
    │                                   │
    └─────▶ Backend (/api) ────────┐   │
                │                   │   │
                ├─▶ PostgreSQL      │   │
                │   (데이터 조회)    │   │
                │                   │   │
                ├─▶ Redis           │   │
                │   (캐시 확인)      │   │
                │                   │   │
                └─▶ Response ◀──────┴───┘
```

---

### 2. ML 실험 흐름

```
JupyterLab
    │ (모델 학습)
    ▼
MLflow Tracking API
    │
    ├─▶ PostgreSQL (메타데이터 저장)
    │   - Experiment name
    │   - Run ID
    │   - Parameters
    │   - Metrics
    │
    └─▶ MinIO (artifacts 저장)
        - Model files
        - Plots
        - Logs
```

---

### 3. Airflow 워크플로우

```
Airflow Webserver (사용자)
    │ (DAG 정의/트리거)
    ▼
Airflow Scheduler
    │ (작업 스케줄링)
    ▼
Airflow Workers (LocalExecutor/CeleryExecutor)
    │
    ├─▶ Spark Job 실행
    │   (데이터 처리)
    │
    ├─▶ PostgreSQL
    │   (메타데이터 저장)
    │
    └─▶ Backend API 호출
        (결과 알림)
```

---

### 4. Spark 작업 흐름

```
Client (Jupyter/Airflow)
    │ (spark-submit)
    ▼
Spark Master
    │ (작업 분배)
    ├─▶ Worker 1 (Task 실행)
    ├─▶ Worker 2 (Task 실행)
    └─▶ Worker N (Task 실행)
        │
        ▼
    Result Aggregation
        │
        ▼
    MinIO (결과 저장)
```

---

## 기술 스택

### Infrastructure

| 계층 | 기술 | 버전 |
|------|------|------|
| **Container Runtime** | Containerd | 1.7+ |
| **Orchestration** | Kubernetes | 1.25+ |
| **K8s Distribution** | K3s | 1.28+ |
| **Package Manager** | Helm | 3.12+ |
| **Ingress** | Traefik / Nginx | 2.10+ / 1.8+ |
| **Storage** | local-path / NFS | - |
| **Monitoring** | Prometheus + Grafana | 2.45+ / 10.0+ |

---

### Application Stack

| 서비스 | 기술 | 버전 |
|--------|------|------|
| **Frontend** | Next.js | 14+ |
| **Backend** | FastAPI | 0.104+ |
| **Database** | PostgreSQL | 16 |
| **Cache** | Redis | 7 |
| **Notebook** | JupyterLab | latest |
| **ML Tracking** | MLflow | 2.10+ |
| **Object Storage** | MinIO | latest |
| **Workflow** | Apache Airflow | 2.8+ |
| **Processing** | Apache Spark | 3.5 |

---

### Development Stack

| 영역 | 기술 |
|------|------|
| **Language** | Python 3.11+, TypeScript |
| **ORM** | SQLAlchemy |
| **Validation** | Pydantic |
| **API Docs** | OpenAPI (Swagger) |
| **Testing** | pytest, Jest |
| **Linting** | Black, ESLint |
| **Type Check** | mypy, TypeScript |

---

## 확장 로드맵

### Phase 1: 단일 노드 (현재)

```
[ K3s Node ]
  - 모든 서비스 실행
  - Local storage
  - 개발/테스트 환경
```

**목표**: 빠른 개발, 프로토타입

---

### Phase 2: 3-노드 클러스터 (3-6개월)

```
[ Master Node ]          [ Worker 1 ]        [ Worker 2 ]
  - Control Plane          - Apps              - Apps
  - etcd                   - Data Services     - Data Services
  - Light workloads
```

**목표**: 고가용성, 운영 환경

---

### Phase 3: 관리형 Kubernetes (6-12개월)

```
Cloud Provider (AWS EKS / GKE / AKS)
  - 멀티 AZ
  - 관리형 Control Plane
  - Auto-scaling
  - Managed Add-ons
```

**목표**: 엔터프라이즈, 글로벌 서비스

---

### Phase 4: 멀티 클러스터 (12+ 개월)

```
[ Region 1 - Prod ]    [ Region 2 - DR ]    [ Dev Cluster ]
      ▲                       ▲                     │
      └───── Cluster Mesh ────┘                     │
                  │                                  │
            [ Service Mesh (Istio) ]                │
                  │                                  │
            [ GitOps (ArgoCD) ] ◀──────────────────┘
```

**목표**: 글로벌 HA, DR, 멀티 리전

---

## 참고 자료

### Kubernetes 공식 문서
- [Kubernetes Docs](https://kubernetes.io/docs/)
- [Helm Docs](https://helm.sh/docs/)

### 프로젝트 문서
- [README.md](../README.md)
- [QUICKSTART.md](../QUICKSTART.md)
- [INSTALLATION.md](INSTALLATION.md)
- [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

**문서 버전**: 1.0  
**최종 수정**: 2026-04-28  
**작성자**: DataPond Team
