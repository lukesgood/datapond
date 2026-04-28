# DataPond Kubernetes 설치 가이드

## 📋 사전 요구사항

### **시스템 요구사항**

**최소 사양**:
- CPU: 4 cores
- RAM: 8GB
- Disk: 50GB
- OS: Ubuntu 20.04+ / RHEL 8+ / Debian 11+

**권장 사양**:
- CPU: 8+ cores
- RAM: 16GB+
- Disk: 100GB+ SSD
- OS: Ubuntu 22.04 LTS

### **필요한 도구**

설치 스크립트가 자동으로 설치하지만, 수동 설치 시 필요:
- kubectl (Kubernetes CLI)
- helm (Kubernetes 패키지 매니저)
- K3s or Kubernetes 1.25+

---

## 🚀 빠른 설치 (3단계)

### **Step 1: K3s 설치**

```bash
cd /home/luke/datapond-k8s
sudo bash scripts/install-k3s.sh
```

이 스크립트는 다음을 설치합니다:
- K3s (경량 Kubernetes)
- Helm 3
- Nginx Ingress Controller
- Metrics Server (HPA용)

**설치 시간**: 약 5-10분

### **Step 2: 설정 확인 및 수정**

```bash
cd helm/datapond

# 개발 환경
vi values-dev.yaml

# 또는 프로덕션 환경
vi values-prod.yaml
```

**주요 수정 항목**:
- `global.domain`: 도메인 이름 (기본: datapond.local)
- `postgres.auth.password`: PostgreSQL 비밀번호
- `*.replicas`: 각 서비스 복제본 수
- `*.resources`: 리소스 할당량

### **Step 3: DataPond 배포**

```bash
# 개발 환경으로 배포
bash scripts/deploy.sh values-dev.yaml

# 또는 프로덕션 환경으로 배포
bash scripts/deploy.sh values-prod.yaml
```

**배포 시간**: 약 5-10분

---

## 🔧 상세 설치 가이드

### **Option 1: 자동 설치 (권장)**

위의 "빠른 설치" 가이드를 따르세요.

---

### **Option 2: 수동 설치**

#### **1. K3s 설치**

```bash
# K3s 설치
curl -sfL https://get.k3s.io | sh -s - \
  --write-kubeconfig-mode 644

# kubectl 설정
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config

# 확인
kubectl get nodes
```

#### **2. Helm 설치**

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# 확인
helm version
```

#### **3. Ingress Controller 설치**

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.2/deploy/static/provider/cloud/deploy.yaml

# 대기
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

#### **4. Metrics Server 설치 (HPA용)**

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# K3s용 패치
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'
```

#### **5. DataPond 배포**

```bash
cd /home/luke/datapond-k8s

# Namespace 생성
kubectl create namespace datapond

# Helm으로 설치
helm install datapond ./helm/datapond \
  --namespace datapond \
  --values helm/datapond/values.yaml
```

---

## 🌐 접속 설정

### **로컬 접속 (단일 서버)**

1. `/etc/hosts` 파일 수정:

```bash
sudo vi /etc/hosts

# 다음 라인 추가:
127.0.0.1  datapond.local
```

2. 브라우저에서 접속:
```
http://datapond.local
```

### **원격 접속 (네트워크)**

1. `/etc/hosts` 파일 수정 (클라이언트 PC):

```
<server-ip>  datapond.local
```

2. 방화벽 포트 열기 (서버):

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

### **NodePort로 직접 접속**

Ingress 없이 직접 접속:

```bash
# Frontend NodePort 확인
kubectl get svc -n datapond frontend

# 출력 예시:
# NAME       TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)          AGE
# frontend   NodePort   10.43.100.123   <none>        3000:30000/TCP   5m

# 접속
http://<server-ip>:30000
```

---

## ✅ 설치 확인

### **Pod 상태 확인**

```bash
kubectl get pods -n datapond

# 모든 Pod가 Running 상태여야 함
# NAME                        READY   STATUS    RESTARTS   AGE
# backend-xxx                 1/1     Running   0          5m
# frontend-xxx                1/1     Running   0          5m
# postgres-0                  1/1     Running   0          5m
# redis-xxx                   1/1     Running   0          5m
# ...
```

### **Service 확인**

```bash
kubectl get svc -n datapond

# 모든 Service가 생성되어야 함
```

### **Ingress 확인**

```bash
kubectl get ingress -n datapond

# ADDRESS가 할당되어야 함
```

### **로그 확인**

```bash
# Backend 로그
kubectl logs -f deployment/backend -n datapond

# Frontend 로그
kubectl logs -f deployment/frontend -n datapond

# 특정 Pod 로그
kubectl logs <pod-name> -n datapond
```

### **접속 테스트**

```bash
# Backend Health Check
curl http://datapond.local/api/health

# Frontend
curl http://datapond.local
```

---

## 🔐 보안 설정

### **Secret 변경**

프로덕션 배포 전에 반드시 변경:

```bash
kubectl create secret generic datapond-secrets \
  --from-literal=postgres-password=<strong-password> \
  --from-literal=jwt-secret=<random-64-char-string> \
  --from-literal=minio-root-password=<strong-password> \
  -n datapond \
  --dry-run=client -o yaml | kubectl apply -f -
```

### **TLS/SSL 인증서 설정**

#### **Option 1: Let's Encrypt (자동)**

1. cert-manager 설치:

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
```

2. ClusterIssuer 생성:

```yaml
# letsencrypt-prod.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your-email@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
```

```bash
kubectl apply -f letsencrypt-prod.yaml
```

3. Ingress에 TLS 활성화:

```yaml
# values.yaml
ingress:
  enabled: true
  tls:
    enabled: true
    secretName: datapond-tls
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
```

#### **Option 2: 수동 인증서**

```bash
kubectl create secret tls datapond-tls \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key \
  -n datapond
```

---

## 📊 리소스 요구사항

### **기본 구성 (values.yaml)**

| 서비스 | CPU Request | Memory Request | Storage |
|--------|-------------|----------------|---------|
| Frontend | 200m | 256Mi | - |
| Backend | 500m | 512Mi | - |
| PostgreSQL | 1000m | 2Gi | 50Gi |
| Redis | 200m | 256Mi | 5Gi |
| JupyterLab | 1000m | 2Gi | 20Gi |
| MLflow | 500m | 1Gi | 20Gi |
| **Total** | **~4 CPU** | **~8GB RAM** | **~115GB** |

### **프로덕션 구성 (values-prod.yaml)**

고가용성 + 여유 리소스:

| 항목 | 필요량 |
|------|--------|
| CPU | 12-16 cores |
| RAM | 32-64GB |
| Storage | 250-500GB SSD |

---

## 🐛 문제 해결

### **Pod가 Pending 상태**

원인: 리소스 부족

```bash
# 노드 리소스 확인
kubectl describe nodes

# 해결: values.yaml에서 resources 줄이기
```

### **Pod가 CrashLoopBackOff**

```bash
# 로그 확인
kubectl logs <pod-name> -n datapond

# 이벤트 확인
kubectl describe pod <pod-name> -n datapond
```

### **Ingress 접속 안 됨**

```bash
# Ingress Controller 확인
kubectl get pods -n ingress-nginx

# Ingress 상세 정보
kubectl describe ingress -n datapond
```

### **Storage 문제**

```bash
# PVC 상태 확인
kubectl get pvc -n datapond

# PV 확인
kubectl get pv

# StorageClass 확인
kubectl get storageclass
```

---

## 🔄 업데이트 및 롤백

### **업데이트**

```bash
# 설정 변경 후
helm upgrade datapond ./helm/datapond \
  --namespace datapond \
  --values helm/datapond/values.yaml
```

### **롤백**

```bash
# 이전 버전으로 롤백
helm rollback datapond -n datapond

# 특정 리비전으로
helm rollback datapond <revision> -n datapond
```

### **히스토리 확인**

```bash
helm history datapond -n datapond
```

---

## 🗑️ 제거

### **DataPond만 제거**

```bash
helm uninstall datapond -n datapond
kubectl delete namespace datapond
```

### **K3s 완전 제거**

```bash
sudo /usr/local/bin/k3s-uninstall.sh
```

---

## 📞 지원

문제 발생 시:
1. 로그 수집: `kubectl logs <pod> -n datapond`
2. 이벤트 확인: `kubectl get events -n datapond`
3. 상태 확인: `kubectl describe pod <pod> -n datapond`

---

**다음 단계**: [설정 가이드](CONFIGURATION.md)
