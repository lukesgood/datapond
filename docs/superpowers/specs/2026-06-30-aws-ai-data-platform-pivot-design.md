# DataPond 피보팅 설계: AWS-Native Data Foundation for AI Apps

**작성일**: 2026-06-30
**상태**: 설계 확정 (구현 전)
**대체 대상**: `docs/PRODUCT_CONCEPT.md` (v3.0 OSS Lakehouse 컨셉) → 아카이브 예정
**목적**: 벤더 중립 OSS Databricks 대안에서 **AWS 특화 AI 데이터 기반**으로 컨셉 피보팅

---

## 1. 결정 요약 (Decisions)

브레인스토밍에서 확정된 핵심 결정:

| 결정 항목 | 선택 | 비고 |
|---|---|---|
| AWS 특화 수준 | **하이브리드** (AWS 코어 교체 + OSS 차별화 유지) | 완전 매니지드 대체도, OSS 고수도 아님 |
| AI 무게중심 | **AI 애플리케이션을 위한 데이터 기반** | RAG·에이전트의 데이터 연료 공급 |
| 보관 방식 | **Git 태그 + 아카이브 브랜치 + `archive/` 디렉토리** 병행 | 이력 고정 + 한 레포 내 열람 |
| 벡터 스토어 | **pgvector(Aurora) 기본 + OpenSearch Serverless 확장** | 플러그형 추상화, 둘 다 Bedrock KB 지원 |
| 차별화 레이어 | **유지** — Polaris, OpenMetadata, RisingWave, DuckDB | AWS 코어 위에 OSS 차별화 |

---

## 2. 새 포지셔닝

> **"AWS 위에서 RAG·에이전트의 데이터 연료를 공급하는 S3+Bedrock 네이티브 데이터 기반 — 거버넌스·카탈로그·실시간은 오픈소스로 차별화."**

| 항목 | Before (현재 v3.0) | After (피보팅) |
|---|---|---|
| 핵심 가치 | 벤더 중립, 1/10 비용 OSS Databricks 대안 | AWS 네이티브 AI 데이터 기반 |
| 타깃 | 비용 민감 데이터팀 | AWS에서 **AI 앱(RAG/에이전트) 만드는 팀** + 플랫폼팀 |
| 주요 경쟁 | Databricks | Snowflake Cortex, Databricks, **AWS DIY 직접 조합** |
| 차별화 | 가격 | AWS 통합 깊이 + OSS 거버넌스/카탈로그/실시간 + 이식성 |

**타깃 페르소나 (1차)**: AWS를 이미 쓰는 중소~중견 조직의 **AI 앱 개발팀 / 플랫폼 엔지니어**.
RAG·에이전트를 프로덕션에 올리려는데, S3 데이터 → 임베딩 → 벡터 검색 → 거버넌스를
직접 조립하기엔 손이 많이 가는 팀.

---

## 3. 컴포넌트 매핑 (하이브리드)

**원칙**: 상품화 가치가 낮은 인프라(스토리지·쿼리·LLM)는 AWS 매니지드로 교체해 운영부담을 없애고,
차별화가 되는 레이어(거버넌스·카탈로그·실시간·로컬 분석)는 OSS로 유지해 락인 회피·이식성을 셀링포인트로 삼는다.

| 레이어 | 현재 OSS | → 하이브리드 | 분류 |
|---|---|---|---|
| 스토리지 | SeaweedFS | **Amazon S3** | AWS 코어 |
| 테이블/카탈로그 | Polaris/Iceberg | **S3 Tables + Glue Catalog** 기본, **Polaris(Iceberg REST)** 차별화 옵션 | 혼합 |
| 쿼리 | Trino | **Athena**(서버리스) 기본, Trino 옵션 | AWS 코어 |
| 배치 | Spark | **EMR Serverless / Glue** | AWS 코어 |
| LLM | LiteLLM | **Amazon Bedrock**(Claude) 기본 + **LiteLLM 멀티모델 라우팅** | 혼합 |
| **AI 데이터 (신규 핵심)** | — | **임베딩 파이프라인(Bedrock) → 벡터 스토어(pgvector 기본/AOSS 확장) → Bedrock Knowledge Base → RAG API** + 피처스토어 | 신규 |
| 거버넌스/Lineage | OpenMetadata + Polaris RBAC | **유지(차별화)** + Lake Formation/IAM 연동 | OSS 차별화 |
| 실시간 | RisingWave | **유지(차별화)** + Kinesis 연동 | OSS 차별화 |
| 노트북/로컬분석 | JupyterLab + DuckDB | **유지(차별화)** — DuckDB로 S3 직접 쿼리 | OSS 차별화 |
| 배포 | K8s/Helm | **EKS + Terraform/CDK + AWS Marketplace** | AWS 코어 |

---

## 4. 벡터 스토어 전략 (2-tier)

**기본값: pgvector on Aurora PostgreSQL (Serverless v2)** / **확장: OpenSearch Serverless (AOSS)**.
두 백엔드를 **플러그형으로 추상화**한다 (Bedrock Knowledge Bases가 둘 다 공식 지원).

| 기준 | pgvector (기본) | AOSS (확장) |
|---|---|---|
| 적합 규모 | ~수천만 벡터 | 수억~수십억 벡터 |
| 하이브리드 검색 | WHERE 필터 + 벡터 (렉시컬 약함) | BM25 + 시맨틱 내장 |
| 비용 | 0~저 ACU로 축소, 소규모 저렴 | 최소 과금 존재, 소규모 부담 |
| 운영 | 기존 Postgres에 흡수 (시스템 1개 절감) | 완전 매니지드, 별도 스택 |
| 이식성 | OSS → 타클라우드/온프렘 이식 가능 | AWS 종속 강함 |

**선택 근거**: 스택 일관성(이미 Postgres 보유), 비용 곡선(소규모 친화), 피보팅 테제와 정합(OSS·이식성),
"작게 시작 → 필요 시 AOSS 승급" 확장 경로가 그대로 셀링 포인트.
*(향후 콜드 벡터 아카이브 계층으로 S3 Vectors 추가 검토)*

---

## 5. 레퍼런스 아키텍처 (개요)

```
                 ┌─────────────────────────────────────────────┐
                 │            AI 앱 (RAG / 에이전트)             │
                 └───────────────────┬─────────────────────────┘
                                     │ RAG API
        ┌────────────────────────────┼────────────────────────────┐
        │  AI 데이터 레이어 (신규 핵심)                            │
        │  Bedrock Knowledge Base ── 벡터 스토어                   │
        │       ▲                     (pgvector 기본 / AOSS 확장)  │
        │  임베딩 파이프라인 (Bedrock Embeddings)                  │
        └────────────────────────────┼────────────────────────────┘
                                     │
   ┌─────────────────────────────────┼─────────────────────────────────┐
   │  레이크하우스 코어                                                  │
   │  S3 (스토리지) + Iceberg/S3 Tables + Glue Catalog                  │
   │  Athena(쿼리) · EMR Serverless(배치) · RisingWave(실시간)          │
   └─────────────────────────────────┼─────────────────────────────────┘
                                     │
   ┌─────────────────────────────────┼─────────────────────────────────┐
   │  거버넌스/관측 (OSS 차별화)                                         │
   │  OpenMetadata(카탈로그·Lineage) · Polaris(Iceberg REST·RBAC)       │
   │  Lake Formation/IAM 연동 · DuckDB(로컬 탐색)                       │
   └────────────────────────────────────────────────────────────────────┘

   배포: EKS + Terraform/CDK + AWS Marketplace
   보안: IAM, Lake Formation, VPC
```

---

## 6. 실행 단계

### Phase 0 — 보관 (반나절)
- `v3.0-oss-lakehouse` Git 태그 생성·푸시
- `archive/oss-lakehouse` 브랜치 생성·푸시
- 현재 컨셉/문서를 레포 내 `archive/` 디렉토리로 이동
- `ARCHIVE.md`: 이전 컨셉 요약 + 복귀 방법(태그/브랜치 체크아웃) 기록

### Phase 1 — 컨셉 재정의 (문서)
- 새 `docs/PRODUCT_CONCEPT.md`: 포지셔닝·타깃·경쟁·컴포넌트 매핑·차별화
- `README.md` 교체 (새 포지셔닝/아키텍처/Quickstart)

### Phase 2 — 레퍼런스 아키텍처
- S3 + Iceberg/S3 Tables + Glue 레이크하우스 정의
- AI 데이터 레이어 상세: 임베딩 → 벡터(pgvector/AOSS 추상화) → Bedrock KB → RAG API
- IaC: Terraform 또는 CDK 스캐폴드, EKS 상의 OSS 컴포넌트 배치
- 보안: IAM 역할, Lake Formation 권한, VPC 설계

### Phase 3 — MVP (thin slice)
- end-to-end 1개 경로 구현: **S3 데이터 → 임베딩 → 벡터 스토어(pgvector) → Bedrock RAG 데모**
- 그 위에 거버넌스/카탈로그(OpenMetadata) 통합

### Phase 4 — GTM 재정렬
- README/홈페이지 메시지 교체, AWS Marketplace 리스팅 준비
- 데모 환경, 콘텐츠(블로그/튜토리얼)

---

## 7. 범위 밖 (Out of Scope, YAGNI)
- 멀티클라우드 동시 지원 (AWS 특화가 핵심이므로 의도적 제외; 이식성은 OSS 컴포넌트 수준에서만 보장)
- AOSS를 초기 기본값으로 채택 (확장 옵션으로만)
- S3 Vectors 즉시 도입 (향후 검토)

## 8. 미해결/추후 결정
- IaC 도구: Terraform vs CDK (Phase 2에서 확정)
- Glue Catalog 단독 vs Polaris 병행의 구체 경계
- Marketplace 형태: AMI/Helm vs SaaS 리스팅
