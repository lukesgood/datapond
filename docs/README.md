# DataPond Documentation

이 디렉터리의 현재 제품 문서는 **중소 규모 팀을 위한 AWS 위 가벼운 개방형 레이크하우스**(v7.0, 2026-11-12)를
기준으로 한다. 데이터는 S3 API 저장소의 Apache Iceberg, 테이블 목록은 Iceberg 카탈로그(Glue·Polaris·Iceberg REST),
쿼리는 Trino 하나로 처리하고, 그 위에 소스·동기화·카탈로그 권한·행/열 통제·PII·감사와 AI 활용 계층(검색·인용
답변·자연어 SQL·MCP)이 있다. 결정과 근거는 [POSITIONING_V7.md](POSITIONING_V7.md).

> **최종 갱신: 2026-11-13** (chart 2.7.0). 라이브 AWS 레퍼런스: t3.xlarge Spot 단일 노드, Glue(기본) + Polaris
> 카탈로그, 클러스터 안 Trino, 평일 07:30–18:00 KST 가동. 상태가 걸린 항목(라이브 환경, capability)은 변경 시
> 이 인덱스도 함께 갱신한다.

## 현행 문서 — 제품

| 문서 | 목적 |
|---|---|
| [PRODUCT_CONCEPT.md](PRODUCT_CONCEPT.md) | 대상 사용자, 가치 제안, 제품 경계, 경쟁 기준 (v7.0 — **현행 정본**) |
| [POSITIONING_V7.md](POSITIONING_V7.md) | v6.0→v7.0 결정: 왜 레이크하우스인가, 아직 검증되지 않은 것 (2026-11-12) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 개방 계약별 구조, 카탈로그·엔진, 한 테이블 한 작성자 규칙, add-on |
| [DEPLOYMENT_PROFILES.md](DEPLOYMENT_PROFILES.md) | Helm 프로필별 실제 구성과 선택 기준 |
| [FOUNDATION_PROFILE.md](FOUNDATION_PROFILE.md) | `values-foundation.yaml` — AI 계층만 쓰는 AWS 시작점 |
| [SOVEREIGN_CORE_PROFILE.md](SOVEREIGN_CORE_PROFILE.md) | `values-sovereign-core.yaml` — AI 계층만 쓰는 온프렘 시작점 |
| [PORTABILITY.md](PORTABILITY.md) | 계층별 이식성, 카탈로그 내보내기(Glue → REST), 두 카탈로그 동시 사용 규칙 |
| [MCP.md](MCP.md) | MCP 서버 — 도구 목록, 인증, 감사, 한계 |
| [DEMO_SCRIPT.md](DEMO_SCRIPT.md) | 데모 진행 순서 — 레이크하우스 경로, 그다음 AI 계층 |
| [DESIGN_PARTNER_QUESTIONS.md](DESIGN_PARTNER_QUESTIONS.md) | 디자인 파트너 인터뷰 질문지 — 질문마다 그 답으로 정할 결정 |
| [PERSONA_REVIEW_2026-11.md](PERSONA_REVIEW_2026-11.md) | 라이브 콘솔 페르소나 검증(관리자 화면 + 비관리자 역할 API)과 수정 결과 (2026-11-12–13) |

## 기록 — 특정 시점의 결정·조사 (현재 제품 설명이 아님)

| 문서 | 무엇의 기록인가 |
|---|---|
| [MARKET_REVIEW_2026-10.md](MARKET_REVIEW_2026-10.md) | 시장성 재검토 (2026-10-19). 독립 시장 미검증 판정 — 이후 v7 결정으로 이어짐 |
| [POSITIONING_REVIEW.md](POSITIONING_REVIEW.md) | v5.0→v6.0 결정 (2026-09-07, v7으로 대체) |
| [POSITIONING_FIT_AUDIT.md](POSITIONING_FIT_AUDIT.md) | v6.0 기준 적합도 점검 (2026-09-07) |
| [CONCEPT_RECONFIRMATION.md](CONCEPT_RECONFIRMATION.md) | v6 방향 제안 노트 (2026-07-27) |
| [PRODUCTIZATION_READINESS_ASSESSMENT.md](PRODUCTIZATION_READINESS_ASSESSMENT.md) | 상품화 준비도 평가 (v5–v6 시점) |
| [UTILIZATION_PERSONA_ASSESSMENT.md](UTILIZATION_PERSONA_ASSESSMENT.md) | 페르소나 기반 활용 가능성 평가 (2026-08-31, v6 시점) |
| [ONTOLOGY_FEASIBILITY_REPORT.md](ONTOLOGY_FEASIBILITY_REPORT.md) | 온톨로지 실현가능성 실험 (연구 기록) · 하네스: [research/ontology-poc/](research/ontology-poc/) |
| [ONTOLOGY_GRAPHRAG_REVIEW.md](ONTOLOGY_GRAPHRAG_REVIEW.md) | 온톨로지·GraphRAG 적용 검토 (2026-10-15–16 결정) |
| [DATA_RESIDENCY_BACKLOG.md](DATA_RESIDENCY_BACKLOG.md) | 리전 데이터 상주 보류 항목 (D1) |

## 개발

| 문서 | 목적 |
|---|---|
| [DEVELOPMENT.md](DEVELOPMENT.md) | 로컬 테스트 환경(venv, Python 3.11+, requirements 전부 설치)과 backend/frontend/Helm 검증 명령 |

## 거버넌스·보안

| 문서 | 목적 |
|---|---|
| [RLS_DESIGN.md](RLS_DESIGN.md) | 행 수준 보안·컬럼 마스킹 3계층 설계, 정책 데이터 모델, 적용 범위와 **미적용 경계** |

## 배포 및 운영

| 문서 | 목적 |
|---|---|
| [UPGRADING.md](UPGRADING.md) | 기존 배포의 동작이 바뀌는 변경과 운영자 조치 사항 |
| [DEPLOY_SINGLE_NODE.md](DEPLOY_SINGLE_NODE.md) | 현재 AWS EC2/K3s 레퍼런스 배포 절차 (Polaris 병행 §7a, 인스턴스 타입 변경 §7b) |
| [OPERATIONS_PAUSE.md](OPERATIONS_PAUSE.md) | 라이브 환경 정지/재시작 런북 · **현재 상태: 평일 07:30–18:00 KST 가동 (t3.xlarge Spot, chart 2.7.0)** |
| [AWS_MVP_RUNBOOK.md](AWS_MVP_RUNBOOK.md) | AWS RAG 경로 acceptance/smoke test |
| [AWS_BEDROCK_SETUP.md](AWS_BEDROCK_SETUP.md) | Bedrock provider credential/model 설정 |
| [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) | Aurora/S3/critical secret 복구 절차 |
| [../terraform/README.md](../terraform/README.md) | 실제 Terraform 리소스와 적용 절차 |

## Capability 상태

| Capability | 모든 프로필 | 프로필 선택 | Roadmap |
|---|---:|---:|---:|
| Knowledge/RAG, pgvector, citations, MCP (read 30개) | ✅ | | |
| PII, collection ACL, 감사, 호출자별 AI spend | ✅ | | |
| 인증 — 로컬 계정, passkey/WebAuthn | ✅ (passkey는 HTTPS 도메인 구성 시) | | |
| 인증 — LDAP/AD | | ✅ `LDAP_ENABLED`, 기본 off | |
| 인증 — OIDC SSO | | ✅ Enterprise 이미지(`/ee`) **＋** `OIDC_ENABLED` | SAML 미구현 |
| Trino 쿼리 엔진 (카탈로그가 있는 모든 프로필), 워커 `trino.workers.replicas` | | ✅ | 워커 자동 확장 |
| 레이크 카탈로그 여러 개(Glue·Polaris·Iceberg REST), 카탈로그별 권한 | | ✅ AWS single-node · OSS extended | |
| DB 소스 = Trino 카탈로그 `src_<slug>` (PostgreSQL·MySQL·SQL Server·Oracle·MongoDB), 동기화 대상 카탈로그 선택 | | ✅ Trino 프로필 | |
| 카탈로그 내보내기(복사 없이 등록), 한 테이블 한 작성자(사본 보호·최신화) | | ✅ `catalog:write`(관리자·데이터 엔지니어) | |
| RLS 엔진 (행 필터·컬럼 마스킹) | | ✅ `governance.rls.enabled` | |
| S3/Bedrock adapter | ✅ AWS 프로필 · MinIO/Ollama in Sovereign | | |
| Aurora/Glue adapter, Polaris 병행 | | ✅ AWS single-node | |
| RisingWave/OpenMetadata/Airflow/Spark/Jupyter/MLflow | | ✅ Optional add-on | |
| 온톨로지 concept store (Phase 0) | | ✅ opt-in, 기본 off (`ontology.enabled`) | Phase 1+ 보류 |
| EKS installer, EMR Serverless, S3 Tables, Lake Formation, AOSS, DataZone, Marketplace | | | 🛣️ |
| Delta → Iceberg 이관, 통합 export/import CLI, 자동 exit drill | | | 🛣️ |

`enabled`는 구성 상태이지 서비스 health를 의미하지 않는다. 실제 상태는 Services/System에서 확인한다. 비활성 OSS 구성요소는 AWS 서비스로 자동 대체되지 않는다. 런타임 실제 값은 `GET /api/capabilities`가 정본이며, 위 표는 그 플래그가 어느 프로필에서 켜지는지를 설명한다.

## 문서 상태 규칙

- 루트 README와 위 목록의 문서가 현재 제품 설명의 기준이다.
- `docs/superpowers/plans/`와 `docs/superpowers/specs/`는 특정 시점의 설계·구현 이력이다.
- 역사 문서에 EKS, Marketplace, DataZone 등의 목표가 있어도 현재 구현을 의미하지 않는다.
- 새 기능은 코드, Helm wiring, 테스트, 해당 프로필 acceptance가 모두 확인된 뒤 Shipped로 승격한다.
- 코드 주석이 참조하는 설계 문서는 이 디렉터리에 실재해야 한다. 참조만 남고 문서가 없으면 둘 중 하나를 고친다.

## 관련 문서

- 이전 v3 OSS lakehouse 컨셉: [../ARCHIVE.md](../ARCHIVE.md)
- Enterprise 경계: [../ee/README.md](../ee/README.md)
- Third-party license: [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
