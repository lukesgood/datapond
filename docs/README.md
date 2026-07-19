# DataPond Documentation

이 디렉터리의 현재 제품 문서는 **Portable AI Data Foundation**을 기준으로 한다. DataPond의 제품 경계는 governed RAG 애플리케이션 코어이며, AWS와 OSS 데이터 서비스는 프로필에 따라 선택되는 어댑터·add-on이다.

## 먼저 읽을 문서

| 문서 | 목적 |
|---|---|
| [PRODUCT_CONCEPT.md](PRODUCT_CONCEPT.md) | 대상 사용자, 가치 제안, 제품 경계, 경쟁 기준 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Portable Core, 어댑터 계약, optional add-on 구조 |
| [DEPLOYMENT_PROFILES.md](DEPLOYMENT_PROFILES.md) | Helm 프로필별 실제 구성과 선택 기준 |
| [FOUNDATION_PROFILE.md](FOUNDATION_PROFILE.md) | `values-foundation.yaml` Portable Core · AWS starter 상세 |
| [PORTABILITY.md](PORTABILITY.md) | 데이터·모델·배포 이식성과 출구 전략 |

## 배포 및 운영

| 문서 | 상태 |
|---|---|
| [DEPLOY_SINGLE_NODE.md](DEPLOY_SINGLE_NODE.md) | 현재 AWS EC2/K3s 레퍼런스 배포 절차 |
| [AWS_MVP_RUNBOOK.md](AWS_MVP_RUNBOOK.md) | AWS RAG 경로 acceptance/smoke test |
| [AWS_BEDROCK_SETUP.md](AWS_BEDROCK_SETUP.md) | Bedrock provider credential/model 설정 |
| [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) | Aurora/S3/critical secret 복구 절차 |
| [../terraform/README.md](../terraform/README.md) | 실제 Terraform 리소스와 적용 절차 |

## Capability 상태

| Capability | Portable Core | 프로필 선택 | Roadmap |
|---|---:|---:|---:|
| Knowledge/RAG, pgvector, citations | ✅ | | |
| PII, collection ACL, audit, AI spend | ✅ | | |
| S3/Bedrock adapter | ✅ AWS starter | | |
| Aurora/Glue/Athena adapter | | ✅ AWS single-node | |
| Polaris/Trino | | ✅ OSS extended | |
| RisingWave/OpenMetadata/Airflow/Jupyter/MLflow | | ✅ Optional add-on | |
| EKS installer, EMR Serverless, S3 Tables, Lake Formation, AOSS, DataZone, Marketplace | | | 🛣️ |
| 통합 export/import CLI 및 자동 exit drill | | | 🛣️ |

`enabled`는 구성 상태이지 서비스 health를 의미하지 않는다. 실제 상태는 Services/System에서 확인한다. 비활성 OSS 구성요소는 AWS 서비스로 자동 대체되지 않는다.

## 문서 상태 규칙

- 루트 README와 위 목록의 문서가 현재 제품 설명의 기준이다.
- `docs/superpowers/plans/`와 `docs/superpowers/specs/`는 특정 시점의 설계·구현 이력이다.
- 역사 문서에 EKS, Marketplace, DataZone 등의 목표가 있어도 현재 구현을 의미하지 않는다.
- 새 기능은 코드, Helm wiring, 테스트, 해당 프로필 acceptance가 모두 확인된 뒤 Shipped로 승격한다.

## 관련 문서

- 이전 v3 OSS lakehouse 컨셉: [../ARCHIVE.md](../ARCHIVE.md)
- Enterprise 경계: [../ee/README.md](../ee/README.md)
- Third-party license: [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
