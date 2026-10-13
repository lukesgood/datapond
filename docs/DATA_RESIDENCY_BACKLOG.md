# 리전 데이터 상주(data residency) — 보류 항목

> 기록일: 2026-10-13. 상태: **기록만, 미착수.** 재검토 시점: 설계 파트너 확정 후(수요 게이트 2026-10-27 이후).
> 성격: 조사 결과와 검토 항목의 목록이다. 결정·설계·구현은 아직 없다.
> Sovereign Core 관련 항목은 별도 건으로 추후 추가한다.

## 요건 (사용자 지시, 2026-10-13)

- AWS 환경에 집중한다. 교차 리전 처리가 발생하지 않고, 지정된 리전에서만 실행되어 데이터가 설정된 리전을 벗어나지 않는 규제 준수 환경.

## 조사 결과 — 현재 라이브(us-east-1)에서 데이터가 리전을 벗어나는 지점

| # | 경로 | 현재 상태 | 판정 |
|---|---|---|---|
| R1 | Bedrock 생성 모델 `default`/`chat` (`values-prod-single.yaml`, `values-foundation.yaml`, `docs/AWS_BEDROCK_SETUP.md`) | `bedrock/us.anthropic.claude-*` 교차 리전 추론 프로필 | **이탈.** `us.` 프로필은 us-east-1·us-east-2·us-west-2로 라우팅 |
| R2 | Bedrock 임베딩 `embed`, 리랭크 `rerank` | 리전 모델 ID + `aws_region_name` | 리전 내. 단 `amazon.rerank-v1:0`은 us-east-1에 없어 지금도 벡터 순서로 폴백 중(cohere.rerank-v3-5만 존재) |
| R3 | S3·Aurora·Glue/Athena·DLM 스냅샷·Secrets | 단일 리전, 복제·교차 리전 복사 없음 | 리전 내 |
| R4 | 노드 IAM `BedrockInvoke` (`terraform/iam.tf`) | `resources = ["*"]`, 리전 조건 없음 | 차단 장치 없음 |
| R5 | 백엔드 egress 정책 (`AI_EGRESS_POLICY`, `app/api/ai_backends.py`) | `local-only` / `cloud-allowed` 두 모드 | 리전 개념 없음. `cloud-allowed`는 AWS 밖 제공자도 허용 |
| R6 | SES 메일 (`app/email_util.py`), CloudWatch 메트릭 (`app/metrics.py`) | 환경변수 기본값 us-east-1 | 지정 리전과 묶여 있지 않음. 메일 주소는 개인정보 |
| R7 | 백엔드·LiteLLM 로그 | 프롬프트 본문 포함 여부 미확인 | 포함되면 로그도 개인정보, 보관 위치 리전 구속 필요 |
| R8 | 배포 파이프라인 (GitHub 러너 → ECR) | 이미지만 | 고객 데이터 없음 |
| R9 | IAM, Route 53 | 글로벌 서비스 | 구성 메타데이터만, 허용으로 가정 |

## 조사 결과 — Bedrock 리전 내 단일 호출 가능 모델 (2026-10-13, `aws bedrock list-foundation-models`)

| 리전 | 리전 내(ON_DEMAND) | 비고 |
|---|---|---|
| us-east-1 | Titan Embed v2, Nova/Mistral/Llama/Qwen 계열, Cohere Rerank 3.5 | **Claude 전 모델이 추론 프로필 전용** → 리전 고정 시 Claude 생성 불가 |
| ap-northeast-2 | Titan Embed v2, **Claude Sonnet 5, Claude Opus 5**, Claude 3.5 Sonnet, Claude 3 Haiku | 리랭크 모델 없음(벡터 순서 폴백). Haiku 4.5/5.5는 프로필 전용 |

`apac.` 프로필은 도쿄·싱가포르·시드니·뭄바이 등으로, `global.` 프로필은 전 세계 상용 리전으로 라우팅한다. 리전 고정 모드에서는 `us.`/`eu.`/`apac.`/`global.` 접두사 모두 거부 대상.

## 법률·컴플라이언스 검토 항목 (기술 측 분석, 법률 자문 아님 — 법무 확인 필요)

- L1. 개인정보보호법 제28조의8: 국외 제공뿐 아니라 처리위탁·보관도 "이전". 한국 정보주체 개인정보를 미국 리전에 두는 것 자체가 국외 이전이며, 리전 내 고정은 "상주"가 아니라 "적법 근거를 갖춘 이전"이 된다. 적법 근거: 별도 동의 / 법률·조약 / 계약 이행 위탁·보관으로서 처리방침 공개 / 인증 / 보호위원회 적정성 인정.
- L2. 제28조의8 제4항 보호조치(시행령 제29조의10)와 제28조의9 이전 중지 명령 리스크는 고객(개인정보처리자) 몫. 제품은 처리 위치 보장과 증빙을 제공할 뿐 처리방침 기재·AWS DPA는 대신하지 못한다.
- L3. 업종 규제: 금융(전자금융감독규정 — 개인신용정보 처리 시스템 국내 설치, 국외 위탁은 본점·지점·계열사 한정), 공공(CSAP 국내 리전), 의료(전자의무기록 국내 보관). 첫 타깃 세그먼트 기준 컴플라이언스 참조 구성은 서울 리전이어야 한다.
- L4. 교차 리전 추론 프로필은 저장은 원 리전, 처리는 타 리전. 법은 "조회되는 경우를 포함"하므로 처리 위치가 국외이면 이전. 서울에서 `apac.` 사용도 국외 이전.
- L5. 글로벌 서비스(IAM, Route 53)는 메타데이터만 → 허용 가정. SES·로그는 개인정보 포함 가능 → 리전 구속 필요(R6, R7).
- L6. 현재 라이브는 데모 데이터만 있어 위반 상태 아님. 고객 데이터 수용 시점부터 문제.
- L7. 법무 확인 필요: 고객 업종별 적용 규정; 서울 리전이어도 AWS 글로벌 운영 시스템 접근을 국외 이전으로 볼지; CLOUD Act 노출에 대한 고객 입장; 인공지능기본법(2026-01-22 시행)이 상주 요건을 추가하는지.

## 재검토 시 결정할 항목

- D1. 지정 리전: 설정값으로 받되 컴플라이언스 참조 구성·검증 리전을 ap-northeast-2로 할지. us-east-1 라이브는 개발·데모 참조로 남길지, 서울로 이전할지.
- D2. 서울 검증 환경: 별도 EC2(K3s) 한 대. 데모 데이터만 사용하면 라이브 데이터 복사 승인 불필요. 비용 16 GB급 온디맨드 상시 월 약 120–140달러, 평일 주간 스케줄 시 약 40–45달러.
- D3. 작업 분류: egress 정책 제3모드 + IAM + Helm + 문서에 걸치므로 architectural(설계 문서 선행)로 볼지, bounded로 낮출지.

## 재검토 시 후보 작업 (미착수)

- W1. egress 정책 `region-pinned` 모드 + `ai.region` 설정: 등록 시와 호출 시 모두 Bedrock `aws_region_name == 지정 리전`, 모델 ID에 교차 리전 접두사 없음, AWS 밖 제공자 거부.
- W2. Terraform: 노드·IRSA 정책에 `aws:RequestedRegion` 조건(글로벌 서비스 제외), Bedrock 리소스를 리전 내 foundation-model ARN으로 한정.
- W3. SES·CloudWatch·로그 보관 위치를 지정 리전에 구속. 프롬프트 본문 로그 여부 확인.
- W4. 호출별 감사 기록(`tool_call_log`)에 처리 리전 기록 — "이 호출이 서울에서 처리됨"을 건별로 증빙.
- W5. `values-prod-single.yaml`·`values-foundation.yaml`·`docs/AWS_BEDROCK_SETUP.md`의 `us.` 프로필을 리전 설정에 따른 ID로 교체. 서울 기준 `anthropic.claude-sonnet-5`/`anthropic.claude-opus-5`.
- W6. `docs/DATA_RESIDENCY.md`: 데이터를 담는 서비스별 리전 구속, 글로벌 서비스 목록, 검증 명령, 제품 책임과 고객 책임(처리방침·DPA·업종 규제)의 분리.
- W7. 부수 수정: 라이브 `rerank` 모델명이 가리키는 `amazon.rerank-v1:0`은 us-east-1에 없음 — `cohere.rerank-v3-5:0`으로 교체하거나 비활성 명시.
- W8. RFI-260916 내부참조의 요건 항목과 교차 확인(전환 드릴 기록, 실제 IdP 검증 등과 함께).
