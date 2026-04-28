# 🚀 DataPond Kubernetes - 시작하기

**Kubernetes 기반 DataPond가 배포 준비 완료되었습니다!**

---

## ⚡ 빠른 시작 (5분)

```bash
# 1단계: 디렉토리 이동
cd /home/luke/datapond-k8s

# 2단계: K3s 설치
sudo bash scripts/install-k3s.sh

# 3단계: /etc/hosts 설정
echo "127.0.0.1  datapond.local" | sudo tee -a /etc/hosts

# 4단계: 배포
bash scripts/deploy.sh values-dev.yaml

# 5단계: 확인
kubectl get pods -n datapond -w
# 모든 Pod가 Running 될 때까지 대기 (5-10분)

# 6단계: 접속
# 브라우저에서: http://datapond.local
```

---

## 📚 문서 가이드

### 처음 사용하시나요?
1. **[QUICKSTART.md](QUICKSTART.md)** - 5분 빠른 시작 (명령어 중심)
2. **[docs/INSTALLATION.md](docs/INSTALLATION.md)** - 상세 설치 가이드 (이론 포함)

### 배포 준비 중이신가요?
1. **[docs/DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md)** - 배포 전 체크리스트
2. **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - 프로젝트 전체 개요

### 문제가 발생했나요?
1. **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** - 문제 해결 가이드

### 프로젝트 상세 정보는?
1. **[COMPLETION_REPORT.md](COMPLETION_REPORT.md)** - 완료 보고서 (상세)
2. **[README.md](README.md)** - 프로젝트 개요

---

## 🎯 주요 URL

배포 후 접속 가능한 서비스:

| 서비스 | URL | 기본 계정 |
|--------|-----|----------|
| **Frontend** | http://datapond.local | - |
| **Backend API** | http://datapond.local/api | - |
| **JupyterLab** | http://datapond.local/jupyter | Token: `jupyter` |
| **MLflow** | http://datapond.local/mlflow | - |
| **Airflow** | http://datapond.local/airflow | admin / admin |
| **Spark UI** | http://datapond.local/spark | - |
| **MinIO Console** | http://datapond.local/minio-console | minioadmin / minioadmin |

---

## ✅ 배포 확인

```bash
# Pod 상태 확인
kubectl get pods -n datapond

# 모든 Pod가 다음과 같이 표시되어야 함:
# NAME                           READY   STATUS    RESTARTS   AGE
# backend-xxx                    1/1     Running   0          5m
# frontend-xxx                   1/1     Running   0          5m
# postgres-0                     1/1     Running   0          5m
# redis-xxx                      1/1     Running   0          5m
# jupyter-xxx                    1/1     Running   0          5m
# mlflow-xxx                     1/1     Running   0          5m
# minio-xxx                      1/1     Running   0          5m
# airflow-webserver-xxx          1/1     Running   0          5m
# airflow-scheduler-xxx          1/1     Running   0          5m
# spark-master-0                 1/1     Running   0          5m
# spark-worker-0                 1/1     Running   0          5m
```

---

## 🔧 자주 사용하는 명령어

```bash
# Pod 로그 확인
kubectl logs <pod-name> -n datapond

# Pod 재시작
kubectl rollout restart deployment/<service> -n datapond

# 서비스 스케일링
kubectl scale deployment <service> --replicas=3 -n datapond

# 포트 포워딩 (직접 접속)
kubectl port-forward svc/<service> <local-port>:<service-port> -n datapond

# 전체 삭제
helm uninstall datapond -n datapond
kubectl delete namespace datapond
```

---

## 📊 시스템 요구사항

### 개발 환경 (values-dev.yaml)
- **CPU**: 4+ cores ✅
- **RAM**: 8GB+ ✅ (현재 서버: 16GB)
- **Disk**: 100GB+ ✅ (현재 서버: 914GB)

**현재 서버 (4C/16GB/914GB)**: ✅ 개발 환경 실행 가능!

### 프로덕션 (values-prod.yaml)
- **CPU**: 16+ cores
- **RAM**: 32GB+
- **Disk**: 500GB+

---

## 🆘 문제 발생 시

### Pod가 시작 안 됨?
```bash
kubectl describe pod <pod-name> -n datapond
kubectl logs <pod-name> -n datapond
```

### 이미지가 없다고 나옴?
```bash
# Backend 이미지 빌드 (필요시)
cd /home/luke/datapond/backend
podman build -t datapond/backend:latest .
podman save datapond/backend:latest | sudo k3s ctr images import -

# Frontend 이미지 빌드 (필요시)
cd /home/luke/datapond/frontend
podman build -t datapond/frontend:latest .
podman save datapond/frontend:latest | sudo k3s ctr images import -
```

### 접속 안 됨?
```bash
# Ingress 확인
kubectl get ingress -n datapond

# /etc/hosts 확인
cat /etc/hosts | grep datapond
```

**더 많은 해결 방법**: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

---

## 🎉 완료!

모든 준비가 끝났습니다. 위의 **빠른 시작** 명령어를 실행하시면 됩니다!

**다음**: [QUICKSTART.md](QUICKSTART.md) 또는 [docs/DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md)

---

**버전**: 2.0.0-k8s  
**작성일**: 2026-04-28  
**상태**: ✅ READY FOR DEPLOYMENT
