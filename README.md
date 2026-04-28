# DataPond Kubernetes Edition

**완전히 재설계된 Kubernetes 기반 DataPond 플랫폼**

---

## 🎯 개요

DataPond를 Kubernetes 네이티브 아키텍처로 완전히 재구성한 버전입니다.

### **주요 개선사항**

- ✅ Kubernetes 네이티브 설계
- ✅ Helm Chart 기반 배포
- ✅ 자동 스케일링 (HPA)
- ✅ 고가용성 구성
- ✅ GitOps 준비 완료
- ✅ 프로메테우스 모니터링
- ✅ Ingress 기반 통합 라우팅
- ✅ 영구 스토리지 (PV/PVC)

---

## 📁 디렉토리 구조

```
datapond-k8s/
├── helm/                           # Helm Chart (권장)
│   └── datapond/
│       ├── Chart.yaml             # Chart 메타데이터
│       ├── values.yaml            # 기본 설정값
│       ├── values-dev.yaml        # 개발 환경
│       ├── values-prod.yaml       # 프로덕션 환경
│       └── templates/             # K8s 리소스 템플릿
│           ├── namespace.yaml
│           ├── configmap.yaml
│           ├── secrets.yaml
│           ├── backend/
│           ├── frontend/
│           ├── postgres/
│           ├── redis/
│           ├── jupyter/
│           ├── mlflow/
│           ├── airflow/
│           ├── spark/
│           └── ingress.yaml
│
├── k8s/                           # Raw Kubernetes Manifests
│   ├── namespace.yaml
│   ├── configmaps/
│   ├── secrets/
│   ├── deployments/
│   ├── services/
│   ├── statefulsets/
│   ├── ingress/
│   └── persistent-volumes/
│
├── docker/                        # 최적화된 Dockerfile
│   ├── backend/
│   ├── frontend/
│   └── services/
│
├── monitoring/                    # 모니터링 스택
│   ├── prometheus/
│   └── grafana/
│
├── scripts/                       # 자동화 스크립트
│   ├── install-k3s.sh
│   ├── deploy.sh
│   ├── update.sh
│   ├── backup.sh
│   └── rollback.sh
│
└── docs/                         # 문서
    ├── INSTALLATION.md
    ├── CONFIGURATION.md
    ├── OPERATIONS.md
    └── TROUBLESHOOTING.md
```

---

## 🚀 빠른 시작

### **1. K3s 설치**

```bash
cd /home/luke/datapond-k8s
sudo bash scripts/install-k3s.sh
```

### **2. DataPond 배포 (Helm)**

```bash
# Namespace 생성
kubectl create namespace datapond

# Helm으로 배포
helm install datapond ./helm/datapond \
  --namespace datapond \
  --values helm/datapond/values-dev.yaml

# 또는 프로덕션
helm install datapond ./helm/datapond \
  --namespace datapond \
  --values helm/datapond/values-prod.yaml
```

### **3. 배포 확인**

```bash
# Pod 상태 확인
kubectl get pods -n datapond

# 서비스 확인
kubectl get svc -n datapond

# Ingress 확인
kubectl get ingress -n datapond
```

### **4. 접속**

```bash
# 로컬 접속 (K3s)
http://datapond.local

# 또는 NodePort로 직접 접속
http://<node-ip>:30000
```

---

## 📊 아키텍처

### **서비스 구성**

```
┌─────────────────────────────────────────────────┐
│              Ingress Controller                  │
│         (Traefik or Nginx Ingress)              │
└─────────────────┬───────────────────────────────┘
                  │
    ┌─────────────┼─────────────┬─────────────┐
    │             │             │             │
┌───▼───┐   ┌────▼────┐   ┌───▼───┐   ┌────▼────┐
│Frontend│   │ Backend │   │Jupyter│   │ MLflow  │
│(Next.js)   │(FastAPI)│   │  Lab  │   │         │
└───────┘   └────┬────┘   └───────┘   └────┬────┘
                 │                           │
        ┌────────┴────────┐         ┌───────┴────────┐
        │                 │         │                │
    ┌───▼───┐      ┌─────▼─────┐  ┌▼──────┐  ┌─────▼─────┐
    │Postgres│     │   Redis   │  │ MinIO │  │  Airflow  │
    │(StatefulSet) │           │  │  (S3) │  │           │
    └───────┘      └───────────┘  └───────┘  └───────────┘
```

### **리소스 할당**

| 서비스 | CPU Request | CPU Limit | Memory Request | Memory Limit |
|--------|-------------|-----------|----------------|--------------|
| Frontend | 200m | 500m | 256Mi | 512Mi |
| Backend | 500m | 1000m | 512Mi | 1Gi |
| PostgreSQL | 1000m | 2000m | 2Gi | 4Gi |
| Redis | 200m | 500m | 256Mi | 512Mi |
| JupyterLab | 1000m | 2000m | 2Gi | 4Gi |
| MLflow | 500m | 1000m | 1Gi | 2Gi |
| Airflow Web | 500m | 1000m | 1Gi | 2Gi |
| Airflow Scheduler | 500m | 1000m | 1Gi | 2Gi |

---

## 🔧 설정

### **환경별 설정 파일**

- `values-dev.yaml` - 개발 환경 (리소스 최소화)
- `values-prod.yaml` - 프로덕션 환경 (HA, 모니터링)
- `values-staging.yaml` - 스테이징 환경

### **주요 설정 항목**

```yaml
# values.yaml 예시
global:
  domain: datapond.local
  storageClass: local-path

backend:
  replicas: 2
  image: datapond/backend:latest
  resources:
    requests:
      cpu: 500m
      memory: 512Mi

frontend:
  replicas: 2
  image: datapond/frontend:latest

postgres:
  enabled: true
  persistence:
    size: 50Gi

redis:
  enabled: true
  
jupyter:
  enabled: true
  replicas: 1

mlflow:
  enabled: true
```

---

## 📈 모니터링

### **Prometheus + Grafana**

```bash
# Prometheus 설치
kubectl apply -f monitoring/prometheus/

# Grafana 설치
kubectl apply -f monitoring/grafana/

# Grafana 접속
kubectl port-forward -n monitoring svc/grafana 3000:3000
# http://localhost:3000 (admin/admin)
```

### **주요 메트릭**

- Pod CPU/Memory 사용률
- 서비스 응답 시간
- Database 쿼리 성능
- Ingress 트래픽

---

## 🔒 보안

### **Secret 관리**

```bash
# Secret 생성
kubectl create secret generic datapond-secrets \
  --from-literal=postgres-password=yourpassword \
  --from-literal=jwt-secret=yoursecret \
  -n datapond

# 또는 파일에서
kubectl apply -f k8s/secrets/
```

### **네트워크 정책**

- Pod 간 통신 제한
- Ingress만 외부 노출
- Database는 내부 접근만

---

## 🔄 운영

### **업데이트**

```bash
# Helm으로 업데이트
helm upgrade datapond ./helm/datapond \
  --namespace datapond \
  --values helm/datapond/values-prod.yaml

# 롤백
helm rollback datapond -n datapond
```

### **스케일링**

```bash
# 수동 스케일링
kubectl scale deployment backend --replicas=5 -n datapond

# HPA (자동 스케일링) - 이미 적용됨
kubectl get hpa -n datapond
```

### **백업**

```bash
# 데이터베이스 백업
bash scripts/backup.sh

# 복원
bash scripts/restore.sh <backup-file>
```

---

## 🐛 트러블슈팅

### **Pod가 시작하지 않음**

```bash
# 로그 확인
kubectl logs <pod-name> -n datapond

# 이벤트 확인
kubectl describe pod <pod-name> -n datapond

# 전체 상태
kubectl get events -n datapond --sort-by='.lastTimestamp'
```

### **Ingress 접근 불가**

```bash
# Ingress 상태
kubectl get ingress -n datapond

# Traefik 로그 (K3s 기본)
kubectl logs -n kube-system -l app.kubernetes.io/name=traefik
```

### **Storage 문제**

```bash
# PVC 상태
kubectl get pvc -n datapond

# PV 상태
kubectl get pv
```

---

## 📚 추가 문서

- [설치 가이드](docs/INSTALLATION.md)
- [설정 가이드](docs/CONFIGURATION.md)
- [운영 가이드](docs/OPERATIONS.md)
- [트러블슈팅](docs/TROUBLESHOOTING.md)

---

## 🆚 기존 버전과 비교

| 항목 | 기존 (Docker Compose) | K8s 버전 |
|------|----------------------|----------|
| 배포 시간 | 수동, 10-30분 | 자동, 5분 |
| 스케일링 | 수동 | 자동 (HPA) |
| 고가용성 | ❌ | ✅ |
| 모니터링 | 수동 설정 | 통합됨 |
| 롤백 | 어려움 | 1-command |
| 업데이트 | 다운타임 | 무중단 |
| 리소스 관리 | 수동 | 자동 (Requests/Limits) |

---

## 📞 지원

문제 발생 시:
1. `kubectl get pods -n datapond` - Pod 상태 확인
2. `kubectl logs <pod-name> -n datapond` - 로그 확인
3. `kubectl describe pod <pod-name> -n datapond` - 상세 정보

---

**버전**: 2.0.0-k8s  
**최초 작성**: 2026-04-28  
**Kubernetes 최소 버전**: 1.25+  
**K3s 권장 버전**: 1.28+
