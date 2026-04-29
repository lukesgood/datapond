# DataPond - AI-Native Lakehouse for Sovereign Infrastructure

**Databricks가 진입할 수 없는 온프렘·에어갭 환경을 위한 엔터프라이즈 AI 데이터 플랫폼**

[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.25+-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Helm](https://img.shields.io/badge/Helm-3.12+-0F1689?logo=helm&logoColor=white)](https://helm.sh/)
[![LiteLLM](https://img.shields.io/badge/AI-Multi--Model-FF6B35)](https://litellm.ai/)
[![Apache Iceberg](https://img.shields.io/badge/Table_Format-Apache_Iceberg-blue)](https://iceberg.apache.org/)

---

## 📋 What is DataPond?

DataPond는 **온프레미스·에어갭·프라이빗 클라우드** 환경에 특화된 AI-Native Lakehouse 플랫폼입니다.

Databricks는 클라우드 SaaS 전용 제품입니다. 다음 환경의 조직들은 Databricks를 도입할 수 없습니다:

- 🏦 **금융** — 금감원 규제, 망분리 의무, 고객 데이터 외부 반출 금지
- 🏛️ **공공·국방** — 에어갭 네트워크, 국정원 CC 인증 요건
- 🏥 **의료·바이오** — EMR 외부 전송 금지, 개인정보보호법
- 🏭 **제조·에너지** — OT 망 분리, 산업 기밀 보호

DataPond는 이 조직들이 Databricks 수준의 AI 데이터 플랫폼을 **자체 인프라 위에서** 운영할 수 있게 합니다.

> "DataPond는 Databricks가 들어올 수 없는 곳에서 엔터프라이즈 AI 데이터 플랫폼을 운영하는 유일한 방법입니다."

---

## ✨ 핵심 기능

### 🏗️ Modern Lakehouse Architecture

```yaml
Storage Layer:
  - SeaweedFS: 분산 오브젝트 스토리지 (S3 호환)
  - Apache Iceberg: ACID 트랜잭션, Time Travel, 스키마 진화

Compute Layer:
  - Apache Spark: 분산 배치 처리
  - Trino: 고성능 OLAP SQL 엔진
  - RisingWave: 실시간 스트리밍 SQL (Kafka + Flink 대체)
  - DuckDB: JupyterLab 내 초고속 로컬 쿼리

Catalog & Governance:
  - Apache Polaris: REST Catalog (Unity Catalog 수준 거버넌스)
  - OpenMetadata: 자동 Lineage, 데이터 카탈로그

Orchestration:
  - Apache Airflow: 워크플로우 자동화
  - JupyterLab: 인터랙티브 데이터 분석
  - MLflow: ML 실험 추적 및 모델 관리
```

### 🤖 AI-Native 설계

```yaml
내부망 LLM 지원:
  - LiteLLM으로 내부망 Ollama/vLLM 연결
  - 데이터가 외부로 나가지 않음
  - Claude, GPT-4, 내부 모델 선택적 사용

AI 기능:
  - 자연어 → SQL 생성 (스키마 인식)
  - 코드 에러 자동 수정
  - 데이터 이상 감지
  - 쿼리 최적화 제안
```

### 🔐 엔터프라이즈 거버넌스

```yaml
Apache Polaris:
  - RBAC: 테이블/스키마/컬럼 레벨 권한
  - 멀티테넌시: 부서별 데이터 격리
  - 감사 로그: 모든 데이터 접근 추적
  - Unity Catalog 수준 기능 ($0)

OpenMetadata:
  - Airflow/Spark/Trino/MLflow 자동 Lineage
  - 규제 감사 대응 (데이터 흐름 증명)
  - PII 자동 분류
```

### 🚀 Kubernetes Native (온프렘 최적화)

```yaml
배포:
  - Helm Chart: 단일 명령어 설치
  - 에어갭 지원: 오프라인 이미지 패키지
  - K3s: 단일 서버부터 시작 가능

운영:
  - High Availability: 멀티 레플리카
  - Self-healing: 자동 복구
  - Rolling Update: 무중단 배포

보안:
  - NetworkPolicy: Pod 간 통신 제어
  - RBAC: 역할 기반 권한 관리
  - TLS: 전 구간 암호화
```

---

## 🚀 빠른 시작

### Prerequisites

**Kubernetes 도구:**
- Kubernetes 1.25+ (K3s 권장 — 온프렘 단일 서버 지원)
- Helm 3.12+
- kubectl

**서버 사양:**

| 구성 | CPU | RAM | Disk |
|------|-----|-----|------|
| PoC / 개발 | 12 cores | 24 GB | 300 GB SSD |
| 소규모 프로덕션 (단일 노드) | 24 cores | 64 GB | 500 GB SSD |
| 엔터프라이즈 HA (3-node 클러스터) | 16 cores × 3 | 64 GB × 3 | 1 TB × 3 |

> 상세 사양: [docs/INSTALLATION.md](docs/INSTALLATION.md#시스템-요구사항)

### 5분 설치 (로컬 클론)

```bash
# 1. K3s 설치 (온프렘 단일 서버)
sudo bash scripts/install-k3s.sh

# 2. hosts 설정
echo "127.0.0.1  datapond.local" | sudo tee -a /etc/hosts

# 3. 배포
bash scripts/deploy.sh values-dev.yaml

# 4. 상태 확인
kubectl get pods -n datapond
kubectl get ingress -n datapond
```

### 접속

| 서비스 | URL |
|--------|-----|
| Frontend | http://datapond.local |
| Backend API | http://datapond.local/api |
| JupyterLab | http://datapond.local/jupyter |
| MLflow | http://datapond.local/mlflow |
| Airflow | http://datapond.local/airflow |

기본 계정: JupyterLab 토큰 `jupyter` / Airflow `airflow/airflow`

---

## 🏗️ 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    Ingress (Traefik/Nginx)                  │
└──────────────────────┬──────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┬─────────────────┐
       │               │               │                 │
┌──────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐ ┌───────▼────────┐
│  Frontend   │ │   Backend   │ │  JupyterLab │ │    Airflow     │
│  (Next.js)  │ │  (FastAPI)  │ │  + DuckDB   │ │ (Orchestrator) │
└─────────────┘ └──────┬──────┘ └─────────────┘ └────────────────┘
                       │
       ┌───────────────┼───────────────┬─────────────────┐
       │               │               │                 │
┌──────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐ ┌───────▼────────┐
│   Trino     │ │    Spark    │ │ RisingWave │ │ OpenMetadata   │
│  (SQL)      │ │  (Batch)   │ │ (Stream)   │ │  (Lineage)     │
└─────────────┘ └─────────────┘ └─────────────┘ └────────────────┘
                       │
              ┌────────▼─────────┐
              │  Apache Polaris  │
              │  (REST Catalog)  │
              └────────┬─────────┘
                       │
              ┌────────▼─────────┐
              │    SeaweedFS     │
              │  + Apache Iceberg│
              │  (Lakehouse)     │
              └────────┬─────────┘
                       │
              ┌────────▼─────────┐
              │    LiteLLM       │
              │  (내부망 LLM)     │
              │ Claude/Llama/etc │
              └──────────────────┘
```

### 데이터 흐름

```
[Real-time]  IoT/Kafka → RisingWave (PostgreSQL SQL) → Polaris → Iceberg
[Batch]      Airflow DAG → Spark → Polaris → Iceberg
[Analytics]  Trino → Polaris (권한 체크) → Iceberg
[DS/탐색]    JupyterLab → DuckDB (로컬 초고속) → Iceberg 직접 읽기
[ML]         JupyterLab → Spark → MLflow → Iceberg
[AI]         모든 UI → LiteLLM → 내부망 LLM (외부 미전송)
[Lineage]    모든 서비스 → OpenMetadata (자동 수집)
```

---

## 🆚 왜 DataPond인가?

### 시장 공백

| 상황 | 기존 해결책 | 문제 |
|------|------------|------|
| 망분리 의무 금융사 | Databricks | 외부 SaaS → 사용 불가 |
| 에어갭 공공기관 | Hadoop/Cloudera | 레거시, AI 기능 없음 |
| EMR 외부전송 금지 병원 | 자체 개발 | 높은 구축·유지 비용 |
| OT 망 분리 제조사 | 수동 분석 | 확장성 없음 |

**DataPond**: Kubernetes 위의 AI-Native Lakehouse → 모든 온프렘 환경에서 동작

### 기술 경쟁력

| 항목 | Cloudera CDP | 자체 개발 스택 | **DataPond** |
|------|-------------|--------------|-------------|
| **AI 통합** | 제한적 | 직접 개발 | ✅ LiteLLM 내장 (내부망 LLM) |
| **실시간 처리** | Kafka+Flink | 직접 통합 | ✅ RisingWave (PostgreSQL SQL) |
| **거버넌스** | 별도 제품 | 직접 개발 | ✅ Polaris + OpenMetadata |
| **설치 복잡도** | 수주 | 수개월 | ✅ Helm 단일 명령어 |
| **유지보수** | 전담팀 필요 | 전담팀 필요 | ✅ Kubernetes 자동화 |
| **아키텍처** | Hadoop 기반 | 파편화 | ✅ 현대 Lakehouse |

---

## 📖 문서

### 시작하기
- [QUICKSTART.md](QUICKSTART.md) — 5분 설치 가이드
- [docs/INSTALLATION.md](docs/INSTALLATION.md) — 상세 설치 가이드
- [docs/LAB_GUIDE.md](docs/LAB_GUIDE.md) — 7가지 실습 Lab

### 아키텍처
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 전체 구조 설명
- [docs/ARCHITECTURE_DIAGRAMS.md](docs/ARCHITECTURE_DIAGRAMS.md) — 시각적 가이드

### 기능 가이드
- [docs/LITELLM_INTEGRATION.md](docs/LITELLM_INTEGRATION.md) — AI Assistant 설정
- [docs/RISINGWAVE_INTEGRATION.md](docs/RISINGWAVE_INTEGRATION.md) — 실시간 스트리밍
- [docs/OPENMETADATA_INTEGRATION.md](docs/OPENMETADATA_INTEGRATION.md) — 데이터 거버넌스

### 제품 전략
- [docs/PRODUCT_CONCEPT.md](docs/PRODUCT_CONCEPT.md) — 제품 정의 및 로드맵
- [docs/DATABRICKS_FEATURE_COMPARISON.md](docs/DATABRICKS_FEATURE_COMPARISON.md) — 기능 비교

### 라이선스
- [docs/OPEN_SOURCE_COMPONENTS.md](docs/OPEN_SOURCE_COMPONENTS.md) — 오픈소스 컴포넌트 전체 목록 (SBOM)
- [docs/LICENSE_COMPLIANCE.md](docs/LICENSE_COMPLIANCE.md) — 라이선스 준수 가이드

### 프로덕션 운영
- [docs/PRODUCTION_READINESS_REVIEW.md](docs/PRODUCTION_READINESS_REVIEW.md) — 운영 준비 체크리스트
- [docs/DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md) — 배포 체크리스트
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — 문제 해결 가이드

---

## 📊 현재 개발 상태

```yaml
완료:
  - ✅ Lakehouse 아키텍처 (SeaweedFS + Iceberg + Trino)
  - ✅ 실시간 스트리밍 (RisingWave)
  - ✅ 데이터 거버넌스 (Apache Polaris + OpenMetadata)
  - ✅ 통합 오케스트레이션 (Airflow + Spark)
  - ✅ ML 플랫폼 (MLflow + JupyterLab + DuckDB)
  - ✅ AI Assistant (LiteLLM 멀티모델)
  - ✅ 라이선스 안전 (Valkey → Redis 대체)
  - ✅ Helm Chart (개발/프로덕션 환경 분리)

진행 중 (Phase 1):
  - 🔄 에어갭 배포 지원 (오프라인 이미지 패키지)
  - 🔄 OAuth2 + LDAP/AD 통합
  - 🔄 TLS 전 구간 자동화

계획 중 (Phase 2):
  - 📋 행/열 레벨 보안 (Polaris 확장)
  - 📋 감사 로그 무결성 보장
  - 📋 Prometheus + Grafana 모니터링
```

---

## 📞 Contact

- **Website**: https://datapond.io
- **Email**: hello@datapond.io

---

<div align="center">

**Built for organizations that own their data.**

</div>
