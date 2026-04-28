# DataPond Kubernetes 배포 체크리스트

**배포 전에 이 체크리스트를 반드시 확인하세요!**

---

## 📋 사전 준비

### 1. 시스템 요구사항 확인

- [ ] CPU: 최소 4 cores (권장: 8+ cores)
- [ ] RAM: 최소 8GB (권장: 16GB+)
- [ ] Disk: 최소 50GB SSD (권장: 100GB+ SSD)
- [ ] OS: Ubuntu 20.04+ / RHEL 8+ / Debian 11+
- [ ] 인터넷 연결 (Docker 이미지 다운로드용)

### 2. 네트워크 설정

- [ ] 포트 80, 443 외부 접근 가능 (Ingress용)
- [ ] 방화벽 규칙 확인
- [ ] 도메인 DNS 설정 (프로덕션)
- [ ] `/etc/hosts` 설정 (로컬/개발)

### 3. 백업 (기존 시스템이 있는 경우)

- [ ] PostgreSQL 데이터베이스 백업
- [ ] Jupyter 노트북 백업
- [ ] MLflow 실험 데이터 백업
- [ ] Airflow DAG 백업
- [ ] 환경 변수 및 설정 파일 백업

---

## 🔐 보안 설정

### 1. 비밀번호 변경 (프로덕션 필수!)

**절대 기본 비밀번호를 사용하지 마세요!**

#### values-prod.yaml 편집:

```bash
vi /home/luke/datapond-k8s/helm/datapond/values-prod.yaml
```

**변경 필요 항목:**

```yaml
# PostgreSQL 비밀번호
postgres:
  auth:
    password: CHANGE_THIS_STRONG_PASSWORD_123!@#  # ← 변경

# Airflow 관리자 비밀번호
airflow:
  auth:
    username: admin  # ← 필요시 변경
    password: CHANGE_THIS_AIRFLOW_PASSWORD_456!@#  # ← 변경

# MinIO 인증 정보
minio:
  auth:
    rootUser: CHANGE_THIS_MINIO_USER  # ← 변경
    rootPassword: CHANGE_THIS_MINIO_PASSWORD_789!@#  # ← 변경

# Jupyter 토큰
jupyter:
  env:
    - name: JUPYTER_TOKEN
      value: "CHANGE_THIS_JUPYTER_TOKEN_ABC!@#"  # ← 변경

# Grafana (모니터링 활성화 시)
monitoring:
  grafana:
    adminPassword: CHANGE_THIS_PASSWORD  # ← 변경
```

- [ ] PostgreSQL 비밀번호 변경
- [ ] Airflow 비밀번호 변경
- [ ] MinIO 인증 정보 변경
- [ ] Jupyter 토큰 변경
- [ ] Grafana 비밀번호 변경 (모니터링 사용 시)
- [ ] JWT Secret 변경 (`templates/secrets.yaml`)

### 2. TLS/SSL 설정 (프로덕션)

- [ ] 도메인 준비
- [ ] cert-manager 설치 (Let's Encrypt용)
- [ ] values-prod.yaml에서 `ingress.tls.enabled: true`
- [ ] 도메인 DNS A 레코드 설정

### 3. 네트워크 보안

- [ ] Network Policies 활성화 검토
- [ ] Pod Security Policy 활성화 검토
- [ ] RBAC 설정 확인

---

## 🚀 설치 단계

### Step 1: K3s 설치

```bash
cd /home/luke/datapond-k8s
sudo bash scripts/install-k3s.sh
```

**확인:**
- [ ] K3s 설치 완료
- [ ] kubectl 명령어 작동
- [ ] Helm 설치 완료
- [ ] Ingress Controller 실행 중
- [ ] Metrics Server 실행 중

```bash
# 확인 명령어
kubectl get nodes
kubectl get pods -n kube-system
helm version
```

### Step 2: 환경 선택 및 설정

**개발 환경:**
```bash
cp helm/datapond/values-dev.yaml helm/datapond/my-values.yaml
```

**프로덕션 환경:**
```bash
cp helm/datapond/values-prod.yaml helm/datapond/my-values.yaml
```

**설정 편집:**
```bash
vi helm/datapond/my-values.yaml
```

- [ ] 도메인 설정 (`global.domain`)
- [ ] 리소스 할당 확인 (시스템 사양에 맞게 조정)
- [ ] 비밀번호 모두 변경 (프로덕션)
- [ ] 활성화할 서비스 선택 (`*.enabled`)

### Step 3: /etc/hosts 설정 (로컬/개발)

```bash
echo "127.0.0.1  datapond.local" | sudo tee -a /etc/hosts
```

- [ ] /etc/hosts 항목 추가

### Step 4: 배포 실행

```bash
bash scripts/deploy.sh my-values.yaml
```

**또는 직접 Helm 명령어:**

```bash
helm install datapond ./helm/datapond \
  --namespace datapond \
  --create-namespace \
  --values helm/datapond/my-values.yaml
```

- [ ] 배포 명령 실행
- [ ] 에러 없이 완료

---

## ✅ 배포 후 확인

### 1. Pod 상태 확인

```bash
kubectl get pods -n datapond -w
```

**모든 Pod가 Running 상태가 될 때까지 대기 (5-10분 소요 가능)**

- [ ] frontend Pod: Running
- [ ] backend Pod: Running
- [ ] postgres Pod: Running
- [ ] redis Pod: Running
- [ ] jupyter Pod: Running
- [ ] mlflow Pod: Running
- [ ] minio Pod: Running
- [ ] airflow-webserver Pod: Running
- [ ] airflow-scheduler Pod: Running
- [ ] spark-master Pod: Running
- [ ] spark-worker Pod: Running

**문제 발생 시:**
```bash
# Pod 상세 정보
kubectl describe pod <pod-name> -n datapond

# 로그 확인
kubectl logs <pod-name> -n datapond

# 이벤트 확인
kubectl get events -n datapond --sort-by='.lastTimestamp'
```

### 2. Service 확인

```bash
kubectl get svc -n datapond
```

- [ ] 모든 Service가 생성됨
- [ ] ClusterIP가 할당됨

### 3. Ingress 확인

```bash
kubectl get ingress -n datapond
```

- [ ] Ingress 생성 완료
- [ ] ADDRESS 할당됨

### 4. Storage 확인

```bash
kubectl get pvc -n datapond
```

- [ ] 모든 PVC가 Bound 상태

### 5. 접속 테스트

**브라우저에서 접속:**

- [ ] Frontend: `http://datapond.local` 또는 `https://your-domain.com`
- [ ] Backend API: `http://datapond.local/api/health`
- [ ] JupyterLab: `http://datapond.local/jupyter`
- [ ] MLflow: `http://datapond.local/mlflow`
- [ ] Airflow: `http://datapond.local/airflow`
- [ ] Spark UI: `http://datapond.local/spark`
- [ ] MinIO Console: `http://datapond.local/minio-console`

**curl 테스트:**

```bash
# Backend Health Check
curl http://datapond.local/api/health

# Frontend
curl -I http://datapond.local
```

### 6. 로그인 테스트

**기본 계정 (개발):**
- [ ] Airflow: `admin / admin`
- [ ] JupyterLab: Token = `jupyter`
- [ ] MinIO: `minioadmin / minioadmin`

**프로덕션: 변경한 비밀번호 사용**

### 7. 기능 테스트

- [ ] Frontend 대시보드 로드
- [ ] Backend API 응답
- [ ] JupyterLab 노트북 생성/실행
- [ ] MLflow 실험 로그
- [ ] Airflow DAG 생성
- [ ] Spark 작업 제출

---

## 📊 모니터링 설정 (선택사항)

### Prometheus + Grafana 활성화

```yaml
# values.yaml
monitoring:
  enabled: true
  prometheus:
    enabled: true
  grafana:
    enabled: true
```

```bash
helm upgrade datapond ./helm/datapond \
  --namespace datapond \
  --values helm/datapond/my-values.yaml
```

- [ ] Prometheus 실행 확인
- [ ] Grafana 접속 확인
- [ ] 대시보드 import

---

## 🔄 백업 설정

### 자동 백업 설정

```bash
# Cron job으로 백업 스크립트 실행
crontab -e

# 매일 새벽 2시 백업
0 2 * * * /home/luke/datapond-k8s/scripts/backup.sh
```

- [ ] 백업 스크립트 테스트
- [ ] Cron job 설정
- [ ] 백업 저장소 확인 (충분한 공간)

---

## 🚨 롤백 준비

### 롤백 계획

```bash
# Helm 릴리스 히스토리 확인
helm history datapond -n datapond

# 이전 버전으로 롤백
helm rollback datapond <revision> -n datapond
```

- [ ] 롤백 명령어 숙지
- [ ] 백업 복구 절차 문서화

---

## 📝 최종 확인

### 배포 완료 체크리스트

- [ ] 모든 Pod Running 상태
- [ ] 모든 Service 정상
- [ ] Ingress 접속 가능
- [ ] 로그인 성공
- [ ] 주요 기능 작동
- [ ] 비밀번호 모두 변경 (프로덕션)
- [ ] TLS/SSL 설정 (프로덕션)
- [ ] 모니터링 활성화 (선택)
- [ ] 백업 설정 완료
- [ ] 문서 업데이트

---

## 📞 문제 해결

**문제 발생 시 수집할 정보:**

1. **시스템 정보:**
```bash
kubectl version
helm version
kubectl get nodes
free -h
df -h
```

2. **Pod 상태:**
```bash
kubectl get pods -n datapond
kubectl describe pod <pod-name> -n datapond
kubectl logs <pod-name> -n datapond --previous  # 이전 로그
```

3. **이벤트:**
```bash
kubectl get events -n datapond --sort-by='.lastTimestamp'
```

4. **리소스 사용량:**
```bash
kubectl top nodes
kubectl top pods -n datapond
```

**일반적인 문제:**

| 문제 | 원인 | 해결 |
|------|------|------|
| Pod Pending | 리소스 부족 | values.yaml에서 resources 줄이기 |
| ImagePullBackOff | 이미지 없음 | 이미지 빌드 또는 레지스트리 확인 |
| CrashLoopBackOff | 애플리케이션 오류 | 로그 확인, 설정 검토 |
| Ingress 접속 안됨 | Ingress Controller 문제 | Controller Pod 확인 |
| PVC Pending | StorageClass 문제 | PV 수동 생성 또는 class 변경 |

---

## 🎯 다음 단계

배포 완료 후:

1. **성능 튜닝**: [OPERATIONS.md](OPERATIONS.md) 참고
2. **CI/CD 설정**: GitOps (ArgoCD/Flux)
3. **고가용성**: 멀티 노드 클러스터
4. **스케일링 테스트**: 부하 테스트 실행
5. **재해 복구**: DR 계획 수립

---

**배포 성공을 축하합니다! 🎉**

문제가 있으면 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)를 참고하세요.
