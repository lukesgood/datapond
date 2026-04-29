# DataPond Phase 0 Validation Checklist

**목표**: 데이터 인프라 통합 검증 (Backend/Frontend 제외)  
**예상 시간**: 30-60분  
**현재 단계**: K3s 설치 중

---

## ✅ Step 1: K3s 설치

**실행 중:**
```bash
sudo bash scripts/install-k3s.sh
```

**예상 소요 시간**: 2-3분

**성공 확인:**
```bash
kubectl version
kubectl get nodes
```

**예상 출력:**
```
NAME        STATUS   ROLES                  AGE   VERSION
localhost   Ready    control-plane,master   1m    v1.28.x+k3s1
```

---

## ✅ Step 2: /etc/hosts 설정

**실행:**
```bash
sudo bash -c 'echo "127.0.0.1  datapond.local" >> /etc/hosts'
```

**확인:**
```bash
cat /etc/hosts | grep datapond
```

**예상 출력:**
```
127.0.0.1  datapond.local
```

---

## ✅ Step 3: DataPond 배포

**실행:**
```bash
cd /home/luke/datapond

# Quick test 배포 (Backend/Frontend 제외)
helm install datapond ./helm/datapond \
  -n datapond \
  --create-namespace \
  -f helm/datapond/values-quicktest.yaml
```

**예상 소요 시간**: 1-2분

**확인:**
```bash
kubectl get pods -n datapond
```

---

## ✅ Step 4: Pod 상태 모니터링

**실행:**
```bash
kubectl get pods -n datapond -w
```

**예상 Pod 목록 (9개):**
```
NAME                                  READY   STATUS    RESTARTS   AGE
postgres-0                            1/1     Running   0          5m
valkey-xxx                            1/1     Running   0          5m
jupyter-xxx                           1/1     Running   0          4m
mlflow-xxx                            1/1     Running   0          4m
spark-master-0                        1/1     Running   0          4m
spark-worker-0                        1/1     Running   0          4m
seaweedfs-master-0                    1/1     Running   0          3m
seaweedfs-volume-0                    1/1     Running   0          3m
seaweedfs-filer-0                     1/1     Running   0          3m
seaweedfs-s3-xxx                      1/1     Running   0          3m
trino-xxx                             1/1     Running   0          3m
polaris-xxx                           1/1     Running   0          2m
risingwave-meta-0                     1/1     Running   0          2m
risingwave-frontend-xxx               1/1     Running   0          2m
risingwave-compute-0                  1/1     Running   0          2m
risingwave-compactor-xxx              1/1     Running   0          2m
openmetadata-elasticsearch-0          1/1     Running   0          2m
openmetadata-server-xxx               1/1     Running   0          1m
```

**전체 Running까지 예상 시간**: 5-10분

---

## ⚠️ Step 5: 문제 해결 (발생 시)

### Pod가 Pending 상태

**원인**: 리소스 부족 또는 PVC 바인딩 대기

**확인:**
```bash
kubectl describe pod <pod-name> -n datapond
kubectl get pvc -n datapond
```

**해결:**
- PVC가 Bound 될 때까지 대기 (보통 10-30초)
- 리소스 부족이면 values 조정

### Pod가 ImagePullBackOff

**원인**: 이미지를 찾을 수 없음

**확인:**
```bash
kubectl describe pod <pod-name> -n datapond | grep -A 5 "Events:"
```

**해결:**
- 퍼블릭 이미지 확인
- imagePullPolicy 확인

### Pod가 CrashLoopBackOff

**원인**: 애플리케이션 시작 실패

**확인:**
```bash
kubectl logs <pod-name> -n datapond
kubectl logs <pod-name> -n datapond --previous
```

**해결:**
- 로그 확인하여 원인 파악
- 환경변수 또는 설정 오류 수정

---

## ✅ Step 6: 서비스 접근 확인

### JupyterLab
```bash
# 브라우저에서:
http://datapond.local/jupyter

# Token: jupyter
```

### MLflow
```bash
http://datapond.local/mlflow
```

### Trino UI
```bash
http://datapond.local/trino
```

### RisingWave Dashboard
```bash
http://datapond.local/risingwave
```

### OpenMetadata
```bash
http://datapond.local/openmetadata
```

---

## ✅ Step 7: 통합 테스트

### Test 1: PostgreSQL 연결

```bash
kubectl exec -it postgres-0 -n datapond -- psql -U datapond -d datapond

# SQL:
\l
\dt
SELECT version();
\q
```

**예상 결과**: 연결 성공, 데이터베이스 목록 표시

### Test 2: SeaweedFS S3

```bash
# Port forward
kubectl port-forward -n datapond svc/seaweedfs-s3 8333:8333

# 별도 터미널에서:
curl http://localhost:8333
```

**예상 결과**: 200 OK 응답

### Test 3: Trino 쿼리

```bash
kubectl exec -it <trino-pod> -n datapond -- trino

# SQL:
SHOW CATALOGS;
SHOW SCHEMAS FROM iceberg;
SELECT 1;
```

**예상 결과**: Catalog 목록 표시

### Test 4: RisingWave 연결

```bash
kubectl port-forward -n datapond svc/risingwave-frontend 4566:4566

# 별도 터미널에서:
psql -h localhost -p 4566 -U root -d dev

# SQL:
SELECT version();
\q
```

**예상 결과**: RisingWave 버전 표시

### Test 5: OpenMetadata API

```bash
curl http://datapond.local/openmetadata/api/v1/health
```

**예상 결과**: `{"status":"healthy"}`

---

## ✅ Step 8: 리소스 사용량 확인

```bash
# Pod 리소스 사용
kubectl top pods -n datapond

# 노드 리소스 사용
kubectl top nodes
```

**예상 사용량:**
- CPU: 3-5 cores
- Memory: 6-8GB

**실제 vs 계획 비교:**
- values-quicktest.yaml에 정의된 리소스와 비교
- 너무 많이 사용하면 조정 필요

---

## ✅ Step 9: 로그 확인

```bash
# 모든 Pod 로그 한눈에
for pod in $(kubectl get pods -n datapond -o name); do
  echo "=== $pod ==="
  kubectl logs $pod -n datapond --tail=5
done
```

**확인 사항:**
- ERROR 메시지 없는지
- WARN 메시지 심각한지
- 정상 시작 메시지 있는지

---

## ✅ Step 10: 안정성 테스트

**장시간 실행:**
```bash
# 30분-1시간 동안 안정적으로 실행되는지 확인
watch -n 10 'kubectl get pods -n datapond'
```

**확인 사항:**
- Pod Restart 횟수가 증가하지 않는지
- 모든 Pod가 Running 유지되는지
- OOMKilled 발생하지 않는지

---

## 📊 검증 결과 요약

### 성공 기준

- [ ] K3s 설치 완료
- [ ] 모든 Pod Running (18개)
- [ ] 5개 서비스 UI 접근 가능
- [ ] PostgreSQL 연결 성공
- [ ] Trino 쿼리 실행 성공
- [ ] RisingWave 연결 성공
- [ ] OpenMetadata API 응답
- [ ] 30분 이상 안정적 실행
- [ ] 리소스 사용량 예상 범위 내
- [ ] 치명적 에러 없음

### 발견된 이슈

**이 섹션에 버그/문제점 기록:**

```
예시:
- Issue 1: postgres-0 초기화 5분 소요 (예상 1분)
  원인: 초기 데이터베이스 생성 시간
  해결: 정상 동작, 문서 업데이트 필요

- Issue 2: openmetadata-elasticsearch OOMKilled
  원인: Java heap 부족 (512MB)
  해결: values-quicktest.yaml 수정 필요 (1GB로 증가)
```

---

## 🎯 다음 단계

### 성공 시:

1. **Git 커밋**
   ```bash
   git add helm/datapond/values-quicktest.yaml VALIDATION_CHECKLIST.md
   git commit -m "feat: add quick test validation and checklist"
   ```

2. **문제 수정**
   - 발견된 버그 수정
   - 리소스 조정
   - 문서 업데이트

3. **Backend/Frontend 이미지 빌드**
   - Dockerfile 작성
   - 이미지 빌드
   - 전체 스택 재배포

4. **Lab 1-9 실행**
   - 각 Lab 가이드 검증
   - 문제점 문서화
   - 수정 및 재테스트

### 실패 시:

1. **이슈 문서화**
   - 에러 메시지 전체 복사
   - 재현 방법 기록
   - 스크린샷 저장

2. **롤백**
   ```bash
   helm uninstall datapond -n datapond
   kubectl delete namespace datapond
   ```

3. **분석 및 수정**
   - 근본 원인 파악
   - Helm 차트 수정
   - 재배포 시도

---

## 📞 도움 필요 시

**GitHub Issues:**
- https://github.com/lukesgood/datapond/issues

**참고 문서:**
- [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- [ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

**체크리스트 버전**: 1.0  
**작성일**: 2026-04-29  
**Phase**: 0 (Validation)  
**예상 완료 시간**: 30-60분
