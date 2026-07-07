# DataPond — AWS-Native Data Foundation for AI Apps

> **AWS 위에서 RAG·에이전트의 데이터 연료를 공급하는 S3+Bedrock 네이티브 데이터 기반.**
> 거버넌스·카탈로그·실시간은 오픈소스로 차별화.

---

## 🎯 Overview

**DataPond는 AWS에서 AI 앱(RAG·에이전트)을 프로덕션에 올리려는 팀을 위한 데이터 기반 플랫폼입니다.**

RAG를 PoC에서 프로덕션으로 올릴 때 필요한 배관 — S3 데이터 → 청킹 → 임베딩 → 벡터 적재 →
검색 → Bedrock 응답 — 을 **거버넌스(권한·계보·PII·비용)까지 갖춰 즉시 제공**합니다.
Bedrock Knowledge Bases가 '검색'만 준다면, DataPond는 그 위에 거버넌스·비용 관리·
레이크하우스 통합을 더합니다. 고객의 AWS 계정 안에서 동작하므로 데이터 주권이 유지되고,
차별화 레이어가 오픈소스이므로 락인을 회피합니다.

**타깃**: AWS를 이미 쓰는 조직에서 RAG·에이전트를 프로덕션에 올리려는 **AI 앱 개발팀 / 플랫폼 엔지니어**.
S3 데이터 → 임베딩 → 벡터 검색 → 거버넌스를 직접 조립하기엔 손이 많이 가는 팀.

### 핵심 가치

1. **AI 데이터 파이프라인을 거버넌스까지 완성형으로** — 청크 업서트·재시도·PII 마스킹을 갖춘
   인제스천, pgvector RAG + 리랭크 + 컬렉션 단위 RLS, 카탈로그→Knowledge 브릿지,
   OpenMetadata 계보, 사용자별 비용 귀속·예산 알림. "RAG 데모"가 아니라 **거버넌스 갖춘
   프로덕션 RAG 기반**.
2. **AWS 네이티브 코어로 운영부담 제거** — 스토리지 S3, 쿼리 Athena, 배치 EMR Serverless,
   LLM은 Bedrock(Claude) + LiteLLM 멀티모델 라우팅, 벡터는 pgvector(Aurora) 기본 /
   OpenSearch Serverless 확장.
3. **오픈소스 차별화 레이어로 이식성 확보** — 거버넌스(OpenMetadata)·카탈로그(Polaris)·
   실시간(RisingWave)·로컬 분석(DuckDB)은 OSS 유지. 상품화 가치가 낮은 인프라만 AWS
   매니지드로 교체하는 **하이브리드 원칙**.

### 포지셔닝

| 항목 | 내용 |
|---|---|
| 핵심 가치 | AWS 네이티브 AI 데이터 기반 (RAG·에이전트의 데이터 연료) |
| 타깃 | AWS에서 AI 앱을 만드는 개발팀 / 플랫폼 엔지니어 |
| 경쟁축 | AWS 통합 깊이 + 거버넌스 + 이식성 (가격 아님) |
| 모델 | **하이브리드** — AWS 코어(S3·Athena·EMR·Bedrock) + OSS 차별화(Polaris·OpenMetadata·RisingWave·DuckDB) |
| 주요 경쟁 | Snowflake Cortex · Databricks · AWS DIY 직접 조합 |

> 자세한 컨셉·경쟁 분석·비즈니스 모델: [docs/PRODUCT_CONCEPT.md](docs/PRODUCT_CONCEPT.md) ·
> 설계 스펙: [docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md](docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md)

## 🏗️ 아키텍처 (개요)

```
AI 앱 (RAG / 에이전트)
        │ RAG API
AI 데이터 레이어 ── Bedrock Knowledge Base ─ 벡터 스토어(pgvector/AOSS)
        │                    ▲ 임베딩 파이프라인(Bedrock)
레이크하우스 코어 ── S3 + Iceberg/S3 Tables + Glue · Athena · EMR · RisingWave
        │
거버넌스/관측(OSS) ── OpenMetadata · Polaris · Lake Formation/IAM · DuckDB
```

스토리지는 **네이티브 S3가 기본**(`storage.endpoint: ""` + IAM)이며, 셀프호스티드/개발
환경은 S3 호환 **MinIO**를 사용합니다.

## 🚀 배포 (Quickstart)

```bash
# AWS-native AI Data Foundation (권장 — 5 workloads)
helm upgrade --install datapond helm/datapond -n datapond \
  -f helm/datapond/values-foundation.yaml

# 풀스택 프로파일: values-aws.yaml (EKS+S3+Bedrock) · values-onprem.yaml · values-quicktest.yaml
```

Bedrock 자격증명 설정은 `docs/AWS_BEDROCK_SETUP.md`, 인프라 프로비저닝은 `terraform/README.md` 참조.

---

## 🧭 현재 상태: 피보팅 완료 → 상품화 하드닝 진행 중

DataPond는 **벤더 중립 OSS Databricks 대안**(v3.0)에서 **AWS 특화 AI 데이터 기반**(v4.0)으로
피보팅을 완료했습니다. MVP(S3 → 임베딩 → pgvector → Bedrock RAG)가 main에 머지되어 있고,
현재는 상품화를 위한 보안·운영 하드닝(P0 백로그)을 진행 중입니다.
이전 컨셉은 [ARCHIVE.md](ARCHIVE.md) 참조 — `archive/oss-lakehouse` 브랜치 / `v3.0-oss-lakehouse` 태그에 보관.

### 피보팅 이후 구현된 것 (main 머지 완료)

- **AWS MVP** — S3 → Bedrock 임베딩 → Aurora pgvector → Bedrock RAG end-to-end + Terraform 레퍼런스 IaC (`terraform/`: S3, Aurora, IAM/IRSA) (#100)
- **스토리지 전환** — SeaweedFS → MinIO, AWS-native S3를 base 기본값으로 + `storage.endpoint` 단일화 (#101, #102)
- **LiteLLM ↔ Bedrock 자격증명** — IRSA / static-key / instance-profile 3가지 모드 (#103)
- **린 "AI Data Foundation" Helm 프로파일** — `values-foundation.yaml`, 워크로드 16개 → 5개(backend, frontend, Postgres+pgvector, LiteLLM, Valkey); 무거운 레이크하우스 컴포넌트는 AWS 매니지드로 대체 (#104)
- **UI capability-gating** — `/api/capabilities` + Helm `FEATURE_*` 플래그로 비활성 컴포넌트 페이지 숨김 (#105)
- **시크릿 하드닝 P0-1a/1b** — 크리티컬 시크릿 + 컴포넌트 패스워드 fail-closed, Helm lookup-preserve 생성, pod manifest 평문 제거 (#106, #107)

## 🗺️ 로드맵

- **Phase 0** — 보관 (이전 컨셉 아카이브) ✅
- **Phase 1** — 컨셉 재정의 (PRODUCT_CONCEPT, README) ✅
- **Phase 2** — 레퍼런스 아키텍처 (Terraform IaC ✅, 보안 하드닝 🔄 진행 중)
- **Phase 3** — MVP (S3 → 임베딩 → 벡터 → Bedrock RAG end-to-end) ✅ — [구현 계획](docs/superpowers/plans/2026-06-30-aws-mvp-bedrock-rag.md)
- **Phase 4** — GTM 재정렬

**진행 중인 P0 (상품화 하드닝)**: ~~시크릿/패스워드 하드닝~~ ✅ · LICENSE/서드파티 어트리뷰션 🔄 ·
SSO(SAML/OIDC) 핸들러 · 이미지 태그 고정 · 백업/DR(Aurora) · lakehouse-service IRSA · AWS 라이브 apply+E2E

## 📄 License

DataPond is **Apache-2.0** ([LICENSE](LICENSE)) — everything in this repository except
the [`/ee`](ee/README.md) directory, which is reserved for commercially-licensed
Enterprise features ([ee/LICENSE](ee/LICENSE)). Third-party components and their
licenses are inventoried in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) —
regulated-procurement note included (AGPL/ELv2 components apply only to
onprem/dev profiles).
