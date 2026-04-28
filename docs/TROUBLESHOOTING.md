# DataPond Kubernetes 문제 해결 가이드

**자주 발생하는 문제와 해결 방법**

---

## 📋 목차

1. [진단 도구](#진단-도구)
2. [Pod 관련 문제](#pod-관련-문제)
3. [네트워킹 문제](#네트워킹-문제)
4. [스토리지 문제](#스토리지-문제)
5. [리소스 문제](#리소스-문제)
6. [서비스별 문제](#서비스별-문제)
7. [성능 문제](#성능-문제)

---

## 진단 도구

### 기본 진단 명령어

```bash
# 전체 상태 개요
kubectl get all -n datapond

# Pod 상태 (실시간)
kubectl get pods -n datapond -w

# 상세 정보
kubectl describe pod <pod-name> -n datapond

# 로그 확인
kubectl logs <pod-name> -n datapond
kubectl logs <pod-name> -n datapond --previous  # 이전 실행 로그

# 실시간 로그
kubectl logs -f <pod-name> -n datapond

# 이벤트 확인
kubectl get events -n datapond --sort-by='.lastTimestamp'

# 리소스 사용량
kubectl top nodes
kubectl top pods -n datapond
```

### 고급 진단

```bash
# Pod 내부 접속
kubectl exec -it <pod-name> -n datapond -- /bin/sh

# 네트워크 테스트
kubectl run -it --rm debug --image=nicolaka/netshoot -n datapond -- /bin/bash

# DNS 확인
kubectl exec -it <pod-name> -n datapond -- nslookup postgres
```

---

## Pod 관련 문제

### 1. Pod가 Pending 상태

**증상:**
```
NAME                      READY   STATUS    RESTARTS   AGE
backend-xxx               0/1     Pending   0          5m
```

**원인:**
- 노드 리소스 부족 (CPU/Memory)
- PVC가 Bound 안 됨
- Node selector 불일치
- Taints/Tolerations 문제

**진단:**
```bash
kubectl describe pod <pod-name> -n datapond

# 마지막 Events 섹션 확인:
# - "Insufficient cpu" → CPU 부족
# - "Insufficient memory" → 메모리 부족
# - "pod has unbound PVC" → 스토리지 문제
```

**해결:**

1. **리소스 부족:**
```yaml
# values.yaml 수정
backend:
  resources:
    requests:
      cpu: 200m  # 500m → 200m
      memory: 256Mi  # 512Mi → 256Mi
```

```bash
helm upgrade datapond ./helm/datapond \
  --namespace datapond \
  --values helm/datapond/values.yaml
```

2. **PVC 문제:** [스토리지 문제](#스토리지-문제) 참고

3. **노드 리소스 확인:**
```bash
kubectl describe nodes
# Allocated resources 섹션 확인
```

---

### 2. Pod가 CrashLoopBackOff

**증상:**
```
NAME                      READY   STATUS             RESTARTS   AGE
backend-xxx               0/1     CrashLoopBackOff   5          10m
```

**원인:**
- 애플리케이션 오류 (코드 버그)
- 잘못된 환경 변수
- 의존성 서비스 미실행 (예: DB 연결 실패)
- 이미지 문제

**진단:**
```bash
# 로그 확인
kubectl logs <pod-name> -n datapond
kubectl logs <pod-name> -n datapond --previous

# 상세 정보
kubectl describe pod <pod-name> -n datapond
```

**해결:**

1. **데이터베이스 연결 실패:**
```bash
# PostgreSQL Pod 확인
kubectl get pods -n datapond | grep postgres

# PostgreSQL 로그
kubectl logs postgres-0 -n datapond

# 연결 테스트
kubectl exec -it <backend-pod> -n datapond -- \
  nc -zv postgres 5432
```

2. **환경 변수 확인:**
```bash
kubectl exec <pod-name> -n datapond -- env | grep DATABASE
```

3. **Secret 확인:**
```bash
kubectl get secret datapond-secrets -n datapond -o yaml
```

---

### 3. Pod가 ImagePullBackOff

**증상:**
```
NAME                      READY   STATUS             RESTARTS   AGE
backend-xxx               0/1     ImagePullBackOff   0          2m
```

**원인:**
- 이미지가 존재하지 않음
- Registry 인증 실패
- 네트워크 문제

**진단:**
```bash
kubectl describe pod <pod-name> -n datapond
# Events에서 "Failed to pull image" 메시지 확인
```

**해결:**

1. **로컬 이미지 빌드 필요:**
```bash
# Backend 이미지 빌드
cd /home/luke/datapond/backend
podman build -t datapond/backend:latest .

# Frontend 이미지 빌드
cd /home/luke/datapond/frontend
podman build -t datapond/frontend:latest .

# K3s로 이미지 임포트
podman save datapond/backend:latest | sudo k3s ctr images import -
podman save datapond/frontend:latest | sudo k3s ctr images import -
```

2. **ImagePullPolicy 변경:**
```yaml
# values.yaml
global:
  imagePullPolicy: Never  # 로컬 이미지만 사용
```

3. **공개 이미지 사용 (테스트용):**
```yaml
backend:
  image:
    repository: python
    tag: "3.11-slim"
```

---

### 4. Pod가 Terminating에서 멈춤

**증상:**
```
NAME                      READY   STATUS        RESTARTS   AGE
backend-xxx               1/1     Terminating   0          1h
```

**원인:**
- Finalizer 문제
- 볼륨 언마운트 실패

**해결:**
```bash
# 강제 삭제
kubectl delete pod <pod-name> -n datapond --force --grace-period=0
```

---

## 네트워킹 문제

### 1. Service에 접속 안 됨

**증상:**
- Ingress로 접속 안 됨
- Service 간 통신 실패

**진단:**
```bash
# Service 확인
kubectl get svc -n datapond

# Endpoints 확인
kubectl get endpoints -n datapond

# Ingress 확인
kubectl get ingress -n datapond
kubectl describe ingress datapond-ingress -n datapond
```

**해결:**

1. **Ingress Controller 확인:**
```bash
# Traefik (K3s 기본)
kubectl get pods -n kube-system | grep traefik

# Nginx (별도 설치 시)
kubectl get pods -n ingress-nginx
```

2. **Service → Pod 연결 확인:**
```bash
# Endpoints가 비어있으면 Selector 문제
kubectl get endpoints backend -n datapond

# Label 확인
kubectl get pods -n datapond --show-labels
```

3. **/etc/hosts 확인 (로컬):**
```bash
cat /etc/hosts | grep datapond

# 없으면 추가
echo "127.0.0.1  datapond.local" | sudo tee -a /etc/hosts
```

---

### 2. DNS Resolution 실패

**증상:**
- Pod 내에서 서비스 이름으로 접속 안 됨
- "Name or service not known" 오류

**진단:**
```bash
# Pod 내에서 DNS 테스트
kubectl exec -it <pod-name> -n datapond -- nslookup postgres
kubectl exec -it <pod-name> -n datapond -- nslookup postgres.datapond.svc.cluster.local
```

**해결:**

1. **CoreDNS 확인:**
```bash
kubectl get pods -n kube-system | grep coredns
kubectl logs <coredns-pod> -n kube-system
```

2. **Service FQDN 사용:**
```yaml
# values.yaml
backend:
  env:
    - name: DATABASE_URL
      value: "postgresql://user:pass@postgres.datapond.svc.cluster.local:5432/db"
```

---

### 3. 외부 접속 안 됨

**증상:**
- 클라이언트 PC에서 `http://datapond.local` 접속 불가

**해결:**

1. **방화벽 확인 (서버):**
```bash
sudo ufw status
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

2. **/etc/hosts 설정 (클라이언트 PC):**
```
<server-ip>  datapond.local
```

3. **NodePort로 직접 접속 테스트:**
```bash
kubectl get svc -n datapond frontend

# NodePort 확인 (예: 30000)
curl http://<server-ip>:30000
```

---

## 스토리지 문제

### 1. PVC가 Pending

**증상:**
```
NAME            STATUS    VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS
postgres-pvc    Pending                                      local-path
```

**원인:**
- StorageClass가 없음
- 적합한 PV가 없음
- 디스크 공간 부족

**진단:**
```bash
# PVC 상세 정보
kubectl describe pvc postgres-pvc -n datapond

# StorageClass 확인
kubectl get storageclass

# PV 확인
kubectl get pv
```

**해결:**

1. **StorageClass 확인 (K3s는 기본 제공):**
```bash
kubectl get storageclass

# 없으면 K3s local-path provisioner 확인
kubectl get pods -n kube-system | grep local-path
```

2. **수동 PV 생성 (필요시):**
```yaml
# manual-pv.yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: postgres-manual-pv
spec:
  capacity:
    storage: 50Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: /data/postgres
  storageClassName: manual
```

```bash
sudo mkdir -p /data/postgres
kubectl apply -f manual-pv.yaml
```

3. **디스크 공간 확인:**
```bash
df -h
```

---

### 2. 데이터 손실

**증상:**
- Pod 재시작 후 데이터 사라짐

**원인:**
- PVC 미사용 (ephemeral storage)
- PVC가 삭제됨

**예방:**
```yaml
# values.yaml - persistence 활성화 확인
postgres:
  persistence:
    enabled: true
    size: 50Gi
```

**복구:**
```bash
# 백업에서 복구
bash scripts/rollback.sh
```

---

## 리소스 문제

### 1. 메모리 부족 (OOMKilled)

**증상:**
```
NAME                      READY   STATUS      RESTARTS   AGE
backend-xxx               0/1     OOMKilled   1          5m
```

**진단:**
```bash
kubectl describe pod <pod-name> -n datapond
# Last State: Terminated
#   Reason: OOMKilled
```

**해결:**

1. **메모리 제한 증가:**
```yaml
# values.yaml
backend:
  resources:
    limits:
      memory: 2Gi  # 1Gi → 2Gi
```

2. **시스템 메모리 확인:**
```bash
free -h
kubectl top nodes
```

3. **메모리 누수 확인:**
```bash
kubectl top pods -n datapond
```

---

### 2. CPU Throttling

**증상:**
- 애플리케이션이 느림
- CPU limits에 도달

**진단:**
```bash
kubectl top pods -n datapond
# CPU가 limits에 근접
```

**해결:**
```yaml
# values.yaml - CPU limits 증가
backend:
  resources:
    limits:
      cpu: 2000m  # 1000m → 2000m
```

---

## 서비스별 문제

### PostgreSQL

**문제: 연결 실패**

```bash
# PostgreSQL Pod 로그
kubectl logs postgres-0 -n datapond

# 연결 테스트
kubectl exec -it postgres-0 -n datapond -- psql -U datapond -d datapond

# 비밀번호 확인
kubectl get secret datapond-secrets -n datapond -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d
```

---

### JupyterLab

**문제: 접속 안 됨**

```bash
# JupyterLab 로그
kubectl logs <jupyter-pod> -n datapond

# Token 확인
kubectl get secret datapond-secrets -n datapond -o jsonpath='{.data.JUPYTER_TOKEN}' | base64 -d

# 직접 접속 (포트 포워딩)
kubectl port-forward <jupyter-pod> 8888:8888 -n datapond
# http://localhost:8888
```

---

### MLflow

**문제: Tracking URI 오류**

```bash
# MLflow 로그
kubectl logs <mlflow-pod> -n datapond

# SeaweedFS 확인 (artifact store)
kubectl get pods -n datapond | grep seaweedfs
kubectl logs <seaweedfs-pod> -n datapond

# DB 연결 확인
kubectl exec -it <mlflow-pod> -n datapond -- \
  nc -zv postgres 5432
```

---

### Airflow

**문제: Webserver 접속 안 됨**

```bash
# Init DB 로그 (초기화)
kubectl logs <airflow-webserver-pod> -n datapond -c init-db

# Webserver 로그
kubectl logs <airflow-webserver-pod> -n datapond -c webserver

# Scheduler 로그
kubectl logs <airflow-scheduler-pod> -n datapond

# DB 초기화 (필요시)
kubectl exec -it <airflow-pod> -n datapond -- airflow db reset
```

---

### Spark

**문제: Worker 연결 안 됨**

```bash
# Master 로그
kubectl logs <spark-master-pod> -n datapond

# Worker 로그
kubectl logs <spark-worker-pod-0> -n datapond

# Master URL 확인
kubectl exec -it <spark-worker-pod-0> -n datapond -- \
  env | grep SPARK_MASTER_URL
```

---

## 성능 문제

### 1. 느린 응답 시간

**진단:**
```bash
# 리소스 사용량
kubectl top pods -n datapond

# HPA 상태 (autoscaling)
kubectl get hpa -n datapond

# 메트릭 서버 확인
kubectl get pods -n kube-system | grep metrics-server
```

**해결:**

1. **HPA 활성화:**
```yaml
# values.yaml
backend:
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
```

2. **리소스 증가:**
```yaml
backend:
  resources:
    requests:
      cpu: 1000m
      memory: 1Gi
```

---

### 2. 디스크 I/O 병목

**진단:**
```bash
# 디스크 사용량
df -h

# I/O 성능
iostat -xz 1
```

**해결:**
- SSD 사용
- 스토리지 클래스 변경 (NVMe 등)
- 볼륨 크기 증가

---

## 일반적인 해결 절차

### 완전 재시작

```bash
# 1. Helm uninstall
helm uninstall datapond -n datapond

# 2. Namespace 삭제 (PVC도 삭제됨 - 주의!)
kubectl delete namespace datapond

# 3. 재설치
bash scripts/deploy.sh
```

### 특정 Pod 재시작

```bash
# Deployment 재시작 (Pod가 새로 생성됨)
kubectl rollout restart deployment backend -n datapond

# 또는 Pod 삭제 (자동 재생성)
kubectl delete pod <pod-name> -n datapond
```

### 설정 변경 적용

```bash
# values.yaml 수정 후
helm upgrade datapond ./helm/datapond \
  --namespace datapond \
  --values helm/datapond/values.yaml
```

---

## 긴급 복구

### 롤백

```bash
# 히스토리 확인
helm history datapond -n datapond

# 이전 버전으로 롤백
helm rollback datapond -n datapond

# 특정 리비전으로
helm rollback datapond 2 -n datapond
```

### 백업 복구

```bash
bash scripts/rollback.sh
```

---

## 로그 수집 (지원 요청 시)

```bash
# 전체 상태 수집
kubectl get all -n datapond > datapond-status.txt
kubectl describe pods -n datapond > datapond-pods.txt
kubectl get events -n datapond --sort-by='.lastTimestamp' > datapond-events.txt
kubectl logs <pod-name> -n datapond > pod-logs.txt

# 시스템 정보
kubectl version >> system-info.txt
kubectl get nodes -o wide >> system-info.txt
free -h >> system-info.txt
df -h >> system-info.txt
```

---

**문제가 해결되지 않으면 GitHub Issues에 위 정보와 함께 문의하세요.**
