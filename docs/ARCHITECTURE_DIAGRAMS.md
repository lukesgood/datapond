# DataPond Kubernetes 아키텍처 다이어그램

**상세 시각화 문서**

---

## 📊 전체 시스템 아키텍처

```
                        ┌─────────────────────────────────────┐
                        │         External Users              │
                        │    (Browser, API Clients)           │
                        └──────────────┬──────────────────────┘
                                       │ HTTPS/HTTP
                                       │
                        ┌──────────────▼──────────────────────┐
                        │      Kubernetes Cluster             │
                        │                                     │
    ┌───────────────────┼─────────────────────────────────────┼───────────────────┐
    │                   │    Ingress Controller               │                   │
    │                   │   (Traefik/Nginx)                   │                   │
    │                   │   datapond.local                    │                   │
    │                   └──────────────┬──────────────────────┘                   │
    │                                  │                                          │
    │   ┌──────────────────────────────┼──────────────────────────────┐          │
    │   │                              │                              │          │
    │   │  ┌───────────────────────────▼─────────┐  ┌─────────────────▼─────┐   │
    │   │  │     Application Layer                │  │   Service Layer       │   │
    │   │  │                                       │  │                       │   │
    │   │  │  ┌──────────┐    ┌──────────┐       │  │  ┌─────────────┐     │   │
    │   │  │  │Frontend  │    │ Backend  │       │  │  │ JupyterLab  │     │   │
    │   │  │  │(Next.js) │───▶│(FastAPI) │───────┼──┼─▶│             │     │   │
    │   │  │  │          │    │          │       │  │  └─────────────┘     │   │
    │   │  │  │Port:3000 │    │Port:8000 │       │  │                       │   │
    │   │  │  └──────────┘    └────┬─────┘       │  │  ┌─────────────┐     │   │
    │   │  │                       │              │  │  │   MLflow    │     │   │
    │   │  │                       │              │  │  │             │     │   │
    │   │  │                       │              │  │  └──────┬──────┘     │   │
    │   │  └───────────────────────┼──────────────┘  │         │            │   │
    │   │                          │                 │  ┌──────▼──────┐     │   │
    │   │                          │                 │  │   SeaweedFS     │     │   │
    │   │                          │                 │  │  (S3 API)   │     │   │
    │   │                          │                 │  └─────────────┘     │   │
    │   │                          │                 │                       │   │
    │   │                          │                 │  ┌─────────────┐     │   │
    │   │                          │                 │  │  Airflow    │     │   │
    │   │                          │                 │  │ Web+Sched   │     │   │
    │   │                          │                 │  └─────────────┘     │   │
    │   │                          │                 │                       │   │
    │   │                          │                 │  ┌─────────────┐     │   │
    │   │                          │                 │  │   Spark     │     │   │
    │   │                          │                 │  │ Master+Work │     │   │
    │   │                          │                 │  └─────────────┘     │   │
    │   │                          │                 └───────────────────────┘   │
    │   │                          │                                             │
    │   │  ┌───────────────────────▼─────────────────────────────┐              │
    │   │  │              Data Layer                              │              │
    │   │  │                                                      │              │
    │   │  │  ┌─────────────────┐      ┌──────────────┐         │              │
    │   │  │  │   PostgreSQL    │      │    Redis     │         │              │
    │   │  │  │   (Primary)     │      │   (Cache)    │         │              │
    │   │  │  │                 │      │              │         │              │
    │   │  │  │   Port: 5432    │      │  Port: 6379  │         │              │
    │   │  │  └────────┬────────┘      └──────┬───────┘         │              │
    │   │  └───────────┼────────────────────────┼────────────────┘              │
    │   │              │                        │                                │
    │   │  ┌───────────▼────────────────────────▼────────────────┐              │
    │   │  │              Storage Layer (PVC)                     │              │
    │   │  │                                                      │              │
    │   │  │  ┏━━━━━━━━━┓  ┏━━━━━━━━┓  ┏━━━━━━━━┓  ┏━━━━━━━━┓  │              │
    │   │  │  ┃Postgres ┃  ┃ SeaweedFS  ┃  ┃Jupyter ┃  ┃Airflow ┃  │              │
    │   │  │  ┃   PVC   ┃  ┃  PVC   ┃  ┃  PVC   ┃  ┃  PVC   ┃  │              │
    │   │  │  ┃  50Gi   ┃  ┃ 100Gi  ┃  ┃  20Gi  ┃  ┃  20Gi  ┃  │              │
    │   │  │  ┗━━━━━━━━━┛  ┗━━━━━━━━┛  ┗━━━━━━━━┛  ┗━━━━━━━━┛  │              │
    │   │  └──────────────────────────────────────────────────────┘              │
    │   └──────────────────────────────────────────────────────────────────────┘
    └──────────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 데이터 흐름 다이어그램

### 1. 사용자 요청 처리

```
┌────────┐
│ User   │
│Browser │
└───┬────┘
    │ HTTP GET /
    ▼
┌───────────────┐
│   Ingress     │
│datapond.local │
└───┬───────────┘
    │
    ├─── Path: / ────────────────┐
    │                             ▼
    │                      ┌──────────────┐
    │                      │  Frontend    │
    │                      │  (Next.js)   │
    │                      └──────┬───────┘
    │                             │
    │                             │ API call: /api/projects
    │                             ▼
    ├─── Path: /api ───────▶┌──────────────┐
    │                        │   Backend    │
    │                        │  (FastAPI)   │
    │                        └──────┬───────┘
    │                               │
    │                         ┌─────┴──────┐
    │                         │            │
    │                    ┌────▼────┐  ┌───▼────┐
    │                    │Postgres │  │ Redis  │
    │                    │  Query  │  │ Cache  │
    │                    └────┬────┘  └───┬────┘
    │                         │           │
    │                         └─────┬─────┘
    │                               │
    │                         ┌─────▼──────┐
    │                         │  Response  │
    │                         │   (JSON)   │
    │                         └─────┬──────┘
    │                               │
    │                               ▼
    └───────────────────────────── User
```

---

### 2. ML 실험 라이프사이클

```
┌─────────────────────────────────────────────────────────────────┐
│                    ML Experiment Flow                           │
└─────────────────────────────────────────────────────────────────┘

Step 1: 데이터 준비
┌───────────┐
│ JupyterLab│
│  (User)   │
└─────┬─────┘
      │ Load data
      ▼
┌─────────────┐
│ PostgreSQL  │
│   (Data)    │
└─────┬───────┘
      │
      ▼
Step 2: 모델 학습
┌───────────┐
│ Jupyter   │
│ + MLflow  │
│  Client   │
└─────┬─────┘
      │ mlflow.log_param()
      │ mlflow.log_metric()
      ▼
┌─────────────┐
│   MLflow    │
│  Tracking   │
│   Server    │
└─────┬───────┘
      │
      ├────────────────────┐
      │                    │
      ▼                    ▼
┌─────────────┐      ┌──────────────┐
│ PostgreSQL  │      │    SeaweedFS     │
│ (Metadata)  │      │ (Artifacts)  │
│             │      │              │
│ - Exp name  │      │ - model.pkl  │
│ - Run ID    │      │ - plots/     │
│ - Params    │      │ - logs/      │
│ - Metrics   │      │ - data/      │
└─────────────┘      └──────────────┘

Step 3: 모델 배포
┌───────────┐
│  MLflow   │
│  Model    │
│ Registry  │
└─────┬─────┘
      │ Register model
      ▼
┌──────────────┐
│ Production   │
│   Model      │
│ (Versioned)  │
└──────────────┘
```

---

### 3. Airflow 워크플로우 실행

```
┌─────────────────────────────────────────────────────────────────┐
│                  Airflow Workflow Execution                     │
└─────────────────────────────────────────────────────────────────┘

┌──────────────┐
│   DAG File   │
│  (Python)    │
└──────┬───────┘
       │ Upload to /dags
       ▼
┌──────────────┐
│  Airflow     │
│  Webserver   │ ◀─── User (Trigger DAG)
└──────┬───────┘
       │ Create DagRun
       ▼
┌──────────────┐
│  Airflow     │
│  Scheduler   │
└──────┬───────┘
       │ Schedule tasks
       ▼
┌──────────────────────────────────────┐
│         Task Execution               │
│                                      │
│  ┌──────────┐     ┌──────────┐     │
│  │  Task 1  │────▶│  Task 2  │     │
│  │ (Worker) │     │ (Worker) │     │
│  └────┬─────┘     └────┬─────┘     │
│       │                │            │
│       │  Execute:      │            │
│       │  - SQL query   │            │
│       │  - Spark job   │            │
│       │  - API call    │            │
│       │                │            │
│       └────────┬───────┘            │
│                │                    │
└────────────────┼────────────────────┘
                 │
       ┌─────────┴──────────┐
       │                    │
       ▼                    ▼
┌──────────────┐    ┌──────────────┐
│  PostgreSQL  │    │    Spark     │
│   (Store)    │    │  Cluster     │
└──────────────┘    └──────────────┘
       │
       │ Save result
       ▼
┌──────────────┐
│   SeaweedFS      │
│  (Output)    │
└──────────────┘
```

---

### 4. Spark 분산 처리

```
┌─────────────────────────────────────────────────────────────────┐
│              Spark Distributed Processing                       │
└─────────────────────────────────────────────────────────────────┘

┌──────────────┐
│   Client     │
│ (Jupyter or  │
│  Airflow)    │
└──────┬───────┘
       │ spark-submit
       ▼
┌──────────────────────────────────────────┐
│         Spark Master                     │
│         (Resource Manager)               │
└──────┬───────────────────────────────────┘
       │
       │ Distribute tasks
       │
       ├─────────────┬─────────────┬─────────────┐
       │             │             │             │
       ▼             ▼             ▼             ▼
┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐
│  Worker 1 │ │  Worker 2 │ │  Worker 3 │ │  Worker N │
│           │ │           │ │           │ │           │
│ Executor  │ │ Executor  │ │ Executor  │ │ Executor  │
│ ┌───────┐ │ │ ┌───────┐ │ │ ┌───────┐ │ │ ┌───────┐ │
│ │Task 1 │ │ │ │Task 2 │ │ │ │Task 3 │ │ │ │Task N │ │
│ └───┬───┘ │ │ └───┬───┘ │ │ └───┬───┘ │ │ └───┬───┘ │
└─────┼─────┘ └─────┼─────┘ └─────┼─────┘ └─────┼─────┘
      │             │             │             │
      │             │             │             │
      └─────────────┴─────────────┴─────────────┘
                    │
                    │ Shuffle & Aggregate
                    ▼
            ┌──────────────┐
            │    Result    │
            │  Aggregation │
            └──────┬───────┘
                   │
                   ▼
            ┌──────────────┐
            │    SeaweedFS     │
            │   (Output)   │
            └──────────────┘
```

---

## 🌐 네트워크 토폴로지

### Ingress 라우팅

```
                    Internet
                       │
                       ▼
            ┌──────────────────┐
            │  Load Balancer   │
            │  (External IP)   │
            └────────┬─────────┘
                     │
                     ▼
            ┌────────────────────────┐
            │  Ingress Controller    │
            │  (Traefik/Nginx)       │
            └────────┬───────────────┘
                     │
     ┌───────────────┼───────────────┬─────────────┐
     │               │               │             │
     │ /             │ /api          │ /jupyter    │ /mlflow
     │               │               │             │
     ▼               ▼               ▼             ▼
┌─────────┐    ┌─────────┐    ┌──────────┐  ┌──────────┐
│Frontend │    │Backend  │    │ Jupyter  │  │  MLflow  │
│Service  │    │Service  │    │ Service  │  │ Service  │
│:3000    │    │:8000    │    │ :8888    │  │ :5000    │
└─────────┘    └─────────┘    └──────────┘  └──────────┘
     │               │               │             │
     └───────────────┴───────────────┴─────────────┘
                     │
             Internal Network
           (ClusterIP Services)
```

---

### Service 간 통신

```
┌────────────────────────────────────────────────────────────┐
│               Kubernetes Service Network                   │
│              (ClusterIP: 10.43.0.0/16)                     │
└────────────────────────────────────────────────────────────┘

Frontend Pod (10.42.0.10)
    │
    │ HTTP: http://backend.datapond.svc.cluster.local:8000
    ▼
Backend Pod (10.42.0.20)
    │
    ├─── PostgreSQL: postgres.datapond.svc.cluster.local:5432
    │    (Connection Pool: 20 connections)
    │
    ├─── Redis: redis.datapond.svc.cluster.local:6379
    │    (Connection Pool: 10 connections)
    │
    ├─── MLflow: mlflow.datapond.svc.cluster.local:5000
    │    (HTTP REST API)
    │
    └─── SeaweedFS: seaweedfs.datapond.svc.cluster.local:9000
         (S3 API)

MLflow Pod (10.42.0.30)
    │
    ├─── PostgreSQL: postgres.datapond.svc.cluster.local:5432
    │    (Backend store)
    │
    └─── SeaweedFS: seaweedfs.datapond.svc.cluster.local:9000
         (Artifact store)

Airflow Pods
    │
    ├─── PostgreSQL: postgres.datapond.svc.cluster.local:5432
    │    (Metadata DB)
    │
    └─── Spark: spark://spark-master.datapond.svc.cluster.local:7077
         (Job submission)
```

---

## 💾 스토리지 아키텍처

```
┌────────────────────────────────────────────────────────────┐
│           Storage Architecture (Layered View)              │
└────────────────────────────────────────────────────────────┘

Application Layer
┌─────────────┬─────────────┬─────────────┬─────────────┐
│  PostgreSQL │  JupyterLab │   SeaweedFS     │   Airflow   │
│    Pod      │    Pod      │    Pod      │    Pods     │
└──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┘
       │             │             │             │
       │ Mount       │ Mount       │ Mount       │ Mount
       ▼             ▼             ▼             ▼
┌──────────────────────────────────────────────────────────┐
│              PersistentVolumeClaim (PVC)                 │
│                                                          │
│  ┏━━━━━━━━━┓  ┏━━━━━━━━┓  ┏━━━━━━━━┓  ┏━━━━━━━━━┓     │
│  ┃Postgres ┃  ┃Jupyter ┃  ┃ SeaweedFS  ┃  ┃ Airflow ┃     │
│  ┃   PVC   ┃  ┃  PVC   ┃  ┃  PVC   ┃  ┃ DAG PVC ┃     │
│  ┃ 50Gi    ┃  ┃ 20Gi   ┃  ┃ 100Gi  ┃  ┃ 10Gi    ┃     │
│  ┗━━━┬━━━━━┛  ┗━━━┬━━━━┛  ┗━━━┬━━━━┛  ┗━━━┬━━━━━┛     │
└──────┼────────────┼────────────┼────────────┼──────────┘
       │            │            │            │
       │ Bind       │ Bind       │ Bind       │ Bind
       ▼            ▼            ▼            ▼
┌──────────────────────────────────────────────────────────┐
│             PersistentVolume (PV)                        │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐│
│  │   PV-1   │  │   PV-2   │  │   PV-3   │  │   PV-4   ││
│  │  50Gi    │  │  20Gi    │  │  100Gi   │  │  10Gi    ││
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘│
└───────┼─────────────┼─────────────┼─────────────┼──────┘
        │             │             │             │
        │             │             │             │
        ▼             ▼             ▼             ▼
┌──────────────────────────────────────────────────────────┐
│              StorageClass Provisioner                    │
│           (local-path / NFS / Ceph)                      │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│            Physical Storage                              │
│                                                          │
│  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐ │
│  │  Local Disk   │  │   NFS Share   │  │  Cloud EBS  │ │
│  │  /var/lib/... │  │  nfs-server   │  │  AWS/GCP    │ │
│  └───────────────┘  └───────────────┘  └─────────────┘ │
└──────────────────────────────────────────────────────────┘
```

---

### 백업 구조

```
┌────────────────────────────────────────────────────────────┐
│                  Backup Architecture                       │
└────────────────────────────────────────────────────────────┘

Production Data
┌─────────────┬─────────────┬─────────────┐
│ PostgreSQL  │   SeaweedFS     │    PVCs     │
│   (OLTP)    │ (Artifacts) │  (Files)    │
└──────┬──────┴──────┬──────┴──────┬──────┘
       │             │             │
       │             │             │
       ▼             ▼             ▼
┌──────────────────────────────────────────┐
│         Backup Methods                   │
│                                          │
│  PostgreSQL:                             │
│    - pg_dump (Full Backup)               │
│    - WAL archiving (Incremental)         │
│    - PITR (Point-in-Time Recovery)       │
│                                          │
│  SeaweedFS:                                  │
│    - mc mirror (Sync)                    │
│    - Bucket versioning                   │
│                                          │
│  PVCs:                                   │
│    - VolumeSnapshot (CSI)                │
│    - Velero (Cluster backup)             │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│       Backup Storage                     │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │  Local:  /backup/datapond/         │ │
│  │    ├── postgres/                   │ │
│  │    ├── seaweedfs/                      │ │
│  │    └── snapshots/                  │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │  Remote: S3/GCS/Azure Blob         │ │
│  │    - Encrypted                     │ │
│  │    - Versioned                     │ │
│  │    - Lifecycle policies            │ │
│  └────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

---

## 🔄 스케일링 전략

### Horizontal Pod Autoscaling (HPA)

```
┌────────────────────────────────────────────────────────────┐
│              HPA (Horizontal Pod Autoscaler)               │
└────────────────────────────────────────────────────────────┘

Metrics Server
      │
      │ CPU/Memory metrics
      ▼
┌──────────────┐
│  HPA         │
│  Controller  │
└──────┬───────┘
       │
       │ Target: CPU > 70%
       │
       ▼
┌────────────────────────────────────────┐
│     Deployment: Backend                │
│                                        │
│  Current state: 2 pods                 │
│  CPU usage: 80% (above threshold)      │
└────────┬───────────────────────────────┘
         │
         │ Scale up decision
         ▼
┌────────────────────────────────────────┐
│     Deployment: Backend                │
│                                        │
│  Desired state: 4 pods                 │
│                                        │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
│  │Pod 1 │ │Pod 2 │ │Pod 3 │ │Pod 4 │ │
│  └──────┘ └──────┘ └──────┘ └──────┘ │
│  (existing)(existing) (new)   (new)   │
└────────────────────────────────────────┘

Time series:
  t=0:   2 pods, CPU 80%
  t=30s: 3 pods, CPU 65% (scaling)
  t=60s: 4 pods, CPU 50% (stable)
  t=5m:  Traffic drops, CPU 40%
  t=10m: Scale down to 3 pods
```

---

### Database Scaling

```
┌────────────────────────────────────────────────────────────┐
│           PostgreSQL Scaling Strategy                      │
└────────────────────────────────────────────────────────────┘

Phase 1: Single Node (Current)
┌──────────────┐
│  PostgreSQL  │
│   Primary    │
│ (Read+Write) │
└──────────────┘

Phase 2: Primary + Read Replicas
┌──────────────┐
│  PostgreSQL  │
│   Primary    │
│   (Write)    │
└──────┬───────┘
       │ Streaming Replication
       │
       ├──────────────┬──────────────┐
       │              │              │
       ▼              ▼              ▼
┌──────────┐    ┌──────────┐  ┌──────────┐
│ Replica1 │    │ Replica2 │  │ Replica3 │
│  (Read)  │    │  (Read)  │  │  (Read)  │
└──────────┘    └──────────┘  └──────────┘

Application connects via:
  - Write: primary.postgres.svc:5432
  - Read:  replicas.postgres.svc:5432 (load balanced)

Phase 3: Sharding (Future)
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Shard 1    │  │   Shard 2    │  │   Shard 3    │
│ (Users 1-1M) │  │(Users 1M-2M) │  │(Users 2M-3M) │
└──────────────┘  └──────────────┘  └──────────────┘
        │                │                │
        └────────────────┴────────────────┘
                         │
                ┌────────▼────────┐
                │  Citus / Vitess │
                │  (Coordinator)  │
                └─────────────────┘
```

---

## 🔒 보안 아키텍처

```
┌────────────────────────────────────────────────────────────┐
│                 Security Layers                            │
└────────────────────────────────────────────────────────────┘

Layer 1: Network Security
┌──────────────────────────────────────┐
│  Internet                            │
│    │                                 │
│    ▼                                 │
│  Firewall/WAF                        │
│    │                                 │
│    ▼                                 │
│  TLS Termination (Ingress)           │
│    │ HTTPS only                      │
└────┼──────────────────────────────────┘
     │
Layer 2: Authentication
┌────▼──────────────────────────────────┐
│  Ingress                              │
│    │                                  │
│    ├─── Basic Auth (optional)         │
│    ├─── OAuth2/OIDC (future)          │
│    └─── API Keys                      │
└────┼──────────────────────────────────┘
     │
Layer 3: Authorization
┌────▼──────────────────────────────────┐
│  Backend (FastAPI)                    │
│    │                                  │
│    ├─── JWT validation                │
│    ├─── Role-based access (RBAC)      │
│    └─── Resource-level permissions    │
└────┼──────────────────────────────────┘
     │
Layer 4: Kubernetes RBAC
┌────▼──────────────────────────────────┐
│  Service Account                      │
│    │                                  │
│    ├─── Role bindings                 │
│    ├─── Resource quotas               │
│    └─── Network policies              │
└────┼──────────────────────────────────┘
     │
Layer 5: Data Encryption
┌────▼──────────────────────────────────┐
│  ┌────────────┐  ┌────────────┐      │
│  │PostgreSQL  │  │   SeaweedFS    │      │
│  │            │  │            │      │
│  │Encrypted at│  │Encrypted at│      │
│  │  rest      │  │  rest      │      │
│  └────────────┘  └────────────┘      │
└───────────────────────────────────────┘
```

---

## 📈 모니터링 아키텍처

```
┌────────────────────────────────────────────────────────────┐
│            Observability Stack (Optional)                  │
└────────────────────────────────────────────────────────────┘

                    Application Pods
┌─────────┬─────────┬─────────┬─────────┬─────────┐
│Frontend │ Backend │Postgres │  Redis  │  etc    │
└────┬────┴────┬────┴────┬────┴────┬────┴────┬────┘
     │         │         │         │         │
     │ Metrics │ Metrics │ Metrics │ Metrics │
     │ (HTTP)  │ (HTTP)  │ (HTTP)  │ (HTTP)  │
     └────┬────┴────┬────┴────┬────┴────┬────┘
          │         │         │         │
          └─────────┴────┬────┴─────────┘
                         │
                         │ Scrape (pull)
                         ▼
                  ┌─────────────┐
                  │ Prometheus  │
                  │  (Metrics)  │
                  └──────┬──────┘
                         │
                         │ Query
                         ▼
                  ┌─────────────┐
                  │   Grafana   │
                  │(Dashboards) │
                  └──────┬──────┘
                         │
                         │ View
                         ▼
                  ┌─────────────┐
                  │    Admin    │
                  │   (User)    │
                  └─────────────┘

Metrics collected:
  - Request rate (req/s)
  - Response time (p50, p95, p99)
  - Error rate (%)
  - CPU/Memory usage
  - Database connections
  - Cache hit rate
```

---

**문서 버전**: 1.0  
**최종 수정**: 2026-04-28
