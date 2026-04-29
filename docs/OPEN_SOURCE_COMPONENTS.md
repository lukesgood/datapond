# DataPond 오픈소스 컴포넌트 목록

**작성일**: 2026-04-29  
**버전**: 4.0.0  
**목적**: Software Bill of Materials (SBOM) — 구매·법무·보안 검토용

---

## 개요

DataPond는 아래 오픈소스 컴포넌트를 기반으로 구축됩니다.  
모든 핵심 컴포넌트는 **상업적 사내 배포(On-Premises) 및 재판매에 허용적인 라이선스**를 사용합니다.

### 라이선스 위험도 요약

| 위험도 | 설명 |
|--------|------|
| 🟢 Safe | Apache 2.0 / MIT / BSD / PostgreSQL License — 제약 없음 |
| 🟡 Caution | 특정 조건 확인 필요 |
| 🔴 Avoid | SSPL / AGPL 등 소스 공개 의무 발생 가능 |

---

## 1. 인프라 레이어

| 컴포넌트 | 버전 | 라이선스 | 위험도 | 용도 |
|---------|------|---------|--------|------|
| **Kubernetes** | 1.25+ | Apache 2.0 | 🟢 Safe | 컨테이너 오케스트레이션 |
| **K3s** (Rancher) | 1.28+ | Apache 2.0 | 🟢 Safe | 경량 Kubernetes (온프렘) |
| **Helm** | 3.12+ | Apache 2.0 | 🟢 Safe | Kubernetes 패키지 관리 |
| **Traefik** | 2.10+ | MIT | 🟢 Safe | Ingress Controller (개발) |
| **Nginx Ingress** | 1.8+ | Apache 2.0 | 🟢 Safe | Ingress Controller (프로덕션) |
| **cert-manager** | 1.13+ | Apache 2.0 | 🟢 Safe | TLS 인증서 자동화 |

---

## 2. 스토리지 레이어

| 컴포넌트 | 버전 | 라이선스 | 위험도 | 용도 |
|---------|------|---------|--------|------|
| **SeaweedFS** | latest | Apache 2.0 | 🟢 Safe | 분산 오브젝트 스토리지 (S3 호환) |
| **Apache Iceberg** | 1.4+ | Apache 2.0 | 🟢 Safe | 오픈 테이블 포맷 (ACID, Time Travel) |

---

## 3. 컴퓨트 레이어

| 컴포넌트 | 버전 | 라이선스 | 위험도 | 용도 |
|---------|------|---------|--------|------|
| **Apache Spark** | 3.5 | Apache 2.0 | 🟢 Safe | 분산 배치 처리 |
| **Trino** | latest | Apache 2.0 | 🟢 Safe | 분산 SQL 쿼리 엔진 (OLAP) |
| **RisingWave** | 1.7+ | Apache 2.0 | 🟢 Safe | 실시간 스트리밍 SQL (PostgreSQL 호환) |
| **DuckDB** | 0.10+ | MIT | 🟢 Safe | 인-프로세스 OLAP (JupyterLab 내장) |

---

## 4. 카탈로그 & 거버넌스 레이어

| 컴포넌트 | 버전 | 라이선스 | 위험도 | 용도 |
|---------|------|---------|--------|------|
| **Apache Polaris** | latest | Apache 2.0 | 🟢 Safe | Iceberg REST Catalog (Unity Catalog 동등) |
| **OpenMetadata** | 1.3+ | Apache 2.0 | 🟢 Safe | 데이터 카탈로그, 자동 Lineage, 데이터 품질 |

---

## 5. 애플리케이션 레이어

| 컴포넌트 | 버전 | 라이선스 | 위험도 | 용도 |
|---------|------|---------|--------|------|
| **FastAPI** | 0.104+ | MIT | 🟢 Safe | Backend API 서버 (Python) |
| **Next.js** | 14+ | MIT | 🟢 Safe | Frontend (React 기반) |
| **PostgreSQL** | 16 | PostgreSQL License | 🟢 Safe | 메타데이터 DB (모든 서비스 공유) |
| **Valkey** | 7.2+ | BSD 3-Clause | 🟢 Safe | Redis 호환 캐시/세션 스토어 |
| **JupyterLab** | latest | BSD 3-Clause | 🟢 Safe | 인터랙티브 노트북 환경 |
| **Apache Airflow** | 2.8+ | Apache 2.0 | 🟢 Safe | 워크플로우 오케스트레이션 |
| **MLflow** | 2.10+ | Apache 2.0 | 🟢 Safe | ML 실험 추적 및 모델 레지스트리 |

---

## 6. AI 레이어

| 컴포넌트 | 버전 | 라이선스 | 위험도 | 용도 |
|---------|------|---------|--------|------|
| **LiteLLM** | latest | MIT | 🟢 Safe | 멀티모델 LLM 프록시 (100+ 모델 지원) |
| **Ollama** | latest | MIT | 🟢 Safe | 내부망 LLM 로컬 실행 (옵션) |
| **vLLM** | latest | Apache 2.0 | 🟢 Safe | GPU 기반 LLM 서빙 (옵션) |

> **LLM 모델 라이선스 주의**: Ollama/vLLM 자체는 MIT/Apache 2.0이지만, 로드하는 모델(Llama, Gemma 등)은 별도 라이선스를 가집니다. 자세한 내용은 [LLM 모델 라이선스 섹션](#llm-모델-라이선스) 참조.

---

## 7. 모니터링 레이어

| 컴포넌트 | 버전 | 라이선스 | 위험도 | 용도 |
|---------|------|---------|--------|------|
| **Prometheus** | 2.45+ | Apache 2.0 | 🟢 Safe | 메트릭 수집 |
| **Grafana** | 10.0+ | AGPL 3.0 | 🟡 Caution | 대시보드 시각화 |
| **Elasticsearch** | 8.10 | SSPL / Elastic License | 🟡 Caution | OpenMetadata 검색 인덱스 |

> **Grafana AGPL 주의**: Grafana 자체를 외부 고객에게 SaaS로 판매하는 경우 소스 공개 의무가 발생할 수 있습니다. 사내 배포(on-prem) 용도는 제약 없습니다. 상세 내용은 [라이선스 상세 분석](#라이선스-상세-분석) 참조.

> **Elasticsearch SSPL 주의**: 7.17 이후 버전은 SSPL 또는 Elastic License가 적용됩니다. OpenMetadata가 내부적으로 사용하는 용도(사내 검색)는 제약 없습니다.

---

## 8. 선택적 컴포넌트 (Optional)

| 컴포넌트 | 라이선스 | 위험도 | 용도 |
|---------|---------|--------|------|
| **HashiCorp Vault** | BSL 1.1 | 🟡 Caution | Secret 관리 (온프렘, 사내 사용 허용) |
| **Harbor** | Apache 2.0 | 🟢 Safe | 에어갭용 내부 컨테이너 레지스트리 |
| **Rook-Ceph** | Apache 2.0 | 🟢 Safe | 프로덕션 공유 스토리지 |
| **PgBouncer** | ISC License | 🟢 Safe | PostgreSQL 커넥션 풀링 |
| **Fluent Bit** | Apache 2.0 | 🟢 Safe | 로그 수집 및 전달 |
| **OpenTelemetry** | Apache 2.0 | 🟢 Safe | 분산 추적 |

---

## 라이선스 상세 분석

### Apache License 2.0

DataPond 핵심 컴포넌트의 대부분이 사용하는 라이선스.

| 항목 | 내용 |
|------|------|
| **상업적 사용** | ✅ 허용 |
| **사내 배포** | ✅ 허용 |
| **소스 코드 공개 의무** | ❌ 없음 |
| **수정 후 재배포** | ✅ 허용 (변경 명시 필요) |
| **특허 보호** | ✅ 기여자의 특허 사용권 부여 |
| **상표 사용** | ❌ 금지 |
| **준수 요건** | LICENSE 및 NOTICE 파일 포함 |

**사용 컴포넌트**: Kubernetes, K3s, Helm, Nginx Ingress, cert-manager, SeaweedFS, Apache Iceberg, Apache Spark, Trino, RisingWave, Apache Polaris, OpenMetadata, Apache Airflow, MLflow, Prometheus, vLLM, Harbor, Rook-Ceph, Fluent Bit, OpenTelemetry

---

### MIT License

| 항목 | 내용 |
|------|------|
| **상업적 사용** | ✅ 허용 |
| **사내 배포** | ✅ 허용 |
| **소스 코드 공개 의무** | ❌ 없음 |
| **특허 보호** | ❌ 없음 (Apache 2.0과 차이) |
| **준수 요건** | LICENSE 파일(MIT 전문) 포함 |

**사용 컴포넌트**: Traefik, DuckDB, FastAPI, Next.js, LiteLLM, Ollama

---

### BSD 3-Clause License

| 항목 | 내용 |
|------|------|
| **상업적 사용** | ✅ 허용 |
| **사내 배포** | ✅ 허용 |
| **소스 코드 공개 의무** | ❌ 없음 |
| **준수 요건** | 저작권 고지, 프로젝트 이름으로 홍보 금지 |

**사용 컴포넌트**: Valkey, JupyterLab

---

### PostgreSQL License

MIT와 동등한 수준의 허용적 라이선스.

| 항목 | 내용 |
|------|------|
| **상업적 사용** | ✅ 허용 |
| **SaaS 제공** | ✅ 허용 (AWS RDS, Google Cloud SQL 모두 사용) |
| **준수 요건** | 저작권 고지 |

---

### AGPL 3.0 (Grafana)

| 항목 | 내용 |
|------|------|
| **사내 사용 (On-Premises)** | ✅ 허용 — 소스 공개 의무 없음 |
| **SaaS로 외부 제공** | ⚠️ Grafana를 직접 외부 서비스로 판매 시 소스 공개 의무 |
| **DataPond 사용 시** | ✅ 사내 모니터링 용도이므로 제약 없음 |

> DataPond를 고객 온프렘에 납품하는 경우, Grafana를 포함해도 AGPL 위반이 아닙니다. Grafana 소스를 직접 수정하여 별도 SaaS 상품으로 판매하는 경우에만 적용됩니다.

---

### SSPL (Elasticsearch 7.17+)

| 항목 | 내용 |
|------|------|
| **사내 사용** | ✅ 허용 |
| **온프렘 납품** | ✅ 허용 (고객이 자체 운영) |
| **SaaS로 직접 판매** | ⚠️ Elasticsearch 자체를 SaaS로 판매 시 소스 공개 의무 |
| **DataPond 사용 시** | ✅ OpenMetadata 검색 인덱스 내부 용도, 제약 없음 |

---

### BSL 1.1 (HashiCorp Vault)

Business Source License — 4년 후 Apache 2.0으로 전환.

| 항목 | 내용 |
|------|------|
| **사내 사용** | ✅ 허용 |
| **온프렘 납품** | ✅ 허용 |
| **상업적 경쟁 제품 판매** | ❌ 금지 (Vault 자체를 경쟁 서비스로 판매) |
| **DataPond 사용 시** | ✅ Secret 관리 용도, 제약 없음 |

---

## LLM 모델 라이선스

내부망 LLM 실행 시 로드하는 모델의 라이선스를 별도 확인해야 합니다.

| 모델 | 라이선스 | 상업 사용 | 주요 제약 |
|------|---------|---------|---------|
| **Llama 3** (Meta) | Llama 3 Community License | ✅ MAU < 7억 | MAU 7억 초과 시 Meta 별도 계약 필요 |
| **Llama 3.1 / 3.2** | Llama 3.1 Community License | ✅ MAU < 7억 | 동일 |
| **Mistral 7B / 8x7B** | Apache 2.0 | ✅ 제약 없음 | — |
| **Mistral Large** | Mistral Research License | ⚠️ 비상업 연구만 | 상업 사용 시 유료 계약 |
| **Gemma** (Google) | Gemma Terms of Use | ✅ | 유해 콘텐츠 생성 금지 |
| **Qwen** (Alibaba) | Qwen License | ✅ | MAU 1억 초과 시 별도 협의 |
| **EXAONE** (LG AI) | EXAONE AI Model License | ✅ 비상업·연구 | 상업 사용 시 별도 계약 |
| **Phi-3** (Microsoft) | MIT | ✅ 제약 없음 | — |
| **Solar** (Upstage) | Apache 2.0 | ✅ 제약 없음 | — |

> **권장**: 상업적 온프렘 납품 환경에서는 **Mistral 7B (Apache 2.0)** 또는 **Phi-3 (MIT)**를 기본 오픈 모델로 권장합니다. Claude/GPT-4 API 연결 시에는 각 제공사 이용약관을 따릅니다.

---

## 준수 요건 체크리스트

### 온프렘 납품 시

```
□ LICENSE 파일 포함 (DataPond 자체 라이선스)
□ NOTICE 파일 포함 (아래 NOTICE 파일 양식 참조)
□ 각 컴포넌트 라이선스 파일을 /licenses/ 디렉토리에 포함
□ 수정한 컴포넌트가 있을 경우 변경 사항 명시
□ LLM 모델 라이선스 별도 확인 (사용 모델에 따라 다름)
□ Grafana, Elasticsearch 수정 배포 여부 확인 (미수정 시 제약 없음)
```

### 사내 운영 시

```
□ 별도 준수 요건 없음 (모든 컴포넌트 사내 사용 허용)
□ LLM 모델 라이선스 확인 (대부분 사내 사용 허용)
```

---

## NOTICE 파일 양식

납품 패키지에 포함해야 하는 NOTICE 파일 양식입니다.

```text
DataPond
Copyright 2026 DataPond

This product includes the following open source software:

------------------------------------------------------------
Infrastructure
------------------------------------------------------------
Kubernetes
  Copyright 2014 The Kubernetes Authors
  Apache License 2.0 — https://github.com/kubernetes/kubernetes

K3s
  Copyright 2019 Rancher Labs, Inc.
  Apache License 2.0 — https://github.com/k3s-io/k3s

Helm
  Copyright 2016 The Helm Authors
  Apache License 2.0 — https://github.com/helm/helm

Traefik
  Copyright 2016-2024 Containous SAS / Traefik Labs
  MIT License — https://github.com/traefik/traefik

------------------------------------------------------------
Storage
------------------------------------------------------------
SeaweedFS
  Copyright 2015-2024 Chris Lu
  Apache License 2.0 — https://github.com/seaweedfs/seaweedfs

Apache Iceberg
  Copyright 2017-2024 The Apache Software Foundation
  Apache License 2.0 — https://iceberg.apache.org/

------------------------------------------------------------
Compute
------------------------------------------------------------
Apache Spark
  Copyright 2014-2024 The Apache Software Foundation
  Apache License 2.0 — https://spark.apache.org/

Trino
  Copyright 2012-2024 Trino Software Foundation
  Apache License 2.0 — https://trino.io/

RisingWave
  Copyright 2022-2024 RisingWave Labs
  Apache License 2.0 — https://github.com/risingwavelabs/risingwave

DuckDB
  Copyright 2018-2024 DuckDB Labs
  MIT License — https://github.com/duckdb/duckdb

------------------------------------------------------------
Catalog & Governance
------------------------------------------------------------
Apache Polaris
  Copyright 2024 The Apache Software Foundation
  Apache License 2.0 — https://polaris.apache.org/

OpenMetadata
  Copyright 2021-2024 OpenMetadata Authors
  Apache License 2.0 — https://github.com/open-metadata/OpenMetadata

------------------------------------------------------------
Application
------------------------------------------------------------
FastAPI
  Copyright 2018 Sebastián Ramírez
  MIT License — https://github.com/fastapi/fastapi

Next.js
  Copyright 2016 Vercel, Inc.
  MIT License — https://github.com/vercel/next.js

PostgreSQL
  Copyright 1996-2024 PostgreSQL Global Development Group
  PostgreSQL License — https://www.postgresql.org/

Valkey
  Copyright 2024 The Linux Foundation
  BSD 3-Clause License — https://github.com/valkey-io/valkey

JupyterLab
  Copyright 2015-2024 Project Jupyter Contributors
  BSD 3-Clause License — https://github.com/jupyterlab/jupyterlab

Apache Airflow
  Copyright 2015-2024 The Apache Software Foundation
  Apache License 2.0 — https://airflow.apache.org/

MLflow
  Copyright 2018-2024 Databricks, Inc.
  Apache License 2.0 — https://mlflow.org/

------------------------------------------------------------
AI
------------------------------------------------------------
LiteLLM
  Copyright 2023-2024 BerriAI
  MIT License — https://github.com/BerriAI/litellm

Ollama
  Copyright 2023-2024 Ollama
  MIT License — https://github.com/ollama/ollama

------------------------------------------------------------
Monitoring
------------------------------------------------------------
Prometheus
  Copyright 2012-2024 The Prometheus Authors
  Apache License 2.0 — https://github.com/prometheus/prometheus

Grafana
  Copyright 2014-2024 Grafana Labs
  AGPL 3.0 — https://github.com/grafana/grafana
```

---

## 관련 문서

- [docs/LICENSE_COMPLIANCE.md](LICENSE_COMPLIANCE.md) — 라이선스별 상세 준수 가이드
- [docs/ARCHITECTURE.md](ARCHITECTURE.md) — 컴포넌트 아키텍처
