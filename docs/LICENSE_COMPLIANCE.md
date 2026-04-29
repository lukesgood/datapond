# DataPond 라이센스 준수 가이드

**작성일**: 2026-04-29  
**버전**: 4.0.0  
**목적**: 컴포넌트별 라이선스 위험도 분석 및 온프렘 납품 준수 방안

> 전체 컴포넌트 목록(SBOM)은 [OPEN_SOURCE_COMPONENTS.md](OPEN_SOURCE_COMPONENTS.md)를 참조하세요.

---

## 📋 Executive Summary

DataPond는 오픈소스 컴포넌트로 구성되며, 모든 핵심 컴포넌트는 **온프렘 납품 및 사내 운영에 제약이 없는 허용적 라이선스**를 사용합니다.

### 라이선스 위험도 평가 (전체)

| 컴포넌트 | 라이선스 | 사내 사용 | 온프렘 납품 | 위험도 |
|---------|---------|---------|-----------|--------|
| Kubernetes / K3s / Helm | Apache 2.0 | ✅ | ✅ | 🟢 Safe |
| SeaweedFS | Apache 2.0 | ✅ | ✅ | 🟢 Safe |
| Apache Iceberg | Apache 2.0 | ✅ | ✅ | 🟢 Safe |
| Apache Spark | Apache 2.0 | ✅ | ✅ | 🟢 Safe |
| Trino | Apache 2.0 | ✅ | ✅ | 🟢 Safe |
| **RisingWave** | Apache 2.0 | ✅ | ✅ | 🟢 Safe |
| **DuckDB** | MIT | ✅ | ✅ | 🟢 Safe |
| **Apache Polaris** | Apache 2.0 | ✅ | ✅ | 🟢 Safe |
| **OpenMetadata** | Apache 2.0 | ✅ | ✅ | 🟢 Safe |
| FastAPI | MIT | ✅ | ✅ | 🟢 Safe |
| Next.js | MIT | ✅ | ✅ | 🟢 Safe |
| PostgreSQL | PostgreSQL License | ✅ | ✅ | 🟢 Safe |
| Valkey | BSD 3-Clause | ✅ | ✅ | 🟢 Safe |
| JupyterLab | BSD 3-Clause | ✅ | ✅ | 🟢 Safe |
| Apache Airflow | Apache 2.0 | ✅ | ✅ | 🟢 Safe |
| MLflow | Apache 2.0 | ✅ | ✅ | 🟢 Safe |
| LiteLLM | MIT | ✅ | ✅ | 🟢 Safe |
| Ollama | MIT | ✅ | ✅ | 🟢 Safe |
| Prometheus | Apache 2.0 | ✅ | ✅ | 🟢 Safe |
| **Grafana** | AGPL 3.0 | ✅ | ✅ | 🟡 Caution (사내 사용 제약 없음) |
| **Elasticsearch** | SSPL / Elastic | ✅ | ✅ | 🟡 Caution (사내 사용 제약 없음) |
| Redis 7.0–7.3 | SSPL | ⚠️ | ⚠️ | 🔴 Avoid |

### 결론
- ✅ **온프렘 납품 및 사내 운영: 모든 핵심 컴포넌트 제약 없음**
- ⚠️ **Grafana, Elasticsearch**: 사내 운영 제약 없음 / 해당 소프트웨어 자체를 SaaS 판매 시에만 주의
- 🚫 **Redis 7.0–7.3 (SSPL)**: 미사용 — Valkey(BSD 3-Clause)로 대체됨

---

## 🔍 컴포넌트별 라이센스 상세 분석

### 0. 신규 추가 컴포넌트 (v4.0)

#### Apache Polaris

**라이선스**: Apache License 2.0  
**출처**: Snowflake 기증 → Apache Software Foundation (2026년 2월 Top-Level Project 졸업)  
**GitHub**: https://github.com/apache/polaris

```yaml
특이사항:
  - Snowflake가 3년 프로덕션 운영 후 Apache에 기증
  - ASF Top-Level Project (최고 수준의 라이선스 안정성)
  - Databricks Unity Catalog의 오픈소스 동등 기능 제공
  
허용: 상업 사용, 사내 배포, 온프렘 납품 모두 허용
준수 요건: LICENSE + NOTICE 파일 포함
```

**위험도**: 🟢 **Safe** (ASF 프로젝트 중 가장 안전한 수준)

---

#### RisingWave

**라이선스**: Apache License 2.0  
**개발사**: RisingWave Labs  
**GitHub**: https://github.com/risingwavelabs/risingwave

```yaml
특이사항:
  - CNCF Sandbox → Incubating 단계
  - PostgreSQL 와이어 프로토콜 호환 스트리밍 SQL
  - Apache 2.0 (상업 사용, 온프렘 납품 제약 없음)

허용: 상업 사용, 사내 배포, 온프렘 납품 모두 허용
준수 요건: LICENSE + NOTICE 파일 포함
```

**위험도**: 🟢 **Safe**

---

#### DuckDB

**라이선스**: MIT License  
**개발사**: DuckDB Labs (CWI — 네덜란드 국립 수학 및 컴퓨터 과학 연구소)  
**GitHub**: https://github.com/duckdb/duckdb

```yaml
특이사항:
  - 인-프로세스 OLAP DB (SQLite for Analytics)
  - MIT 라이선스 — 가장 허용적
  - JupyterLab 노트북 내 로컬 쿼리 엔진으로 사용

허용: 상업 사용, 사내 배포, 온프렘 납품 모두 허용
준수 요건: MIT 라이선스 고지 포함
```

**위험도**: 🟢 **Safe**

---

#### OpenMetadata

**라이선스**: Apache License 2.0  
**개발사**: Collate Inc. (Linux Foundation 프로젝트)  
**GitHub**: https://github.com/open-metadata/OpenMetadata

```yaml
특이사항:
  - Linux Foundation 프로젝트 (라이선스 안정성 높음)
  - Collibra, Alation 등 상용 데이터 거버넌스 툴의 오픈소스 대안
  - 내부 의존성: Elasticsearch (SSPL/Elastic License)
  
내부 의존성 주의:
  - OpenMetadata 검색 기능이 Elasticsearch에 의존
  - Elasticsearch는 7.17 이후 SSPL/Elastic License 적용
  - 사내 사용(내부 검색 인덱스 용도): ✅ 제약 없음
  - Elasticsearch 자체를 SaaS 서비스로 판매: ❌ 주의 필요 (해당 없음)

허용: 상업 사용, 사내 배포, 온프렘 납품 모두 허용
준수 요건: LICENSE + NOTICE 파일 포함
```

**위험도**: 🟢 **Safe** (온프렘 내부 사용 목적)

---

#### Grafana

**라이선스**: AGPL 3.0 (Grafana OSS)  
**GitHub**: https://github.com/grafana/grafana

```yaml
AGPL 3.0 핵심 조건:
  - 소프트웨어를 네트워크를 통해 서비스로 제공(SaaS)하는 경우
    → 수정된 소스 코드를 공개해야 함
  
DataPond 사용 시나리오 분석:
  시나리오 1: 사내 모니터링 (온프렘) → ✅ 제약 없음
  시나리오 2: 고객 온프렘에 납품 (고객이 직접 운영) → ✅ 제약 없음
  시나리오 3: Grafana를 수정하여 SaaS로 판매 → ⚠️ 소스 공개 의무
  
DataPond 납품 용도: 모니터링 대시보드 (시나리오 1, 2)
결론: DataPond 납품 시 Grafana 포함 가능, AGPL 위반 없음

주의: Grafana 소스를 직접 수정하지 않는 것을 권장
대안: Grafana Enterprise 라이선스 구매 (수정 배포 허용)
```

**위험도**: 🟡 **Caution** (납품 시 사용 시나리오 확인 필요, 일반적으로 안전)

---

### 1. SeaweedFS

**라이센스**: Apache License 2.0  
**GitHub**: https://github.com/seaweedfs/seaweedfs

#### 라이센스 조건
```yaml
허용:
  - ✅ 상업적 사용
  - ✅ 수정 (Modification)
  - ✅ 배포 (Distribution)
  - ✅ 특허 사용 (Patent Grant)
  - ✅ 비공개 사용 (Private Use)
  - ✅ SaaS 제공

요구사항:
  - 📝 라이센스 및 저작권 고지 포함
  - 📝 변경사항 명시 (NOTICE 파일)

금지:
  - ❌ 상표권 사용 (Trademark)
  - ❌ 책임 및 보증 (No Warranty)
```

#### 준수 방법
```bash
# SeaweedFS NOTICE 파일 포함
# docker image 또는 배포 패키지에 다음 포함:
/licenses/
  ├── seaweedfs/
  │   ├── LICENSE (Apache 2.0 전문)
  │   └── NOTICE (저작권 고지)
```

**위험도**: 🟢 **Low** (매우 안전, 제약 없음)

---

### 2. Apache Spark

**라이센스**: Apache License 2.0  
**Website**: https://spark.apache.org/

#### 라이센스 조건
- SeaweedFS와 동일 (Apache 2.0)
- 상업적 사용, SaaS 제공 모두 가능

#### 준수 방법
```bash
# Spark 라이센스 포함
/licenses/spark/LICENSE
```

**위험도**: 🟢 **Low**

---

### 3. Apache Iceberg

**라이센스**: Apache License 2.0  
**Website**: https://iceberg.apache.org/

#### 라이센스 조건
- Apache 2.0 (상업 사용 가능)
- Netflix가 개발, Apache Foundation에 기증

**위험도**: 🟢 **Low**

---

### 4. Trino

**라이센스**: Apache License 2.0  
**Website**: https://trino.io/

#### 특이사항
- 구 Presto SQL (Facebook 개발)
- Trino Software Foundation 관리
- 상업적 사용 및 SaaS 제공 가능

#### 상업 지원
```yaml
# Trino는 상업 지원도 제공
- Starburst (Trino 기반 엔터프라이즈 제품)
- 필요시 상업 라이센스 구매 가능 (선택사항)
```

**위험도**: 🟢 **Low**

---

### 5. Apache Airflow

**라이센스**: Apache License 2.0  
**Website**: https://airflow.apache.org/

#### 라이센스 조건
- Apache 2.0 (상업 사용 가능)
- Airbnb 개발, Apache Foundation 기증

**위험도**: 🟢 **Low**

---

### 6. MLflow

**라이센스**: Apache License 2.0  
**Website**: https://mlflow.org/

#### 특이사항
- Databricks 개발 (Linux Foundation 기증)
- 상업적 사용 및 SaaS 제공 가능
- Databricks는 관리형 MLflow도 제공 (별도 상품)

**위험도**: 🟢 **Low**

---

### 7. JupyterLab

**라이센스**: BSD 3-Clause License  
**Website**: https://jupyter.org/

#### 라이센스 조건
```yaml
허용:
  - ✅ 상업적 사용
  - ✅ 수정
  - ✅ 배포
  - ✅ 비공개 사용
  - ✅ SaaS 제공

요구사항:
  - 📝 라이센스 및 저작권 고지

금지:
  - ❌ 보증 없음 (No Warranty)
  - ❌ 책임 제한 (Limitation of Liability)
```

**위험도**: 🟢 **Low** (매우 허용적)

---

### 8. PostgreSQL

**라이센스**: PostgreSQL License (MIT 스타일)  
**Website**: https://www.postgresql.org/

#### 라이센스 조건
```yaml
# PostgreSQL License (매우 허용적)
허용:
  - ✅ 상업적 사용
  - ✅ 수정
  - ✅ 배포
  - ✅ 비공개 사용
  - ✅ SaaS 제공 (AWS RDS, Google Cloud SQL 등 사용)

요구사항:
  - 📝 저작권 고지 (최소한의 요구사항)
```

**위험도**: 🟢 **Low** (가장 안전)

---

### 9. Redis ⚠️

**라이센스**: **버전에 따라 다름** (중요!)

#### 버전별 라이센스

```yaml
Redis 6.x 이하:
  라이센스: BSD 3-Clause
  상업 사용: ✅ 가능
  SaaS 제공: ✅ 가능
  위험도: 🟢 Low

Redis 7.0 ~ 7.3:
  라이센스: SSPL (Server Side Public License) + RSALv2
  상업 사용: ⚠️ 조건부 (소스 공개 요구)
  SaaS 제공: ⚠️ 위험 (SSPL은 클라우드 제공 제한)
  위험도: 🔴 High

Redis 7.4+:
  라이센스: RSALv2 + SSPLv1 듀얼 라이센스 (단, BSD 3-Clause로 회귀 가능)
  상업 사용: ✅ 가능
  SaaS 제공: ✅ 가능 (Valkey 등 포크 사용)
  위험도: 🟡 Medium
```

#### SSPL(Server Side Public License) 위험성

```yaml
SSPL 문제점:
  - MongoDB, Redis가 클라우드 제공자(AWS, Google) 견제 목적으로 도입
  - SaaS로 제공하는 경우, **전체 인프라 소스 코드 공개 의무**
  - AWS가 Redis SSPL 버전 대신 Valkey(오픈소스 포크) 개발
  - OSI(Open Source Initiative)는 SSPL을 "오픈소스"로 인정하지 않음

예시:
  - DataPond를 SaaS로 제공 시
  - Redis 7.0-7.3 (SSPL) 사용하면
  - → DataPond 전체 코드를 오픈소스로 공개해야 함
  - → 상업적으로 매우 위험
```

#### 권장 조치: Valkey 또는 Redis 6.x 사용

**Option 1: Valkey (권장)**

```yaml
# Valkey: Redis의 오픈소스 포크 (Linux Foundation)
# helm/datapond/values.yaml

redis:
  enabled: false  # Redis 대신 Valkey 사용

valkey:
  enabled: true
  image:
    repository: valkey/valkey
    tag: 7.2.5
  master:
    persistence:
      enabled: true
      size: 8Gi
  replica:
    replicaCount: 2

# 라이센스: BSD 3-Clause (안전)
# 호환성: Redis 프로토콜 100% 호환
# 성능: Redis와 동일
```

**Option 2: Redis 6.x**

```yaml
# Redis 6.x (BSD 3-Clause)
redis:
  image:
    tag: 6.2.14  # 마지막 BSD 라이센스 버전
```

**Option 3: Redis 7.4+ (주의해서 사용)**

```yaml
# Redis 7.4+ (RSALv2 + SSPLv1 듀얼)
# - 개인/사내 사용: 안전
# - SaaS 제공: Valkey 권장
redis:
  image:
    tag: 7.4.0
```

#### 라이센스 위험도 평가

| 시나리오 | Redis 6.x | Redis 7.0-7.3 | Redis 7.4+ | Valkey |
|---------|-----------|---------------|-----------|--------|
| 사내 사용 | ✅ 안전 | ⚠️ 주의 | ✅ 안전 | ✅ 안전 |
| 상업 제품 배포 | ✅ 안전 | ⚠️ 주의 | ✅ 안전 | ✅ 안전 |
| **SaaS 제공** | ✅ 안전 | ❌ 위험 | ⚠️ 주의 | ✅ 안전 |
| 클라우드 판매 | ✅ 안전 | ❌ 불가능 | ⚠️ 주의 | ✅ 안전 |

**권장사항**: 
- 🎯 **SaaS 제공 계획 있음**: Valkey 사용 (BSD 3-Clause)
- 🎯 **사내 사용만**: Redis 7.4+ 또는 Valkey 둘 다 안전
- 🎯 **안전 제일주의**: Valkey (리스크 제로)

**위험도**: 🟡 **Medium** (버전 선택 중요)

---

### 10. LiteLLM

**라이센스**: MIT License  
**GitHub**: https://github.com/BerriAI/litellm

#### 라이센스 조건
```yaml
허용:
  - ✅ 상업적 사용
  - ✅ 수정
  - ✅ 배포
  - ✅ 비공개 사용
  - ✅ SaaS 제공

요구사항:
  - 📝 라이센스 고지 (MIT 전문 포함)

금지:
  - ❌ 보증 없음
```

**특이사항**:
- BerriAI 회사가 개발
- MIT 라이센스 (가장 허용적)
- 상업 지원도 별도 제공 (선택사항)

**위험도**: 🟢 **Low** (매우 안전)

---

### 11. Ollama

**라이센스**: MIT License  
**GitHub**: https://github.com/ollama/ollama

#### 라이센스 조건
- MIT License (LiteLLM과 동일)
- 상업적 사용, SaaS 제공 모두 가능

#### 모델 라이센스 주의사항

```yaml
# Ollama는 MIT이지만, 모델은 별도 라이센스!

Llama 3 (Meta):
  라이센스: Llama 3 Community License
  상업 사용: ✅ 가능 (MAU < 700M인 경우)
  제약:
    - MAU 700M 이상 시 Meta 별도 계약 필요
    - 경쟁 LLM 학습 금지

Mistral:
  라이센스: Apache 2.0
  상업 사용: ✅ 가능 (제약 없음)

Gemma (Google):
  라이센스: Gemma Terms of Use
  상업 사용: ✅ 가능
  제약:
    - 불법/유해 콘텐츠 생성 금지
```

**권장사항**:
- 🎯 **상업 SaaS**: Mistral 또는 Llama 3 (MAU < 700M)
- 🎯 **대규모**: Meta와 별도 계약 또는 Mistral 사용

**위험도**: 🟢 **Low** (Ollama 자체는 안전, 모델 선택 주의)

---

## 📊 라이센스 유형별 정리

### Apache License 2.0 (대부분의 컴포넌트)

```yaml
사용 컴포넌트:
  - SeaweedFS
  - Apache Spark
  - Apache Iceberg
  - Trino
  - Apache Airflow
  - MLflow

특징:
  - ✅ 가장 널리 사용되는 허용적 라이센스
  - ✅ 상업적 사용 제약 없음
  - ✅ SaaS 제공 가능
  - ✅ 소스 공개 의무 없음
  - ✅ 특허 보호 (Patent Grant)

요구사항:
  - 📝 LICENSE 파일 포함
  - 📝 NOTICE 파일 포함 (변경사항 있을 시)
  - 📝 저작권 고지

기업 사용 예시:
  - Netflix (Iceberg)
  - Uber (Spark, Airflow)
  - Airbnb (Airflow)
  - Databricks (MLflow, Spark)
```

### MIT License

```yaml
사용 컴포넌트:
  - LiteLLM
  - Ollama

특징:
  - ✅ 가장 허용적인 라이센스
  - ✅ 상업적 사용 제약 없음
  - ✅ SaaS 제공 가능
  - ✅ 소스 공개 의무 없음

요구사항:
  - 📝 라이센스 전문 포함 (MIT 텍스트)

기업 사용 예시:
  - jQuery, React, Node.js 등 대부분의 웹 기술
```

### BSD 3-Clause License

```yaml
사용 컴포넌트:
  - JupyterLab
  - Valkey (권장 Redis 대체)
  - Redis 6.x

특징:
  - ✅ 매우 허용적 (MIT와 유사)
  - ✅ 상업적 사용 가능
  - ✅ SaaS 제공 가능

요구사항:
  - 📝 저작권 고지
  - 📝 라이센스 전문 포함
  - ❌ 프로젝트 이름으로 홍보 금지 (3번 조항)
```

---

## ⚖️ 라이센스 준수 체크리스트

### 배포 시 필수 포함 사항

```bash
# DataPond 배포 패키지 구조
datapond/
├── README.md
├── LICENSE                    # DataPond 자체 라이센스 (Apache 2.0 권장)
├── NOTICE                     # 모든 오픈소스 컴포넌트 고지
├── licenses/                  # 서드파티 라이센스
│   ├── seaweedfs/
│   │   ├── LICENSE
│   │   └── NOTICE
│   ├── spark/LICENSE
│   ├── iceberg/LICENSE
│   ├── trino/LICENSE
│   ├── airflow/LICENSE
│   ├── mlflow/LICENSE
│   ├── jupyterlab/LICENSE
│   ├── postgresql/LICENSE
│   ├── valkey/LICENSE
│   ├── litellm/LICENSE
│   └── ollama/LICENSE
├── helm/
└── docs/
```

### NOTICE 파일 예시

```text
DataPond
Copyright 2026 DataPond Contributors

This product includes software developed by:

- SeaweedFS (https://github.com/seaweedfs/seaweedfs)
  Copyright 2015-2024 Chris Lu
  Licensed under Apache License 2.0

- Apache Spark (https://spark.apache.org/)
  Copyright 2014-2024 The Apache Software Foundation
  Licensed under Apache License 2.0

- Apache Iceberg (https://iceberg.apache.org/)
  Copyright 2017-2024 The Apache Software Foundation
  Licensed under Apache License 2.0

- Trino (https://trino.io/)
  Copyright 2012-2024 Trino Software Foundation
  Licensed under Apache License 2.0

- Apache Airflow (https://airflow.apache.org/)
  Copyright 2015-2024 The Apache Software Foundation
  Licensed under Apache License 2.0

- MLflow (https://mlflow.org/)
  Copyright 2018-2024 Databricks, Inc.
  Licensed under Apache License 2.0

- JupyterLab (https://jupyter.org/)
  Copyright 2015-2024 Project Jupyter Contributors
  Licensed under BSD 3-Clause License

- PostgreSQL (https://www.postgresql.org/)
  Copyright 1996-2024 PostgreSQL Global Development Group
  Licensed under PostgreSQL License

- Valkey (https://valkey.io/)
  Copyright 2024 Linux Foundation
  Licensed under BSD 3-Clause License

- LiteLLM (https://github.com/BerriAI/litellm)
  Copyright 2023-2024 BerriAI
  Licensed under MIT License

- Ollama (https://github.com/ollama/ollama)
  Copyright 2023-2024 Ollama
  Licensed under MIT License
```

---

## 🚨 라이센스 위반 위험 시나리오

### ❌ 위험한 시나리오

#### 1. Redis 7.0-7.3 (SSPL) 사용 + SaaS 제공
```yaml
문제:
  - SSPL은 SaaS 제공 시 전체 소스 공개 의무
  - DataPond를 클라우드로 판매하면 위반

해결:
  - Valkey 사용 (BSD 3-Clause)
  - 또는 Redis 6.x 사용
```

#### 2. 라이센스 고지 누락
```yaml
문제:
  - LICENSE, NOTICE 파일 없이 배포
  - 저작권 고지 제거

해결:
  - 모든 라이센스 파일 포함
  - NOTICE 파일에 모든 컴포넌트 명시
```

#### 3. Llama 3 모델 MAU 700M 초과
```yaml
문제:
  - Llama 3 Community License 위반

해결:
  - Meta와 별도 계약
  - 또는 Mistral 등 다른 모델 사용
```

### ✅ 안전한 시나리오

#### 1. 사내 사용 (Private Use)
```yaml
# 모든 라이센스가 허용
- 외부 배포 없음
- 직원만 사용
- 라이센스 제약 거의 없음
```

#### 2. 상업 제품 배포 (LICENSE 포함)
```yaml
# Apache 2.0, MIT, BSD 모두 허용
- LICENSE 파일 포함
- NOTICE 파일 포함
- 저작권 고지 유지
```

#### 3. SaaS 제공 (Valkey 사용)
```yaml
# Apache 2.0, MIT, BSD 모두 허용
- Redis 대신 Valkey 사용
- LICENSE, NOTICE 포함
- 소스 공개 의무 없음
```

---

## 🎯 DataPond 프로젝트 권장 라이센스

### DataPond 자체 라이센스 선택

```yaml
권장: Apache License 2.0

이유:
  - ✅ 모든 의존성과 호환 (Apache 2.0, MIT, BSD)
  - ✅ 상업적 사용 허용
  - ✅ 특허 보호 (Patent Grant)
  - ✅ 기업 친화적 (Netflix, Uber, Airbnb 등 사용)
  - ✅ 커뮤니티 신뢰도 높음

대안:
  - MIT License (더 간단, 하지만 특허 보호 없음)
  - BSD 3-Clause (MIT와 유사)
```

### LICENSE 파일 생성

```text
# /home/luke/datapond-k8s/LICENSE

                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   Copyright 2026 DataPond Contributors

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
```

---

## 📋 라이센스 감사 도구

### 자동 라이센스 체크

```bash
# pip-licenses (Python 의존성)
pip install pip-licenses
pip-licenses --format=markdown > docs/PYTHON_LICENSES.md

# license-checker (Node.js 의존성)
npm install -g license-checker
license-checker --json > docs/NPM_LICENSES.json

# Trivy (컨테이너 이미지)
trivy image datapond/backend:latest --list-all-pkgs > docs/IMAGE_LICENSES.txt
```

### 주기적 감사

```yaml
# GitHub Actions: 라이센스 자동 체크
# .github/workflows/license-check.yml

name: License Compliance Check
on: [push, pull_request]

jobs:
  check-licenses:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Check Python licenses
        run: |
          pip install pip-licenses
          pip-licenses --fail-on="GPL;LGPL;AGPL"
      
      - name: Check Node.js licenses
        run: |
          npm install -g license-checker
          license-checker --failOn "GPL;LGPL;AGPL"
      
      - name: Check Docker images
        run: |
          trivy image datapond/backend:latest --severity HIGH,CRITICAL
```

---

## 🎓 Best Practices

### 1. 의존성 추가 시 라이센스 확인

```bash
# 새 패키지 추가 전
pip show <package> | grep License
npm info <package> license
```

### 2. 위험한 라이센스 피하기

```yaml
# 피해야 할 라이센스 (상업적 제약)
피하기:
  - GPL (v2, v3): 소스 공개 의무
  - LGPL: 라이브러리는 안전하지만 주의 필요
  - AGPL: 네트워크 사용도 소스 공개 의무
  - SSPL: SaaS 제공 시 전체 공개 의무
  - Commons Clause: 상업적 판매 금지

안전한 라이센스:
  - Apache 2.0 ✅
  - MIT ✅
  - BSD (2-Clause, 3-Clause) ✅
  - PostgreSQL License ✅
  - ISC ✅
```

### 3. 듀얼 라이센스 주의

```yaml
# 일부 프로젝트는 듀얼 라이센스
예: MySQL
  - GPL (오픈소스)
  - Commercial License (상업용)

DataPond 대응:
  - MySQL 대신 PostgreSQL 사용 (완전 무료)
  - 또는 MariaDB (GPL이지만 더 허용적)
```

---

## 📊 요약

### 라이센스 위험도 종합

| 위험도 | 컴포넌트 | 조치사항 |
|-------|---------|---------|
| 🟢 Low | SeaweedFS, Spark, Iceberg, Trino, Airflow, MLflow, JupyterLab, PostgreSQL, LiteLLM, Ollama | 안심하고 사용 |
| 🟡 Medium | Redis 7.4+ | Valkey로 교체 권장 |
| 🔴 High | Redis 7.0-7.3 (SSPL) | **절대 사용 금지** (SaaS 제공 시) |

### 최종 권장사항

✅ **안전하게 사용 가능**
1. 모든 컴포넌트 Apache 2.0, MIT, BSD 라이센스
2. Redis → Valkey로 교체 (이미 문서에 반영)
3. DataPond 자체는 Apache 2.0 권장
4. LICENSE, NOTICE 파일 포함
5. 상업적 사용, SaaS 제공 모두 가능

⚠️ **주의사항**
1. Llama 3 모델: MAU < 700M 확인
2. 새 의존성 추가 시 라이센스 확인
3. 주기적 라이센스 감사

🎯 **결론**: DataPond는 라이센스 관점에서 **안전하며 상업적으로 자유롭게 사용 가능**합니다.
