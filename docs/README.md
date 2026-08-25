# DataPond Documentation

이 디렉터리의 현재 제품 문서는 **Portable AI Data Foundation**을 기준으로 한다. DataPond의 제품 경계는 governed RAG 애플리케이션 코어이며, AWS와 OSS 데이터 서비스는 프로필에 따라 선택되는 어댑터·add-on이다.

> **최종 갱신: 2026-08-24.** 아래 capability 표와 라이브 환경 상태는 이 날짜 기준이다. 상태가 걸린 항목(라이브 환경, capability)은 변경 시 이 인덱스도 함께 갱신한다.

## 먼저 읽을 문서

| 문서 | 목적 |
|---|---|
| [PRODUCT_CONCEPT.md](PRODUCT_CONCEPT.md) | 대상 사용자, 가치 제안, 제품 경계, 경쟁 기준 (v5.0 — **현행 정본**) |
| [PRODUCTIZATION_READINESS_ASSESSMENT.md](PRODUCTIZATION_READINESS_ASSESSMENT.md) | 현재 구현의 상품화 준비도, 출시 차단 요소, 개선 로드맵 |
| [CONCEPT_RECONFIRMATION.md](CONCEPT_RECONFIRMATION.md) | v6 방향 **제안** 노트 (에이전트 governed 데이터 접근 계층 · 수요 게이트). v5.0을 대체하지 않으며, 수요 게이트 통과 후에야 정식 개정으로 승격된다 |
| [ONTOLOGY_FEASIBILITY_REPORT.md](ONTOLOGY_FEASIBILITY_REPORT.md) | 온톨로지 실현가능성·가치 5개 실험 검증 리포트 (연구 기록) · 실험 하네스: [research/ontology-poc/](research/ontology-poc/) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Portable Core, 어댑터 계약, optional add-on 구조 |
| [DEPLOYMENT_PROFILES.md](DEPLOYMENT_PROFILES.md) | Helm 프로필별 실제 구성과 선택 기준 |
| [FOUNDATION_PROFILE.md](FOUNDATION_PROFILE.md) | `values-foundation.yaml` Portable Core · AWS starter 상세 |
| [PORTABILITY.md](PORTABILITY.md) | 데이터·모델·배포 이식성과 출구 전략 |

## 거버넌스·보안

| 문서 | 목적 |
|---|---|
| [RLS_DESIGN.md](RLS_DESIGN.md) | 행 수준 보안·컬럼 마스킹 3계층 설계, 정책 데이터 모델, 적용 범위와 **미적용 경계** |

## 배포 및 운영

| 문서 | 목적 |
|---|---|
| [UPGRADING.md](UPGRADING.md) | 기존 배포의 동작이 바뀌는 변경과 운영자 조치 사항 |
| [DEPLOY_SINGLE_NODE.md](DEPLOY_SINGLE_NODE.md) | 현재 AWS EC2/K3s 레퍼런스 배포 절차 |
| [OPERATIONS_PAUSE.md](OPERATIONS_PAUSE.md) | 라이브 환경 정지/재시작 런북 · **현재 상태: 가동 중 (2026-08-24 기동, Helm rev 59)** |
| [AWS_MVP_RUNBOOK.md](AWS_MVP_RUNBOOK.md) | AWS RAG 경로 acceptance/smoke test |
| [AWS_BEDROCK_SETUP.md](AWS_BEDROCK_SETUP.md) | Bedrock provider credential/model 설정 |
| [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) | Aurora/S3/critical secret 복구 절차 |
| [../terraform/README.md](../terraform/README.md) | 실제 Terraform 리소스와 적용 절차 |

## Capability 상태

| Capability | Portable Core | 프로필 선택 | Roadmap |
|---|---:|---:|---:|
| Knowledge/RAG, pgvector, citations | ✅ | | |
| PII, collection ACL, audit, AI spend | ✅ | | |
| 인증 — 로컬 계정 | ✅ | | |
| 인증 — passkey/WebAuthn | ✅ (HTTPS 도메인 구성 시 자동 활성) | | |
| 인증 — LDAP/AD | | ✅ `LDAP_ENABLED`, 기본 off | |
| 인증 — OIDC SSO | | ✅ Enterprise 이미지(`/ee`) **＋** `OIDC_ENABLED` | SAML 미구현 |
| RLS 엔진 (행 필터·컬럼 마스킹) | | ✅ `governance.rls.enabled` | |
| S3/Bedrock adapter | ✅ AWS starter | | |
| Aurora/Glue/Athena adapter | | ✅ AWS single-node | |
| Polaris/Trino | | ✅ OSS extended | |
| RisingWave/OpenMetadata/Airflow/Spark/Jupyter/MLflow | | ✅ Optional add-on | |
| 온톨로지 concept store (Phase 0 슬라이스) | | ✅ opt-in, 기본 off (`ontology.enabled`) | Phase 1+ 는 수요 게이트 대기 |
| EKS installer, EMR Serverless, S3 Tables, Lake Formation, AOSS, DataZone, Marketplace | | | 🛣️ |
| 통합 export/import CLI 및 자동 exit drill | | | 🛣️ |

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
