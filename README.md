# DataPond — AWS-Native Data Foundation for AI Apps

> **AWS 위에서 RAG·에이전트의 데이터 연료를 공급하는 S3+Bedrock 네이티브 데이터 기반.**
> 거버넌스·카탈로그·실시간은 오픈소스로 차별화.

---

## 🧭 현재 상태: 피보팅 완료 → 상품화 하드닝 진행 중

DataPond는 **벤더 중립 OSS Databricks 대안**(v3.0)에서 **AWS 특화 AI 데이터 기반**으로
피보팅을 완료했습니다. MVP(S3 → 임베딩 → pgvector → Bedrock RAG)가 main에 머지되어 있고,
현재는 상품화를 위한 보안·운영 하드닝(P0 백로그)을 진행 중입니다.

- 🎯 **제품 컨셉**: [docs/PRODUCT_CONCEPT.md](docs/PRODUCT_CONCEPT.md) — 포지셔닝·타깃·경쟁·재활용 자산
- 📐 **설계 스펙**: [docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md](docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md)
- 📦 **이전 컨셉(OSS Lakehouse)**: [ARCHIVE.md](ARCHIVE.md) 참조 — `archive/oss-lakehouse` 브랜치 / `v3.0-oss-lakehouse` 태그에 보관

---

## 🎯 포지셔닝

| 항목 | 내용 |
|---|---|
| 핵심 가치 | AWS 네이티브 AI 데이터 기반 (RAG·에이전트의 데이터 연료) |
| 타깃 | AWS에서 AI 앱을 만드는 개발팀 / 플랫폼 엔지니어 |
| 모델 | **하이브리드** — AWS 코어(S3·Athena·EMR·Bedrock) + OSS 차별화(Polaris·OpenMetadata·RisingWave·DuckDB) |
| 벡터 스토어 | pgvector(Aurora/Postgres) 기본 + OpenSearch Serverless 확장 |

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
환경은 S3 호환 **MinIO**를 사용합니다 (SeaweedFS에서 마이그레이션 완료).
자세한 컴포넌트 매핑과 실행 단계는 [설계 스펙](docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md)을 참조하세요.

## ✅ 피보팅 이후 구현된 것 (main 머지 완료)

- **AWS MVP** — S3 → Bedrock 임베딩 → Aurora pgvector → Bedrock RAG end-to-end + Terraform 레퍼런스 IaC (`terraform/`: S3, Aurora, IAM/IRSA) (#100)
- **스토리지 전환** — SeaweedFS → MinIO, AWS-native S3를 base 기본값으로 + `storage.endpoint` 단일화 (#101, #102)
- **LiteLLM ↔ Bedrock 자격증명** — IRSA / static-key / instance-profile 3가지 모드 (#103)
- **린 "AI Data Foundation" Helm 프로파일** — `values-foundation.yaml`, 워크로드 16개 → 5개(backend, frontend, Postgres+pgvector, LiteLLM, Valkey); 무거운 레이크하우스 컴포넌트는 AWS 매니지드로 대체 (#104)
- **UI capability-gating** — `/api/capabilities` + Helm `FEATURE_*` 플래그로 비활성 컴포넌트 페이지 숨김 (#105)
- **시크릿 fail-closed 하드닝** — production에서 ENCRYPTION_KEY/JWT_SECRET/ADMIN_PASSWORD 미설정 시 기동 거부, Helm lookup 기반 생성·보존 (#106)

## 🚀 배포 (Quickstart)

```bash
# AWS-native AI Data Foundation (권장 — 5 workloads)
helm upgrade --install datapond helm/datapond -n datapond \
  -f helm/datapond/values-foundation.yaml

# 풀스택 프로파일: values-aws.yaml (EKS+S3+Bedrock) · values-onprem.yaml · values-quicktest.yaml
```

Bedrock 자격증명 설정은 `docs/AWS_BEDROCK_SETUP.md`, 인프라 프로비저닝은 `terraform/README.md` 참조.

---

## 🗺️ 로드맵

- **Phase 0** — 보관 (이전 컨셉 아카이브) ✅
- **Phase 1** — 컨셉 재정의 (PRODUCT_CONCEPT, README) ✅
- **Phase 2** — 레퍼런스 아키텍처 (Terraform IaC ✅, 보안 하드닝 🔄 진행 중)
- **Phase 3** — MVP (S3 → 임베딩 → 벡터 → Bedrock RAG end-to-end) ✅ — [구현 계획](docs/superpowers/plans/2026-06-30-aws-mvp-bedrock-rag.md)
- **Phase 4** — GTM 재정렬

**진행 중인 P0 (상품화 하드닝)**: 컴포넌트 패스워드 하드닝 · LICENSE/서드파티 어트리뷰션 ·
SSO(SAML/OIDC) 핸들러 · 이미지 태그 고정 · 백업/DR(Aurora) · lakehouse-service IRSA · AWS 라이브 apply+E2E
