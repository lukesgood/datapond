# 시장성 재검토 — 2026-10-19

2026-10-19 세션에서 오너와 진행한 메뉴·기능 점검과 시장성 검토를 한 곳에 남긴다. 판정과 권장은
작성 시점의 책상 조사(웹 검색, 코드 점검)에 근거하며, 고객·파트너 인터뷰로 검증되지 않았다.
정본 포지셔닝 문서(`PRODUCT_CONCEPT.md` v6.0, `POSITIONING_REVIEW.md`)는 이 문서로 바뀌지 않았다.

## 0. 요약

| 검토한 방향 | 판정 |
|---|---|
| 에이전트용 governed 데이터 도구 서버 (v6, 현재 정본) | 수요 증거 없음. 10/27 게이트 검증 전 |
| AWS 상의 AI 데이터 플랫폼 | 일부 역할(데이터 접근 거버넌스 계층)만 가능. 플랫폼 전체는 아님 |
| Databricks 대체 경량 데이터레이크 (오너가 밝힌 목적) | 대체재가 강하고 고객이 좁아짐. 스타트업은 맞지 않음 |
| 에어갭·통제된 대외망용 AI RAG·GraphRAG·온톨로지 데이터 솔루션 | 수요는 있으나 레드오션. 들어갈 수 있는 층(거버넌스 계층)은 작음 |

세 방향 모두 "제품이 무엇을 할 수 있는가"에서 출발해 "경쟁이 강하거나 시장이 작다"에 닿았다.
남은 질문은 제품이 아니라 **이 팀·회사가 남보다 쉽게 할 수 있는 것**(기존 MSP 고객, 청구 데이터,
관리 계약, AWS 파트너 지위)이다. 권장은 §8.

## 1. 이번 세션에서 출시한 것 (라이브 반영)

| PR | 내용 |
|---|---|
| #242 | Caller budgets가 UUID 대신 계정 이름을 표시. "virtual keys" 잔여 문구 제거 |
| #243 | Help → Integrate 5단계가 에이전트 페이지를 가리킴. Account 부제 정정 |
| #244 | 메뉴 이름 정정(Agents, Analytics). DEMO_SCRIPT d단계를 에이전트 페이지로 |
| #245 | 표시되는 한도 = 강제되는 한도. 게이트웨이는 $0 한도를 저장하지 않아 "no cap"으로 보였음 |
| #246 | Governance → Tool calls 탭(전체 호출자). "Audit Log"는 "Query log"로 |

데모 리허설(`scripts/demo_rehearsal.py`)은 라이브에서 전 단계 통과. DEMO_SCRIPT 1·a~e 단계를 콘솔로
따라가며 확인했고, 그 과정에서 #245·#246의 문제를 찾았다.

## 2. 메뉴 구성 재검토 (미착수)

현재: Overview / Build AI(Knowledge) / Data(Sources·Catalog·Metrics·Analytics) / Data Science(Experiments) /
Operate(Agents·AI Gateway·Governance·Storage·Infrastructure·Settings) / Help·Account.

1. **설정 화면이 없는 거버넌스 기능** — 호출자별 PII 모드(`users.pii_mode`)와 컬렉션 민감도 라벨
   (`collections.sensitivity`: public/internal/confidential/restricted)은 적용되지만 API·UI가 없다.
   DB에 SQL로만 설정 가능. `restricted`는 로컬 모델만 쓰도록 강제된다(`app/sensitivity.py`).
2. **Settings 중복** — Overview 탭이 Infrastructure와 겹침. Users 탭에 서비스 계정이 사람과 섞임.
   "My Profile"이 `/account`와 중복.
3. **Governance 탭 7개** — Query log가 Activity의 Query 출처와 같은 데이터.
4. **그룹 이름** — "Build AI"에 항목 하나. 제안: Tools(Knowledge·Metrics·Analytics) / Data(Sources·Catalog) /
   Govern(Agents·Governance·AI Gateway) / Operate(Storage·Infrastructure·Settings).
5. 작은 것 — Infrastructure 상단 숫자 중복, AI Gateway 제목 중복.

## 3. Build AI에 필요한 기능 (제안, 미착수)

1. **Tool playground** — 에이전트 하나를 골라 그 권한·청크 규칙·마스킹·예산 그대로 도구를 실행하고
   withheld·masked·거부 사유를 보여준다. 지금은 키를 발급해 curl로만 확인 가능.
2. **검색 평가 세트** — 컬렉션별 질문·기대 출처, hit@k, 실행 이력. Compare 탭은 비교만 하고 측정하지 않는다.
3. **도구 목록** — 키별 `tools/list`와 스키마·필요 범위. Playground 안에 넣으면 충분.

하지 않을 것: 에이전트 빌더·프롬프트 편집, 에이전트 레지스트리·도구 정책 엔진, 채팅 앱 생성기.

## 4. AWS에서 AI 워크로드용 데이터 플랫폼이 될 수 있는가

| 역할 | 판정 |
|---|---|
| 에이전트·앱의 데이터 접근 거버넌스 | 된다. 핵심이며 AWS가 하지 않는 부분 |
| RAG 서빙 | 된다. PDF·hybrid는 약함 (Bedrock KB가 강함) |
| 정형 질의 도구(메트릭, governed SQL) | 된다 (Glue/Athena 읽기) |
| 모델 경계·호출자별 비용 | 된다 |
| 데이터 레이크·ETL·스트리밍, 학습·피처, 전사 카탈로그, 에이전트 런타임 | 안 된다 |

걸리는 점: 단일 EC2/K3s(HA·EKS 없음), Lake Formation 미연동, PII 설정 UI 없음, 온프렘 강점은 Sovereign 보류로 미사용.

## 5. Databricks 대체 검토

오너가 밝힌 목적(2026-10-19): *Databricks를 쓰는 고객사 중 규모가 크지 않고 AWS를 적극 사용하는
고객사에게 light weight한 datalake 환경을 플랫폼 형태로 제공.* v6 정본과 대상·범위가 다르다.

- "Databricks 없이 AWS에서 구동"은 지금도 된다. "Databricks 대체"는 레이크하우스 전체 재구현이다.
- v3.0 OSS 레이크하우스(자체 호스팅 Spark·Trino·Airflow 등)는 이미 시도 후 보관했다(`archive/oss-lakehouse`).
- 경량이 되려면 엔진을 직접 돌리지 않고 AWS 서버리스(Athena, Glue, S3 Tables, EMR Serverless) 위의
  작업 공간이어야 한다.
- 직접 경쟁자는 Databricks보다 SageMaker Unified Studio(같은 서비스 위의 무료에 가까운 UI)다.

| Databricks 기능 | DataPond 현재 |
|---|---|
| Delta on S3 | 없음 (S3 Tables 로드맵) |
| SQL·대시보드 | 있음 |
| Jobs(Spark ETL) | AWS 기준 없음 (자체 호스팅 애드온만) |
| 노트북 | 부분 (Jupyter 애드온) |
| Unity Catalog | 부분 (카탈로그·RLS·마스킹·카탈로그 권한, Lake Formation 없음) |
| MLflow | 있음 (애드온) |
| AI(Vector Search·Genie) | 강점 |
| 이전 도구 | 없음 |

## 6. 고객 페르소나

### 6.1 1차 분석

| 페르소나 | 판정 | 이유 |
|---|---|---|
| P1 시리즈 A~B 스타트업 | ✗ | 크레딧 소진 후 비용 문제는 Databricks 안에서 해결 가능, SaaS 선호, 지불 의향 낮음 |
| P2 중소·중견(AWS 이관 완료, MSP 관리) | ◎ | 비용 예측·인력 부족·AI 심사 반려가 실제 불편. 단 MSP 채널이 조건 |
| P3 AI 네이티브 스타트업 | △ | 레이크하우스가 아니라 AI 거버넌스 계층 고객 (v6 대상) |
| P4 데이터 성숙 스케일업 | ✗ | 이전 비용 > 이익 |

드러난 두 가지: (1) 가장 맞는 고객은 MSP를 끼고 AWS를 쓰는 중견기업. (2) 실제 경쟁자는 MSP의
Athena/Glue 직접 조립과 현상 유지 — 차별점은 비용보다 하나의 화면·한국어·AI 거버넌스·운영 부담 없음.

### 6.2 재정의

- **대상 고객사**: AWS 이관 완료·MSP 관리 중견기업. 직원 300~1,000, AWS 월 $1만~5만, 데이터 수백 GB~10 TB,
  데이터 인력 1~4명. A형(Databricks 소규모 사용, 예산이 있다는 신호) 우선, B형(MSP 조립 Athena/Glue) 포함.
- **의사결정자**: IT팀장(비용·인력·종속), 데이터 담당(이전 수고), AI 추진 담당(심사 지연), 정보보호 책임자
  (증거·PII), 현업(숫자 신뢰). 레이크하우스는 구매 조건, AI 거버넌스는 이기는 이유.
- **채널**: MSP 솔루션 아키텍트·영업. 고객마다 다시 조립하던 일을 표준 구성으로 바꾸는 가치.
- **제외**: 스케일업, 시리즈 A~B 스타트업, 규제 업종 첫 파트너, 멀티 리전 필수.
- **제품 우선순위(이 경로를 택할 경우)**: 원클릭 설치(CloudFormation·Marketplace) → Databricks 이전 MVP →
  비용 비교 화면 → PII 설정 UI → Tool playground.

## 7. 시장성 판단

### 7.1 독립 제품으로서 — 약하거나 미입증

수요 직접 증거 없음, 분석할수록 대상이 좁아짐, 대체재가 강하고 쌈, 필요한 기능 공백이 큼,
2026-06 이후 포지셔닝 다섯 번 변경. 단, "증거가 약하다"는 "시장이 약하다"와 같지 않다(인터뷰 0회).

### 7.2 에어갭·통제된 대외망 방향

- 수요 증거 있음: 올거나이즈·업스테이지·핑거 등이 금융권 망분리 온프레미스 RAG로 매출. 금융위 2024-08
  망분리 개선 방안이 외부 AI 연결을 특례로 인정해 "데이터 단위 반출 통제" 수요가 생김.
- 이기기 어려움: LLM+RAG 앱+SI를 묶어 파는 국내 업체가 많고, 고객은 데이터 계층을 따로 사지 않으며,
  공공은 인증·레퍼런스가 진입 조건. GraphRAG 정확도 주장은 대부분 벤더 발표.
- 들어갈 자리: LLM 중립 폐쇄망용 데이터 거버넌스 계층(파트너가 끼워 쓰는 부품). AWS 폐쇄 VPC +
  VPC 엔드포인트 Bedrock도 같은 요구.
- 필요한 것: 오프라인 설치 번들, HWP·PDF 파싱, 라벨·PII 설정 UI. GraphRAG는 요구가 있을 때.

### 7.3 레드오션 판정

| 층 | 경쟁 |
|---|---|
| 완성형 솔루션(LLM+RAG+구축) | 매우 높음 |
| RAG 조립 오픈소스(Dify, RAGFlow, Open WebUI 등) | 높음 — 실제 압력은 여기서 옴 |
| 거버넌스 데이터 계층 | 낮음 — 그러나 따로 사는 사람도 적음 |

## 8. 권장

1. 새 기능 개발을 멈추고 대화 3~5번으로 판정한다.
2. 셋 중 하나를 정한다.
   - **기존 고객 자산** — MSP 고객 중 생성형 AI 추진 고객에 관리 서비스로 붙인다. 성과는 관리 매출·고객 유지.
   - **파트너 부품** — LLM 벤더·SI에 거버넌스 계층으로 공급. 파트너 1~2곳의 의사가 성립 조건.
   - **멈춤** — 오픈소스로 두고 투자 최소화.
3. 검증과 기각 기준:

| 확인할 것 | 방법 | 기각 기준 |
|---|---|---|
| 대상 고객 존재 | MSP 청구 데이터(Databricks Marketplace 결제 고객, 생성형 AI 과제 고객) | 각각 5곳 미만 |
| 막힌 지점 | 고객 3~5곳(IT팀장, 정보보호) | "플랫폼도 거버넌스도 문제 아님" |
| 지불 의사 | 1곳에 유료·PoC 제안 | 응답 0곳 |
| 파트너 의사 | LLM 벤더·SI 2~3곳 | "직접 만든다" |

## 9. 운영 리소스

라이브 AWS 참조 배포(us-east-1, EC2/K3s + Aurora + S3 + Glue/Athena + Bedrock)는 이 검토 후
오너 지시로 정리 대상이 되었다. 정리 결과는 아래에 기록한다.

(정리 후 기록)

## 출처

- Databricks 가격: [DoIT](https://www.doit.com/de/blog/databricks-pricing-explained-dbus-tiers-cost-control),
  [Espresso AI](https://espresso.ai/guides/what-is-a-dbu-4119a), [KMS](https://kms-technology.com/?p=7587),
  [CloudForecast](https://www.cloudforecast.io/guides/databricks-pricing-costs-guide/), [Vendr](https://www.vendr.com/marketplace/databricks)
- Databricks 스타트업 크레딧: [EverythingStartups](https://www.everythingstartups.com/article/how-to-get-startup-credits-10-programs-for-free-ai-credits),
  [Superscout](https://superscout.co/perk/databricks), [Balderton](https://balderton.getproven.com/vendor/databricks)
- AWS: [SageMaker pricing](https://aws.amazon.com/sagemaker/pricing/), [SageMaker Lakehouse](https://aws.amazon.com/sagemaker/lakehouse/),
  [Neptune GraphRAG toolkit](https://aws.amazon.com/about-aws/whats-new/2025/01/amazon-neptune-open-source-graphrag-toolkit)
- 대안·이전 비용: [MotherDuck](https://motherduck.com/vs/databricks-alternative/),
  [beri.net](https://www.beri.net/article/databricks-alternatives-open-lakehouse-migration-cost-2026)
- 망분리: [금융위원회](https://www.fsc.go.kr/no010101/82885?curPage=86), [법무법인 세종](https://shinkim.com/kor/media/newsletter/2533)
- 국내 온프레미스 RAG: [ITWorld 올거나이즈](https://www.itworld.co.kr/article/3546683/),
  [ITWorld 리더보드](https://www.itworld.co.kr/article/3564560/), [Byline](https://byline.network/2024/09/30-339/),
  [Byline](https://byline.network/2024/05/29-273), [Venture Square](https://www.venturesquare.net/1067012/)
- GraphRAG: [Graphwise](https://tools.prnewswire.com/en-us/live/20823/release/20260216EN86780),
  [timbr.ai](https://timbr.ai/blog/every-vendor-is-automating-the-semantic-layer-for-ai-agents-heres-what-theyre-missing/),
  [Instaclustr](https://www.instaclustr.com/education/retrieval-augmented-generation/understanding-graph-rag-components-use-cases-and-best-practices/)
