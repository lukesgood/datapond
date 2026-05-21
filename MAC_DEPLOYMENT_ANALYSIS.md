# Mac에서 DataPond 구동 분석

**날짜**: 2026-05-21  
**비교 대상**: 현재 Linux (Ubuntu 24.04) vs Mac

---

## 📊 현재 Linux 환경

### 하드웨어
- **CPU**: AMD Ryzen 7 PRO 6850U (8코어 16쓰레드)
- **RAM**: 14GB (현재 9GB 사용)
- **Disk**: 241GB NVMe (76GB 사용, 34%)
- **Architecture**: x86_64 (amd64)

### 소프트웨어
- **OS**: Ubuntu 24.04 LTS (native Linux)
- **K8s**: K3s (경량 Kubernetes)
- **Container Runtime**: containerd (네이티브)

### 현재 리소스 사용량
```
Running Pods: 17개
Memory: 9.0GB / 14GB (64%)
CPU: 평균 60% 로드
Disk: 76GB / 241GB (34%)
```

### 성능 특성
- ✅ **네이티브 Linux**: 컨테이너 오버헤드 최소
- ✅ **K3s 최적화**: 단일 노드 환경에 최적화
- ✅ **Direct Hardware Access**: 가상화 없음
- ⚠️ **메모리 부족**: 14GB로 모든 서비스 실행 시 타이트

---

## 🍎 Mac 환경 시나리오

### Mac Silicon (M1/M2/M3)

#### 장점
1. **더 나은 통합 메모리**
   - Unified Memory Architecture
   - CPU-GPU 메모리 공유로 효율성 향상
   - 메모리 대역폭: 최대 400GB/s (vs x86 ~50GB/s)

2. **전력 효율**
   - 동일 성능 대비 전력 소비 50% 이하
   - 발열 적음, 팬 소음 적음
   - 배터리 수명 2-3배 (노트북의 경우)

3. **SSD 성능**
   - NVMe 통합 SSD: 읽기 7GB/s+
   - 현재 시스템 대비 2-3배 빠름

#### 단점
1. **ARM64 아키텍처 호환성 ⚠️**
   ```
   현재 이미지들:
   - datapond/backend:latest (amd64)
   - datapond/frontend:latest (amd64)  
   - apache/polaris:1.4.0 (amd64/arm64 지원)
   - trinodb/trino:latest (amd64/arm64 지원)
   - risingwavelabs/risingwave:v1.6.0 (amd64 only)
   - apache/airflow:2.8.1 (amd64/arm64 지원)
   ```
   
   **문제**: DataPond 커스텀 이미지들이 amd64 전용
   
   **해결책**:
   - Multi-arch 빌드 필요 (`docker buildx`)
   - 또는 Rosetta 2 에뮬레이션 (성능 20-30% 저하)

2. **Docker Desktop 오버헤드**
   - Mac에서는 Linux VM 위에서 Docker 실행
   - 메모리 오버헤드: 약 2-4GB
   - CPU 오버헤드: 약 10-15%
   - K3s도 VM 내부에서 실행

3. **제한된 Docker Desktop 리소스**
   - 기본 설정: CPU 6코어, RAM 8GB
   - DataPond 최소: CPU 8코어, RAM 12GB+ 필요
   - 수동으로 리소스 할당 증가 필요

4. **파일시스템 성능**
   - Volume mount 시 osxfs/gRPC FUSE 사용
   - I/O 성능 저하 (특히 많은 작은 파일)
   - PostgreSQL, SeaweedFS 영향

#### 예상 성능

**Mac Studio M2 Max (12코어 CPU, 32GB RAM 기준)**:
```
Single-thread: Linux 대비 +20%
Multi-thread (container): Linux 대비 -10% (VM 오버헤드)
Memory throughput: +300%
SSD I/O: +200%
전체 효율: Linux와 비슷 또는 약간 낮음
```

**MacBook Pro M3 Pro (12코어 CPU, 18GB RAM 기준)**:
```
CPU: Linux와 유사
Memory: 18GB (vs 14GB) → 여유 +4GB
Disk: 더 빠름
전체: 약간 나음 (메모리 여유 덕분)
```

---

### Mac Intel (x86_64)

#### 장점
1. **아키텍처 호환성 완벽**
   - 모든 amd64 이미지 네이티브 실행
   - 재빌드 불필요

2. **Docker Desktop 성숙도**
   - Intel Mac 지원이 더 오래됨
   - 안정성 높음

#### 단점
1. **모든 Mac Silicon 장점 상실**
   - 전력 효율 낮음
   - 발열 높음
   - 메모리 대역폭 낮음

2. **동일한 Docker Desktop 오버헤드**
   - Linux VM 오버헤드
   - 파일시스템 성능 저하

3. **구형 하드웨어**
   - 현재 단종 (2023년 이후 생산 중단)
   - 업그레이드 경로 없음

#### 예상 성능
```
Intel i9 (8코어 16쓰레드) vs 현재 Ryzen 7:
CPU: 비슷하거나 약간 낮음
Memory: 비슷 (DDR4 vs DDR5)
Docker 오버헤드: -15% 성능
전체: 현재보다 약간 느림
```

---

## 🔄 DataPond Mac 포팅 작업량

### 1. ARM64 Multi-arch 빌드 (필수)

**작업 필요**:
```bash
# Backend
cd backend
docker buildx build --platform linux/amd64,linux/arm64 -t datapond/backend:latest .

# Frontend
cd frontend
docker buildx build --platform linux/amd64,linux/arm64 -t datapond/frontend:latest .

# Jupyter (커스텀 이미지인 경우)
cd jupyter
docker buildx build --platform linux/amd64,linux/arm64 -t datapond/jupyter:latest .
```

**예상 소요 시간**: 4-8시간 (초기 설정 + 빌드 + 테스트)

**문제 가능성**:
- Python 네이티브 확장 (psycopg2, numpy) 재컴파일
- Node.js 네이티브 모듈 (sharp, canvas) ARM64 호환성
- 의존성 라이브러리 ARM64 바이너리 없음

### 2. Helm Values 조정

**Mac Docker Desktop 최적 설정**:
```yaml
# values-mac.yaml
global:
  imagePullPolicy: IfNotPresent

# 리소스 제한 축소 (VM 오버헤드 고려)
backend:
  resources:
    requests:
      cpu: 300m      # 200m → 300m
      memory: 384Mi  # 256Mi → 384Mi
    limits:
      cpu: 800m      # 500m → 800m
      memory: 768Mi  # 512Mi → 768Mi

# PostgreSQL: fsync 최적화 (osxfs 느린 I/O 대응)
postgres:
  persistence:
    storageClass: hostpath  # local-path 대신
  config:
    fsync: "off"            # 개발용만! 프로덕션 금지
    synchronous_commit: "off"

# SeaweedFS: 파일시스템 튜닝
seaweedfs:
  volume:
    persistence:
      storageClass: hostpath
```

### 3. Docker Desktop 설정

**권장 리소스 할당** (Docker Desktop → Settings → Resources):
```
CPUs: 10-12 (전체의 80%)
Memory: 16GB 이상 권장 (최소 12GB)
Swap: 4GB
Disk: 100GB+
```

---

## 📈 성능 비교 예측

### 시나리오 1: Mac Studio M2 Max (32GB RAM)

| 항목 | 현재 Linux | Mac M2 Max | 변화 |
|------|-----------|-----------|------|
| Pod 기동 시간 | 기준 | +10% (VM) | 🔻 |
| API 응답 속도 | 기준 | 비슷 | ➡️ |
| Trino 쿼리 | 기준 | +20% (메모리 BW) | 🔺 |
| PostgreSQL Write | 기준 | -20% (fsync) | 🔻 |
| Airflow DAG 실행 | 기준 | +10% (CPU) | 🔺 |
| 전체 안정성 | 기준 | 비슷 | ➡️ |
| **메모리 여유** | 5GB | **14GB** | 🔺🔺 |

**결론**: 메모리 여유 덕분에 더 많은 서비스 동시 실행 가능. 전체 성능은 비슷하거나 약간 나음.

### 시나리오 2: MacBook Pro M3 Pro (18GB RAM)

| 항목 | 현재 Linux | Mac M3 Pro | 변화 |
|------|-----------|-----------|------|
| Pod 기동 시간 | 기준 | +10% | 🔻 |
| API 응답 속도 | 기준 | 비슷 | ➡️ |
| Trino 쿼리 | 기준 | +15% | 🔺 |
| PostgreSQL Write | 기준 | -20% | 🔻 |
| Airflow DAG 실행 | 기준 | +5% | 🔺 |
| **메모리 여유** | 5GB | **7GB** | 🔺 |

**결론**: 약간 나음. 메모리 +4GB가 가장 큰 장점.

### 시나리오 3: Mac Intel i9 (16GB RAM)

| 항목 | 현재 Linux | Mac Intel | 변화 |
|------|-----------|-----------|------|
| 모든 항목 | 기준 | -10~15% | 🔻 |
| **메모리 여유** | 5GB | **4GB** | 🔻 |

**결론**: 권장하지 않음. VM 오버헤드로 현재보다 느림.

---

## 🎯 추천 사항

### ✅ Mac으로 이전 권장 조건

다음 조건을 **모두** 만족하는 경우:

1. **Mac Silicon (M1/M2/M3)** 소유
2. **RAM 24GB 이상** (32GB 권장)
3. **SSD 여유 공간 150GB+**
4. **ARM64 이미지 빌드 가능** (4-8시간 작업 투자 OK)
5. **개발/테스트 용도** (프로덕션 아님)

### ❌ Mac으로 이전 권장하지 않는 경우

1. **Mac Intel** 보유
2. **RAM 16GB 이하**
3. **프로덕션 배포** (native Linux가 더 안정적)
4. **ARM64 호환성 작업 부담**
5. **현재 환경이 잘 작동 중** (안 고쳐진 거 고치지 마라)

### 🤔 중립: 큰 차이 없음

**현재 Linux (14GB) vs Mac M2/M3 (18-24GB)**:
- 전체 성능: **±5% 차이** (오차 범위)
- 메모리 여유: Mac이 약간 나음
- 안정성: Linux가 약간 나음 (네이티브)
- 개발 편의성: Mac이 나음 (GUI, 도구들)

---

## 🔧 Mac 구동 시 필요 작업

### Phase 1: 환경 준비 (30분)
1. Docker Desktop 설치
2. Kubernetes 활성화 (Settings → Kubernetes)
3. Helm 설치 (`brew install helm`)
4. 리소스 할당 증가 (12GB+ RAM, 10+ CPU)

### Phase 2: 이미지 빌드 (4-8시간)
1. Multi-arch 빌드 환경 설정
   ```bash
   docker buildx create --use
   ```
2. Backend ARM64 빌드 및 테스트
3. Frontend ARM64 빌드 및 테스트
4. 의존성 문제 해결 (발생 시)

### Phase 3: 배포 및 검증 (1-2시간)
1. `values-mac.yaml` 작성
2. Helm 배포
3. 모든 Pod 정상 작동 확인
4. 기능 테스트 (FUNCTIONALITY_TEST_REPORT 재실행)

**총 소요 시간**: 6-11시간

---

## 💡 최종 결론

### 현재 상황 유지 권장 ⭐

**이유**:
1. ✅ **현재 환경이 잘 작동 중** (80% 기능 정상)
2. ✅ **네이티브 Linux 성능 우수** (오버헤드 없음)
3. ✅ **이미 최적화 완료** (K3s, single-node)
4. ⚠️ **Mac 이전 작업량 큼** (6-11시간)
5. ⚠️ **성능 향상 미미** (±5%)

### Mac 이전 고려 상황

다음 경우에만 이전 권장:

1. **Mac Studio M2 Ultra (64GB+ RAM) 보유**
   → 메모리 여유로 RisingWave 등 모든 서비스 동시 실행 가능

2. **ARM64 학습/테스트 목적**
   → 멀티 아키텍처 빌드 경험 습득

3. **Linux 머신이 다른 용도로 필요**
   → 자원 재분배 필요 시

4. **Mac이 주 개발 환경**
   → 단일 머신에서 개발+배포 통합

### 대안: 하이브리드 접근 🎯

**추천**: Mac에서 개발, Linux에서 배포

```
Mac (로컬 개발):
- Frontend/Backend 개발 (VS Code)
- Docker Compose로 핵심 서비스만
- 빠른 피드백 루프

Linux (통합 테스트):
- 전체 스택 K3s 배포
- 실제 환경 검증
- 성능 테스트
```

이 방식이 가장 실용적입니다.

---

## 📚 참고: Mac Docker Desktop 최적화 팁

배포한다면:

1. **Virtualization Framework 사용** (Settings → General)
   - VirtioFS 활성화 (파일 I/O 성능 향상)
   
2. **Resource Saver 비활성화** (Settings → Resources)
   - Background 성능 유지

3. **BuildKit 활성화**
   ```bash
   export DOCKER_BUILDKIT=1
   ```

4. **로컬 레지스트리 사용**
   ```bash
   # 빌드 시간 단축
   docker run -d -p 5000:5000 --name registry registry:2
   ```

5. **Rosetta 에뮬레이션 최후 수단**
   ```bash
   # ARM64 빌드 실패 시
   docker run --platform linux/amd64 ...
   # 성능 -20~30%
   ```
