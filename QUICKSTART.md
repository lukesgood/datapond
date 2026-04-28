# DataPond K8s 빠른 시작 가이드

**5분 안에 DataPond를 Kubernetes에 배포하세요!**

---

## ✅ 사전 확인

현재 서버 사양:
```
CPU: 4 cores ✅
RAM: 16GB ✅
Disk: 914GB ✅

→ DataPond K8s 실행 가능!
```

---

## 🚀 설치 (3단계)

### **Step 1: K3s 설치** (2분)

```bash
cd /home/luke/datapond-k8s
sudo bash scripts/install-k3s.sh
```

이 명령어가:
- ✅ K3s (경량 Kubernetes) 설치
- ✅ Helm 설치
- ✅ Ingress Controller 설치
- ✅ Metrics Server 설치

### **Step 2: 설정** (1분)

```bash
# /etc/hosts에 추가
echo "127.0.0.1  datapond.local" | sudo tee -a /etc/hosts
```

### **Step 3: 배포** (2분)

```bash
bash scripts/deploy.sh
```

---

## 🌐 접속

```
http://datapond.local
```

**기본 계정**:
- Airflow: airflow / airflow
- JupyterLab: Token = jupyter
- PostgreSQL: datapond / datapond_password

---

## 📊 확인

```bash
# Pod 상태
kubectl get pods -n datapond

# 서비스 상태
kubectl get svc -n datapond

# 전체 리소스
kubectl get all -n datapond
```

---

## 🎯 주요 URL

| 서비스 | URL |
|--------|-----|
| Frontend | http://datapond.local |
| Backend API | http://datapond.local/api |
| JupyterLab | http://datapond.local/jupyter |
| MLflow | http://datapond.local/mlflow |
| Airflow | http://datapond.local/airflow |
| Spark UI | http://datapond.local/spark |

---

## 🔧 유용한 명령어

```bash
# 로그 보기
kubectl logs -f deployment/backend -n datapond

# Pod 재시작
kubectl rollout restart deployment/backend -n datapond

# 스케일링
kubectl scale deployment backend --replicas=5 -n datapond

# 포트 포워딩
kubectl port-forward svc/backend 8000:8000 -n datapond

# 삭제
helm uninstall datapond -n datapond
```

---

## 🆘 문제 해결

### Pod가 시작 안 됨?

```bash
kubectl describe pod <pod-name> -n datapond
kubectl logs <pod-name> -n datapond
```

### 접속 안 됨?

```bash
# Ingress 확인
kubectl get ingress -n datapond

# /etc/hosts 확인
cat /etc/hosts | grep datapond
```

### 리소스 부족?

```bash
# values.yaml에서 replicas 줄이기
# 또는 리소스 제한 낮추기
```

---

## 📚 더 알아보기

- [전체 설치 가이드](docs/INSTALLATION.md)
- [설정 가이드](docs/CONFIGURATION.md)
- [운영 가이드](docs/OPERATIONS.md)

---

**이게 전부입니다!** 🎉

DataPond가 Kubernetes에서 실행 중입니다.
