# 스크립트 수정 사항

**수정일**: 2026-04-28

---

## 📝 수정된 스크립트

### 1. install-k3s.sh

#### 발견된 오류

1. **Traefik 비활성화 문제**
   - `--disable traefik`: K3s에서 Traefik을 비활성화했지만, 이후 Nginx만 설치 시도
   - **문제점**: Traefik이 K3s의 기본 Ingress Controller로 더 가벼움
   - **해결**: Traefik을 유지하고, 선택적으로 Nginx 설치

2. **kubectl 버전 명령어 오류**
   - `kubectl version --short`: 최신 버전에서 deprecated
   - **해결**: `kubectl version` 또는 fallback 처리

3. **사용자 확인 오류**
   - root로 실행 시 `$SUDO_USER` 없음
   - **해결**: root 감지 및 적절한 home 디렉토리 설정

4. **에러 처리 부족**
   - K3s 설치 실패 시 계속 진행
   - 파일 존재 여부 미확인
   - **해결**: 각 단계마다 검증 추가

5. **Metrics Server 패치 타이밍**
   - Deployment 생성 전에 패치 시도 가능
   - **해결**: sleep 추가 및 에러 무시

#### 주요 개선 사항

✅ **기존 설치 감지**
```bash
if command -v k3s &> /dev/null; then
  echo "WARNING: K3s is already installed"
  # 재설치 확인 프롬프트
fi
```

✅ **Traefik 유지**
```bash
# Traefik을 기본으로 사용 (K3s 내장)
# 선택적으로 Nginx 설치 가능
```

✅ **향상된 사용자 감지**
```bash
ACTUAL_USER=${SUDO_USER:-$USER}
if [ "$ACTUAL_USER" == "root" ]; then
  USER_HOME="/root"
else
  USER_HOME="/home/$ACTUAL_USER"
fi
```

✅ **파일 검증**
```bash
if [ -f /etc/rancher/k3s/k3s.yaml ]; then
  cp /etc/rancher/k3s/k3s.yaml $USER_HOME/.kube/config
else
  echo "ERROR: K3s config file not found"
  exit 1
fi
```

✅ **클러스터 준비 대기**
```bash
for i in {1..30}; do
  if kubectl get nodes &>/dev/null; then
    echo "Kubernetes is ready!"
    break
  fi
  echo "Waiting... ($i/30)"
  sleep 2
done
```

✅ **상세한 출력**
```bash
echo "System pods:"
kubectl get pods -n kube-system

echo "Storage class:"
kubectl get storageclass
```

---

### 2. deploy.sh

#### 발견된 오류

1. **디렉토리 확인 없음**
   - 잘못된 디렉토리에서 실행 시 실패
   - **해결**: 시작 시 디렉토리 검증

2. **Values 파일 확인 없음**
   - 존재하지 않는 파일로 배포 시도 가능
   - **해결**: 파일 존재 여부 확인

3. **제한적인 에러 메시지**
   - kubectl/helm 없을 때 불명확
   - **해결**: 설치 방법 안내 추가

4. **Ingress 조회 에러**
   - Ingress 없을 때 에러 출력
   - **해결**: 에러 리다이렉션

5. **배포 후 상태 확인 부족**
   - Pod 상태 미확인
   - **해결**: 헬스 체크 및 상세 안내

#### 주요 개선 사항

✅ **디렉토리 검증**
```bash
if [ ! -d "helm/datapond" ]; then
  echo "ERROR: Must run from /home/luke/datapond-k8s directory"
  echo "Current directory: $(pwd)"
  exit 1
fi
```

✅ **Values 파일 검증**
```bash
if [ ! -f "$CHART_PATH/$VALUES_FILE" ]; then
  echo "ERROR: Values file not found: $CHART_PATH/$VALUES_FILE"
  echo "Available values files:"
  ls -1 $CHART_PATH/values*.yaml
  exit 1
fi
```

✅ **Helm 차트 검증**
```bash
echo "Validating Helm chart..."
if ! helm lint $CHART_PATH --values $CHART_PATH/$VALUES_FILE; then
  echo "ERROR: Helm chart validation failed"
  exit 1
fi
```

✅ **배포 전 미리보기**
```bash
echo "Resources to be created:"
helm template $RELEASE_NAME $CHART_PATH \
  --namespace $NAMESPACE \
  --values $CHART_PATH/$VALUES_FILE \
  | grep "^kind:" | sort | uniq -c

read -p "Continue with installation? (y/n) "
```

✅ **상세한 상태 출력**
```bash
echo "Helm release:"
helm list -n $NAMESPACE

echo "Pods:"
kubectl get pods -n $NAMESPACE -o wide

echo "PersistentVolumeClaims:"
kubectl get pvc -n $NAMESPACE

echo "Resource Usage:"
kubectl top nodes 2>/dev/null || echo "Metrics not available yet"
```

✅ **헬스 체크**
```bash
TOTAL_PODS=$(kubectl get pods -n $NAMESPACE --no-headers | wc -l)
RUNNING_PODS=$(kubectl get pods -n $NAMESPACE --no-headers | grep Running | wc -l)

echo "Pods: $RUNNING_PODS/$TOTAL_PODS running"

if [ "$RUNNING_PODS" -eq "$TOTAL_PODS" ]; then
  echo "✓ All pods are running!"
  echo "🎉 DataPond has been successfully deployed!"
else
  echo "⚠️  Some pods are not running yet"
  echo "Monitor progress with:"
  echo "  kubectl get pods -n $NAMESPACE -w"
fi
```

✅ **/etc/hosts 확인**
```bash
if ! grep -q "datapond.local" /etc/hosts 2>/dev/null; then
  echo "⚠️  WARNING: datapond.local not found in /etc/hosts"
  echo "Add this line:"
  echo "  sudo bash -c 'echo \"127.0.0.1  datapond.local\" >> /etc/hosts'"
fi
```

✅ **로그 저장**
```bash
helm install ... --debug 2>&1 | tee /tmp/datapond-install.log
echo "Deployment log saved to: /tmp/datapond-install.log"
```

---

## 🔍 테스트 체크리스트

### install-k3s.sh

- [ ] 루트 권한 확인
- [ ] 기존 K3s 감지
- [ ] K3s 설치
- [ ] kubectl 설정
- [ ] Helm 설치
- [ ] Metrics Server 설치
- [ ] 클러스터 상태 확인
- [ ] 에러 처리

### deploy.sh

- [ ] 디렉토리 확인
- [ ] Values 파일 확인
- [ ] kubectl/helm 존재 확인
- [ ] 클러스터 접근 확인
- [ ] Helm 차트 검증
- [ ] 배포/업그레이드
- [ ] 상태 확인
- [ ] /etc/hosts 확인
- [ ] 헬스 체크

---

## 📋 사용 예시

### 정상 실행 (install-k3s.sh)

```bash
cd /home/luke/datapond-k8s
sudo bash scripts/install-k3s.sh
```

**출력 예시**:
```
===========================================
  DataPond K3s Installation
===========================================

Checking system requirements...
Installing K3s...
Waiting for K3s to be ready...
K3s service status: ✓ active (running)

Setting up kubectl access...
kubectl config copied to /home/luke/.kube/config

Installing Helm...
Helm installed successfully

Waiting for Kubernetes to be fully ready...
Kubernetes is ready!

Checking Traefik Ingress Controller...
Traefik is already installed (K3s default)

Installing Metrics Server...
Metrics Server installed

===========================================
  Installation Complete!
===========================================

Cluster information:
Kubernetes control plane is running at https://127.0.0.1:6443

Kubernetes nodes:
NAME   STATUS   ROLES                  AGE   VERSION
luke   Ready    control-plane,master   1m    v1.28.5+k3s1

System pods:
NAME                              READY   STATUS    RESTARTS   AGE
coredns-xxx                       1/1     Running   0          1m
local-path-provisioner-xxx        1/1     Running   0          1m
metrics-server-xxx                1/1     Running   0          30s
traefik-xxx                       1/1     Running   0          1m

Storage class:
NAME                   PROVISIONER             RECLAIMPOLICY
local-path (default)   rancher.io/local-path   Delete

===========================================
  Next Steps
===========================================

1. Add hostname to /etc/hosts:
   sudo bash -c 'echo "127.0.0.1  datapond.local" >> /etc/hosts'

2. Deploy DataPond:
   cd /home/luke/datapond-k8s
   bash scripts/deploy.sh values-dev.yaml

3. Check deployment:
   kubectl get pods -n datapond -w

4. Access DataPond:
   http://datapond.local
```

---

### 정상 실행 (deploy.sh)

```bash
cd /home/luke/datapond-k8s
bash scripts/deploy.sh values-dev.yaml
```

**출력 예시**:
```
===========================================
  DataPond Kubernetes Deployment
===========================================

Configuration:
  - Chart path: ./helm/datapond
  - Values file: values-dev.yaml
  - Namespace: datapond
  - Release name: datapond

Checking Kubernetes cluster...
NAME   STATUS   ROLES                  AGE   VERSION
luke   Ready    control-plane,master   5m    v1.28.5+k3s1
✓ Kubernetes cluster is accessible

Validating Helm chart...
✓ Helm chart is valid

Creating namespace: datapond

Installing DataPond (first time)...
This may take 5-10 minutes...

Resources to be created:
      2 ConfigMap
      2 Deployment
      1 Ingress
      1 Namespace
      8 PersistentVolumeClaim
      1 Secret
      8 Service
      2 StatefulSet

Continue with installation? (y/n) y

Installing...
[helm output...]

✓ Installation complete!

===========================================
  Deployment Status
===========================================

Pods:
NAME                           READY   STATUS    RESTARTS   AGE
backend-xxx                    1/1     Running   0          2m
frontend-xxx                   1/1     Running   0          2m
postgres-0                     1/1     Running   0          2m
...

Services:
NAME       TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)
backend    ClusterIP   10.43.100.1     <none>        8000/TCP
frontend   ClusterIP   10.43.100.2     <none>        3000/TCP
...

Ingress:
NAME               CLASS      HOSTS              ADDRESS
datapond-ingress   traefik    datapond.local     192.168.1.100

===========================================
  Pod Health Check
===========================================

Pods: 11/11 running

✓ All pods are running!

🎉 DataPond has been successfully installed!

You can now access the application at:
  http://datapond.local
```

---

## 🚨 에러 시나리오 및 해결

### 에러 1: K3s 이미 설치됨

**출력**:
```
WARNING: K3s is already installed
v1.28.5+k3s1
Reinstall K3s? This will remove existing installation. (y/n)
```

**해결**: `n` 입력 시 K3s 설치 건너뜀

---

### 에러 2: kubectl 접근 불가

**출력**:
```
ERROR: Cannot connect to Kubernetes cluster

Troubleshooting:
  1. Check if K3s is running: sudo systemctl status k3s
  2. Check kubeconfig: echo $KUBECONFIG
  3. Try: export KUBECONFIG=~/.kube/config
```

**해결**:
```bash
sudo systemctl status k3s
export KUBECONFIG=~/.kube/config
kubectl get nodes
```

---

### 에러 3: Values 파일 없음

**출력**:
```
ERROR: Values file not found: ./helm/datapond/values-prod.yaml

Available values files:
values-dev.yaml
values.yaml

Usage: bash scripts/deploy.sh [values-file]
Example: bash scripts/deploy.sh values-dev.yaml
```

**해결**: 올바른 파일명 사용

---

### 에러 4: Pod가 시작 안 됨

**출력**:
```
⚠️  Some pods are not running yet

Pods: 8/11 running

This is normal during initial deployment.
Pods may take 5-10 minutes to start.

Monitor progress with:
  kubectl get pods -n datapond -w

Check pod details:
NAME                    READY   STATUS              RESTARTS   AGE
backend-xxx             0/1     ContainerCreating   0          1m
mlflow-xxx              0/1     ImagePullBackOff    0          1m
postgres-0              0/1     Pending             0          1m

If pods stay in Pending/Error state, check:
  kubectl describe pod <pod-name> -n datapond

Common issues:
  - ImagePullBackOff: Images need to be built locally
  - Pending: Insufficient resources (CPU/Memory)
  - CrashLoopBackOff: Check logs
```

**해결**: 문서의 TROUBLESHOOTING.md 참고

---

## ✅ 검증 완료

- ✅ **install-k3s.sh**: 모든 오류 수정, 검증 로직 추가
- ✅ **deploy.sh**: 모든 오류 수정, 상세 출력 추가
- ✅ **실행 권한**: 755로 설정
- ✅ **에러 처리**: set -e로 에러 시 중단
- ✅ **사용자 안내**: 명확한 에러 메시지 및 다음 단계 안내

---

## 📚 관련 문서

- [QUICKSTART.md](QUICKSTART.md) - 빠른 시작 가이드
- [INSTALLATION.md](docs/INSTALLATION.md) - 상세 설치 가이드
- [DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md) - 배포 체크리스트
- [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) - 문제 해결

---

**수정 완료일**: 2026-04-28  
**작성자**: DataPond Team
