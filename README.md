# DataPond — AWS-Native Data Foundation for AI Apps

> **AWS 위에서 RAG·에이전트의 데이터 연료를 공급하는 S3+Bedrock 네이티브 데이터 기반.**
> 거버넌스·카탈로그·실시간은 오픈소스로 차별화.

---

## 🧭 현재 상태: 피보팅 진행 중

DataPond는 **벤더 중립 OSS Databricks 대안**에서 **AWS 특화 AI 데이터 기반**으로
컨셉을 피보팅하고 있습니다.

- 📐 **설계 스펙**: [docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md](docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md)
- 📦 **이전 컨셉(OSS Lakehouse)**: [ARCHIVE.md](ARCHIVE.md) 참조 — `archive/oss-lakehouse` 브랜치 / `v3.0-oss-lakehouse` 태그에 보관

---

## 🎯 새 포지셔닝

| 항목 | 내용 |
|---|---|
| 핵심 가치 | AWS 네이티브 AI 데이터 기반 (RAG·에이전트의 데이터 연료) |
| 타깃 | AWS에서 AI 앱을 만드는 개발팀 / 플랫폼 엔지니어 |
| 모델 | **하이브리드** — AWS 코어(S3·Athena·EMR·Bedrock) + OSS 차별화(Polaris·OpenMetadata·RisingWave·DuckDB) |
| 벡터 스토어 | pgvector(Aurora) 기본 + OpenSearch Serverless 확장 |

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

자세한 컴포넌트 매핑과 실행 단계는 [설계 스펙](docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md)을 참조하세요.

---

## 🗺️ 로드맵

- **Phase 0** — 보관 (이전 컨셉 아카이브) ✅
- **Phase 1** — 컨셉 재정의 (PRODUCT_CONCEPT, README)
- **Phase 2** — 레퍼런스 아키텍처 (IaC, 보안)
- **Phase 3** — MVP (S3 → 임베딩 → 벡터 → Bedrock RAG end-to-end)
- **Phase 4** — GTM 재정렬
