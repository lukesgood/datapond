# DataPond - AI-Native Open Lakehouse Platform

**🚀 Databricks의 오픈소스 대안, 1/10 비용으로 멀티모델 AI 지원**

[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.25+-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Helm](https://img.shields.io/badge/Helm-3.12+-0F1689?logo=helm&logoColor=white)](https://helm.sh/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)
[![LiteLLM](https://img.shields.io/badge/AI-Multi--Model-FF6B35)](https://litellm.ai/)

---

## 📋 What is DataPond?

DataPond는 Kubernetes 기반의 **100% 오픈소스 AI-Native 레이크하우스 플랫폼**입니다.

Databricks/Snowflake와 달리:
- ✅ **완전 무료** - 100% 오픈소스 (Apache 2.0, MIT, BSD)
- ✅ **10배 저렴** - 자체 호스팅으로 연간 $100K+ 절감
- ✅ **멀티모델 AI** - Claude, GPT-4, Gemini, Llama 선택 자유
- ✅ **데이터 주권** - On-premise, Private Cloud 배포 가능
- ✅ **벤더 중립** - Kubernetes로 어디서나 실행

> "Your Data Platform, Your Rules, 1/10 the Cost"

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
  - Federated Query: PostgreSQL + Iceberg + S3 통합

Orchestration:
  - Apache Airflow: 워크플로우 자동화
  - JupyterLab: 인터랙티브 데이터 분석
  - MLflow: ML 실험 추적 및 모델 관리
```

### 🤖 AI Assistant (LiteLLM 기반)
```yaml
자연어 → SQL 생성:
  "지난 30일 동안 매출 상위 10명의 고객 보여줘"
  → SELECT ... FROM ... WHERE ... ORDER BY ... LIMIT 10

코드 에러 자동 수정:
  에러 메시지 입력 → 수정된 코드 + 설명

데이터 인사이트:
  데이터 입력 → AI가 패턴/이상 탐지 + 추천 액션

쿼리 최적화:
  느린 쿼리 → 인덱스 제안 + 최적화된 쿼리

멀티모델 지원:
  - Claude Sonnet 4.6 (최고 품질)
  - GPT-4 (안정성)
  - Gemini Pro (비용 효율)
  - Llama 3 (자체 호스팅, 무료)
```

### 🚀 Kubernetes Native
```yaml
배포:
  - Helm Chart: 5분 설치
  - Multi-environment: dev/prod 분리
  - Auto-scaling: CPU 기반 HPA

운영:
  - High Availability: 멀티 레플리카
  - Self-healing: 자동 복구
  - Rolling Update: 무중단 배포

보안:
  - NetworkPolicy: Pod 간 통신 제어
  - RBAC: 역할 기반 권한 관리
  - TLS: Let's Encrypt 자동 인증서
```

---

## 🚀 빠른 시작

### Prerequisites
```bash
- Kubernetes 1.25+ (K3s, EKS, GKE, AKS 모두 가능)
- Helm 3.12+
- kubectl
- 8GB+ RAM (개발), 32GB+ RAM (프로덕션)
```

### 5분 설치

```bash
# 1. Helm 저장소 추가
helm repo add datapond https://datapond.io/charts
helm repo update

# 2. Namespace 생성
kubectl create namespace datapond

# 3. 설치 (개발 환경)
helm install datapond datapond/datapond \
  -n datapond \
  -f values-dev.yaml

# 4. 상태 확인
kubectl get pods -n datapond
kubectl get ingress -n datapond

# 5. 접속
# Frontend: http://datapond.local
# JupyterLab: http://datapond.local/jupyter
# Airflow: http://datapond.local/airflow
# MLflow: http://datapond.local/mlflow
```

### 또는 로컬에서 설치 (Git Clone)

```bash
# 1. Repository Clone
git clone https://github.com/datapond/datapond-k8s.git
cd datapond-k8s

# 2. 설치
helm install datapond ./helm/datapond \
  -n datapond \
  --create-namespace \
  -f helm/datapond/values-dev.yaml

# 3. 포트 포워딩 (로컬 테스트)
kubectl port-forward -n datapond svc/frontend 3000:3000
kubectl port-forward -n datapond svc/jupyter 8888:8888
```

---

## 🏗️ 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    Ingress (Traefik/Nginx)                  │
│              Single Entry Point + TLS Termination            │
└──────────────────────┬──────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┬─────────────────┐
       │               │               │                 │
┌──────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐ ┌───────▼────────┐
│  Frontend   │ │   Backend   │ │  JupyterLab │ │    Airflow     │
│  (Next.js)  │ │  (FastAPI)  │ │   (Python)  │ │ (Orchestrator) │
└─────────────┘ └──────┬──────┘ └─────────────┘ └────────────────┘
                       │
       ┌───────────────┼───────────────┬─────────────────┐
       │               │               │                 │
┌──────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐ ┌───────▼────────┐
│ PostgreSQL  │ │   Valkey    │ │   Spark    │ │     Trino      │
│    (DB)     │ │  (Cache)    │ │ (Compute)  │ │   (SQL Query)  │
└─────────────┘ └─────────────┘ └──────┬─────┘ └────────┬───────┘
                                       │                 │
                       ┌───────────────┴─────────────────┘
                       │
            ┌──────────▼───────────┐
            │    SeaweedFS (S3)    │
            │  + Apache Iceberg    │
            │   (Lakehouse Layer)  │
            └──────────────────────┘
                       │
            ┌──────────▼───────────┐
            │      LiteLLM         │
            │  (AI Multi-Model)    │
            │ Claude, GPT-4, Llama │
            └──────────────────────┘
```

### 데이터 흐름
```
1. 데이터 수집: Airflow DAG → SeaweedFS (S3)
2. 데이터 처리: Spark → Iceberg 테이블 생성/변환
3. 데이터 분석: Trino → Iceberg + PostgreSQL 연합 쿼리
4. ML 실험: JupyterLab + MLflow → 모델 학습/추적
5. AI 지원: LiteLLM → SQL 생성, 코드 수정, 인사이트
```

---

## 🆚 Databricks 비교

| 항목 | Databricks | DataPond | 차이 |
|------|-----------|----------|------|
| **월 비용** | $20K-$100K+ | $2K-$5K | **10배 저렴** |
| **라이센스** | 상용 (Proprietary) | 오픈소스 (Apache 2.0) | **완전 자유** |
| **AI 모델** | 단일 모델 | Claude, GPT-4, Gemini, Llama | **선택 자유** |
| **배포** | SaaS Only | K8s (On-prem, Cloud) | **데이터 주권** |
| **커스터마이징** | 제한적 | 완전 자유 (오픈소스) | **확장성** |
| **벤더 종속** | 높음 | 없음 | **독립성** |
| **학습 곡선** | 높음 (독자 API) | 중간 (표준 도구) | **표준 기반** |

### TCO (Total Cost of Ownership) 비교

```yaml
Databricks (100명 조직):
  - Platform: $50K/월
  - Storage: $10K/월
  - Compute: $40K/월
  - Total: $100K/월 = $1.2M/년

DataPond (100명 조직):
  - Infrastructure: $3K/월 (K8s 클러스터)
  - Storage: $1K/월 (S3)
  - LLM API: $1K/월 (캐싱으로 절감)
  - Total: $5K/월 = $60K/년

절감액: $1.14M/년 (95% 절감!)
```

---

## 📖 문서

### 시작하기
- [설치 가이드](docs/LAB_GUIDE.md) - 7가지 실습 Lab
- [아키텍처 문서](docs/ARCHITECTURE.md) - 전체 구조 설명
- [아키텍처 다이어그램](docs/ARCHITECTURE_DIAGRAMS.md) - 시각적 가이드

### 프로덕션 배포
- [프로덕션 준비 체크리스트](docs/PRODUCTION_READINESS_REVIEW.md)
- [보안 가이드](docs/LICENSE_COMPLIANCE.md) - 라이센스 준수
- [Redis → Valkey 마이그레이션](docs/REDIS_TO_VALKEY_MIGRATION.md)

### 기능 가이드
- [LiteLLM 통합](docs/LITELLM_INTEGRATION.md) - AI Assistant 설정
- [사용자 경험 개선](docs/USER_EXPERIENCE_IMPROVEMENTS.md)
- [페르소나 기반 UX](docs/PERSONA_BASED_UX.md)
- [관리자 UI](docs/ADMIN_UI_IMPROVEMENTS.md)

### 제품 전략
- [제품 컨셉](docs/PRODUCT_CONCEPT.md) - 제품 정의 및 로드맵
- [Databricks 비교](docs/DATABRICKS_FEATURE_COMPARISON.md) - 기능 차이 분석

---

## 🧪 실습 Lab

[LAB_GUIDE.md](docs/LAB_GUIDE.md)에서 7가지 실습을 제공합니다:

1. **Lab 1**: JupyterLab 데이터 분석
   - Pandas로 CSV 분석
   - PostgreSQL 연결
   - 시각화 (Matplotlib)

2. **Lab 2**: Spark로 Iceberg 테이블 생성
   - 1000개 샘플 이벤트 생성
   - 날짜 파티셔닝
   - 스키마 진화

3. **Lab 3**: Trino SQL 분석
   - 연합 쿼리 (PostgreSQL + Iceberg)
   - 집계 및 조인
   - 성능 최적화

4. **Lab 4**: Time Travel (스냅샷 관리)
   - 과거 데이터 조회
   - 스냅샷 롤백
   - 변경 이력 추적

5. **Lab 5**: MLflow 실험 추적
   - RandomForest 모델 학습
   - 하이퍼파라미터 튜닝
   - 모델 레지스트리

6. **Lab 6**: Airflow DAG 생성
   - ETL 파이프라인
   - 스케줄링
   - 에러 처리

7. **Lab 7**: 엔드투엔드 실시간 분석
   - Kafka → Spark Streaming → Iceberg
   - 실시간 대시보드

---

## 🤝 커뮤니티

### 기여하기
DataPond는 커뮤니티 주도 프로젝트입니다!

```bash
# 1. Fork & Clone
git clone https://github.com/YOUR_USERNAME/datapond-k8s.git

# 2. Branch 생성
git checkout -b feature/amazing-feature

# 3. Commit
git commit -m "Add amazing feature"

# 4. Push
git push origin feature/amazing-feature

# 5. Pull Request 생성
```

### 커뮤니티 채널
- 🐛 **Issues**: [GitHub Issues](https://github.com/datapond/datapond-k8s/issues)
- 💬 **Discord**: [Join Community](https://discord.gg/datapond)
- 📧 **Email**: community@datapond.io
- 🐦 **Twitter**: [@DataPond](https://twitter.com/datapond)

### Contributors
이 프로젝트에 기여해주신 분들:
<!-- ALL-CONTRIBUTORS-LIST:START -->
<!-- Automatically generated -->
<!-- ALL-CONTRIBUTORS-LIST:END -->

---

## 📊 프로젝트 상태

### 현재 버전: 2.0.0 (AI-Native Release)

```yaml
완료:
  - ✅ Lakehouse 아키텍처 (SeaweedFS + Iceberg + Trino)
  - ✅ 실시간 스트리밍 (RisingWave - Kafka + Flink 대체)
  - ✅ 데이터 거버넌스 (OpenMetadata - Collibra 대안)
  - ✅ 통합 오케스트레이션 (Airflow + Spark)
  - ✅ ML 플랫폼 (MLflow + JupyterLab)
  - ✅ AI Assistant (LiteLLM 멀티모델)
  - ✅ 라이센스 안전 (Valkey → Redis 대체)
  - ✅ 9가지 실습 Lab (전체 스택 커버)
  - ✅ 8,000+ 줄 문서

진행 중 (Phase 2 - 3개월):
  - 🔄 OAuth2 + RBAC 인증
  - 🔄 Unity Catalog 스타일 거버넌스
  - 🔄 Databricks SQL 스타일 BI 통합
  - 🔄 Declarative Pipelines (Delta Live Tables)
  - 🔄 통합 모니터링 (Prometheus + Grafana)

계획 중 (Phase 3 - 6개월):
  - 📋 AI Co-pilot (모든 UI에서)
  - 📋 시맨틱 검색 (벡터 DB)
  - 📋 AutoML
  - 📋 자동 문서화
```

### 로드맵
자세한 로드맵은 [PRODUCT_CONCEPT.md](docs/PRODUCT_CONCEPT.md)를 참조하세요.

---

## 📜 라이센스

DataPond는 [Apache License 2.0](LICENSE) 하에 배포됩니다.

모든 의존성 컴포넌트는 상업적 사용 및 SaaS 제공이 가능한 허용적 라이센스를 사용합니다:
- Apache 2.0: SeaweedFS, Spark, Iceberg, Trino, Airflow, MLflow
- MIT: LiteLLM, Ollama
- BSD 3-Clause: JupyterLab, Valkey
- PostgreSQL License: PostgreSQL

자세한 내용은 [LICENSE_COMPLIANCE.md](docs/LICENSE_COMPLIANCE.md)를 참조하세요.

---

## 🙏 감사의 말

DataPond는 다음 오픈소스 프로젝트들 위에 구축되었습니다:
- [Apache Spark](https://spark.apache.org/)
- [Apache Iceberg](https://iceberg.apache.org/)
- [Trino](https://trino.io/)
- [Apache Airflow](https://airflow.apache.org/)
- [MLflow](https://mlflow.org/)
- [SeaweedFS](https://github.com/seaweedfs/seaweedfs)
- [JupyterLab](https://jupyter.org/)
- [LiteLLM](https://github.com/BerriAI/litellm)
- [Valkey](https://valkey.io/)

---

## 🌟 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=datapond/datapond-k8s&type=Date)](https://star-history.com/#datapond/datapond-k8s&Date)

---

## 📞 Contact

- **Website**: https://datapond.io
- **Email**: hello@datapond.io
- **GitHub**: https://github.com/datapond/datapond-k8s
- **Discord**: https://discord.gg/datapond

---

<div align="center">

**Made with ❤️ by the DataPond Community**

[⭐ Star us on GitHub](https://github.com/datapond/datapond-k8s) | [📖 Read the Docs](https://docs.datapond.io) | [💬 Join Discord](https://discord.gg/datapond)

</div>
