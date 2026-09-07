# 포지셔닝 점검과 결정 — v6.0

> 작성: 2026-09-07 · 상태: **결정 기록** · 근거: `CONCEPT_RECONFIRMATION.md`(v6 제안),
> `UTILIZATION_PERSONA_ASSESSMENT.md`(2026-08-31), `PRODUCTIZATION_READINESS_ASSESSMENT.md`,
> `ONTOLOGY_FEASIBILITY_REPORT.md`, 2026-07-20 이후 커밋 이력, `app/capabilities.py`와 사이드바 코드.
>
> 이 문서는 v6 제안을 **v6.0 정본으로 승격**하는 결정과 그 이유를 기록한다. 제품 문장 자체는
> `PRODUCT_CONCEPT.md`가 정본이다. 적합도 점검 결과는 `POSITIONING_FIT_AUDIT.md`에 있다.
> 같은 날 추가: §5 시장 트렌드 대조, §6 시장 필요성 판정과 게이트웨이 전제 정정(권고 미적용),
> §7 기능·비용 관점 자리매김 분석.

## 1. 결론

포지셔닝의 문제는 문장이 나쁜 것이 아니라 **문장이 네 개이고, 어느 것도 구현·검증·채널과 맞지
않는다**는 점이다. 기술은 "버릴 프로토타입이 아니라 좁힐 제품"까지 왔지만 포지셔닝은 2026-07 이후
결정되지 않은 채 남아 있었다.

결정: **"AI 에이전트와 앱을 위한 governed 데이터 도구 서버"**로 고정한다(§5의 트렌드 조정으로
"도구 계층"에서 이름을 바꿨다). 한 문장과 세부는 `PRODUCT_CONCEPT.md` v6.0을 따른다.

## 2. 확인된 문제

### 2.1 정본이 하나가 아니다

| 시점 | 문장 | 위치 |
|---|---|---|
| 2026-04 | on-prem AI-Native Lakehouse (Databricks 대안) | `archive/oss-lakehouse` |
| 2026-06-30 | AWS-Native AI Data Foundation | pivot spec |
| 2026-07-14 | Portable AI Data Foundation (v5.0) | `README.md`, `PRODUCT_CONCEPT.md` |
| 2026-07-27 | 에이전트·AI 앱의 governed·portable 데이터 접근 계층 (v6 제안) | `CONCEPT_RECONFIRMATION.md` |
| 2026-07-27 | "governance + portability로 리드, Foundation도 RAG도 아님" | `OPERATIONS_PAUSE.md` |
| 2026-08-31 | "governed data access for AI/RAG로 메시지 축소" | `UTILIZATION_PERSONA_ASSESSMENT.md` §6-2 |

다섯 달에 네 번 바뀌었고, 문서마다 다른 문장을 리드로 쓰고 있었다.

### 2.2 리드 메시지가 가장 약하게 검증된 영역이다

"Governance"를 앞세우기로 했으나 2026-08-31 내부 평가는 데이터 거버넌스·감사 4.5/10, 감사자
페르소나 3.5/10, 규제·민감 데이터 운영 NO-GO였다. 그 뒤 컬렉션 멤버 공유(`0003`), DB 트리거 기반
append-only 감사(`0005`, 단 앱 role이 테이블 owner라 WORM은 아님), SQL 문장 종류 게이트
(`sql_kind.py`)가 들어왔다. 그러나 RLS는 여전히 기본 허용이고, 에이전트가 실제로 부르는
`/ai/search`·`/ai/rag`·`/ai/sql`의 **성공 호출은 감사에 남지 않으며**, 호출자별 예산은 강제되지
않는다(자세한 근거는 `POSITIONING_FIT_AUDIT.md`). 팔겠다는 것과 검증된 것의 간격은 줄었지만
아직 남아 있다.

### 2.3 "Portable"은 구매 이유가 아니라 반대 제거 장치다

고객은 exit 전략에 먼저 돈을 내지 않는다. export/import CLI와 exit drill은 미구현이라 이 약속은
문서상 약속이다. 헤드라인 자리에 둘 근거가 없다.

### 2.4 세그먼트가 고객이 아니라 실험에서 역산됐다

"jargon-heavy 규제 버티컬(의료코딩·법률·금융)"은 온톨로지 실험 4의 +25% 결과에서 나온 선택이다.
그 세그먼트는 정확히 지금 NO-GO인 감사 불변성·민감 PII·SLA를 요구한다.

### 2.5 v6이 말한 방향과 최근 6주가 만든 것이 다르다

v6의 핵심은 "시장 무게중심이 RAG에서 에이전트·도구 접근(MCP)으로 이동했고, DataPond 자산이 그대로
에이전트의 도구 면에 맞는다"였다. 그러나 2026-08-25 이후 커밋 대부분은 **DataPond 안에서 운영자가
쓰는 챗 어시스턴트**(액션 레지스트리, 파괴적 액션 게이트)에 들어갔다. 외부 에이전트가 DataPond를
도구로 쓰는 면(MCP 서버, 에이전트별 identity·spend, 도구 스코프 키)은 코드에 없다. 안쪽을 향한
코파일럿은 기능이지 카테고리가 아니다.

### 2.6 수요 게이트가 우회됐다

재확정 노트는 "디자인 파트너 1곳 확보 후 재시작, 3개월 내 0곳이면 컨셉 재검토"를 못 박았다.
2026-08-24 라이브를 재기동했지만 파트너 신호 기록이 저장소에 없고, 이후 작업은 기능 확장이었다.
3개월 시한은 **2026-10-27** 전후다.

### 2.7 표면이 여전히 넓다

Helm 프로필 7개, add-on 8개, 역할 7개가 고객 0명인 제품에 붙어 있다. 지원 티어 배지로 정직해졌지만
"무엇을 안 파는가"가 "무엇을 파는가"보다 길다.

## 3. 결정

### 3.1 한 문장

> **DataPond는 AI 에이전트와 애플리케이션이 회사의 문서와 테이블에 접근하는 governed 데이터
> 도구 서버다. 인용 RAG와 governed SQL을 도구로 노출하고, 어떤 호출자가 어떤 컬렉션·행을
> 읽을 수 있는지, 무엇이 인용되고 무엇이 마스킹됐는지, 얼마까지 쓸 수 있는지를 데이터 계층에서
> 통제한다. AWS 위에서 바로 운영하고, 개방 계약 위에 있어 잠기지 않는다.**

(§5.2의 트렌드 조정과 §6.1의 게이트웨이 구절 삭제가 반영된 최종 문장. 초안은 "governed 도구 계층 … 호출자 단위로 접근·PII
마스킹·감사·비용을 통제한다"였다.)

### 3.2 다른 후보보다 나은 이유

1. Bedrock Knowledge Bases·AgentCore와 정면충돌하지 않고 그 위의 빈틈(호출자별 spend 귀속, 한국
   PII, 앱 레벨 ACL, provider 교체)을 겨냥한다.
2. 이미 만든 어시스턴트의 **액션 레지스트리 + 이중 권한 게이트 + invocation 감사**가 외부 도구
   면의 골격이다. 방향을 뒤집으면 지난 6주 투자가 회수된다.
3. "LLM 없이도 말이 되는 기능은 경고"라는 v6 원칙에 가장 부합한다.

### 3.3 바뀌는 것과 유지되는 것

| | v5.0 | v6.0 |
|---|---|---|
| 프레임 | Portable AI Data Foundation | 에이전트·앱의 governed 데이터 도구 서버, 직접 호출이 기본 |
| 리드 | 파운데이션 넓이 | 데이터 계층 거버넌스: 호출자별 컬렉션·행 접근, 인용·마스킹 감사, 호출자별 예산 |
| Portability | 헤드라인 | 두 번째 문단의 "no lock-in" 반대 제거 문구 |
| 첫 세그먼트 | jargon-heavy 규제 버티컬 | AWS 위에서 사내 문서·테이블에 에이전트 접근을 열되 개인정보보호법 대응이 걸리는 한국 기업 |
| 규제 버티컬 | 첫 파트너 | 감사 불변성 이후의 두 번째 단계 |
| 온톨로지 | 수요 게이트 옵션 | 동일. Phase 1 착수 없음 |

유지: Portable Core 아키텍처, 개방 계약, 배포 프로필, fail-closed capability 게이팅, 거버넌스
경계·출구 전략·Open Core 원칙, 과대주장 금지.

### 3.4 하지 않을 것

- 게이트웨이 기능: 에이전트 레지스트리, SSO/SCIM 동기화, rug-pull 탐지, tool 단위 정책 엔진
- 코딩 에이전트 토큰 spend 통제, spend를 리드 메시지로 쓰는 것
- 온톨로지 Phase 1·GraphRAG
- add-on 추가, Databricks/Snowflake 비교표
- 운영자용 어시스턴트 액션 추가 (기존 29개는 유지)
- 규제 버티컬을 첫 파트너로 삼는 것

## 4. 실행

1. **문서 정본 통일** — 이 결정과 함께 `README.md`, `PRODUCT_CONCEPT.md`(v6.0), `docs/README.md`,
   `CLAUDE.md`를 개정한다. "Foundation"은 이름에서 제거한다. MCP는 **다음 슬라이스**로 표기하되
   shipped라고 쓰지 않는다.
2. **적합도 점검** — 새 문장 기준으로 기능·사용성을 점검한다. `POSITIONING_FIT_AUDIT.md`.
3. **수요 게이트 재가동** — 2026-10-27까지 고객 대화 10건과 데모. 신호의 정의: 실제 데이터·예산·
   지불 경로를 가진 파트너 1곳, 또는 유료 PoC 합의 1건. 미달이면 노트대로 컨셉을 재검토한다.
4. **빌드는 게이트 뒤 한 조각만** — 파트너 대화에 필요한 최소 데모는 "외부 에이전트가 도구로
   Knowledge 검색·governed SQL을 호출하고, 호출자별 spend와 감사가 화면에 찍히는 것"이다.
   적합도 점검이 그 조각의 크기를 정한다.
5. **주장과 구현의 티어 일치** — append-only 감사와 default-deny RLS가 없는 동안 "감사 가능"·
   "규제 대응"은 로드맵으로 표기한다.
6. **표면 축소** — 공개 프로필은 `values-foundation.yaml`과 `values-prod-single.yaml` 두 개를
   앞세우고 나머지는 compatibility로 내린다.
7. **수익 모델 정렬** — Enterprise 후보: 정책 팩, 감사 export, 호출자별 예산 강제, 다중 환경
   운영. 데이터 export는 Community에 남긴다.

## 5. 2026-09 시장 트렌드 대조와 조정

2026-09-07 웹 조사로 v6.0을 시장 상태와 대조했다. 결론은 **방향은 맞고 시점은 늦지 않았지만 창은
12~18개월**이다.

### 5.1 확인된 사실

- 시장 무게중심이 "만들기"에서 "운영하기"로 넘어갔다. Databricks·Snowflake 2026 서밋 모두 에이전트를
  기본 연산 단위, MCP를 프로토콜, 거버넌스의 AI 확장, 비용 통제를 말했다. Gartner는 2026년 말 기업 앱
  40%에 에이전트가 들어가되, 거버넌스 부실로 2027년까지 프로젝트 40% 이상이 취소될 수 있다고 본다.
  도입 79% 대 프로덕션 11%.
- MCP 2026-07-28 스펙: stateless HTTP, OAuth 2.0/OIDC 정렬, 확장 체계. Linux Foundation AAIF 이관.
  Fortune 500의 28% 배포. 보안은 채택을 못 따라간다.
- AWS AgentCore Gateway(2026-08-21 포스트): 인바운드 JWT/OAuth, Cedar 정책, principal·tool별 rate
  limit, CloudTrail 감사, Guardrails PII, JWT claim 기반 비용 태깅. **row-level 데이터 접근, RAG 인용·
  검색 거버넌스, 에이전트별 예산 상한은 다루지 않는다고 명시.** Bedrock Managed Knowledge Base
  2026-06-17 출시, Kendra 유지보수 모드.
- Databricks Unity AI Gateway(2026-06-16): 하드 spend cap, PII guardrail, MCP 페이로드 로깅. **Databricks
  안에서만.** Snowflake는 Natoma 인수 후 Cortex AI Gateway. Palo Alto가 Portkey 인수. Obot 시드 35M,
  Runlayer 11M달러.
- 에이전트 identity: 조직 88%가 에이전트 보안 사고, 에이전트를 독립 identity로 다루는 팀 22%.
- 한국: 개인정보위 2026 계획은 매출 10% 과징금, 2026-06 CEO 최종 책임, ISMS-P 강화. AWS Summit Seoul
  2026 규제 환경 세션은 책임 소재·감사 투명성을 pain으로 짚고 파트너 제품은 언급 없음.

### 5.2 v6.0에 반영한 조정

| 항목 | 조정 |
|---|---|
| 카테고리 이름 | "governed 도구 계층" → **"governed 데이터 도구 서버"**. 게이트웨이와 이름이 겹치지 않게 |
| 게이트웨이 관계 | **직교**로 명시. 기본은 직접 호출, 게이트웨이가 있으면 타깃 등록(§6.1에서 한 문장의 구절은 삭제) |
| 리드 차별점 | AWS가 스스로 비워 둔 셋: 호출자별 컬렉션·행 접근(청크 단위는 roadmap, `FIT_AUDIT` §6.3), 인용·마스킹 감사, 호출자별 예산 |
| spend | 리드에서 보조로. 토큰 지출의 큰 몫은 코딩 에이전트에 있다 |
| MCP | roadmap → **다음 데모 슬라이스**(read 전용, 기존 레지스트리 위). shipped 표기는 여전히 아님 |
| 첫 세그먼트 | 한국 규제 구체화: 한국형 식별자 마스킹 증적, CEO 책임 대응 감사 export, ISMS-P 증빙 |
| 하지 않을 것 | 게이트웨이 기능(레지스트리, SSO/SCIM, rug-pull 탐지, tool 정책 엔진), 코딩 에이전트 spend 추가 |

### 5.3 트렌드가 바꾼 우선순위

성공한 검색·답변 호출의 감사(`POSITIONING_FIT_AUDIT.md` P0-1)는 트렌드 관점에서도 첫 번째다.
Databricks는 MCP 페이로드를 시스템 테이블에, AgentCore는 호출마다 principal·정책·guardrail 플래그를
CloudTrail에 남긴다. DataPond는 지금 성공한 read를 남기지 않는다. 그다음이 MCP 어댑터다.

### 출처

- https://aws.amazon.com/blogs/machine-learning/govern-ai-agent-tool-access-with-amazon-bedrock-agentcore-gateway/
- https://aws.amazon.com/blogs/machine-learning/how-agentcore-gateway-supports-the-mcp-2026-07-28-spec/
- https://atlan.com/know/ai-agent/databricks/unity-ai-gateway/
- https://www.pointfive.co/blog/snowflake-and-databricks-summits-2026-what-actually-matters
- https://obot.ai/blog/obot-ai-secures-35m-seed-to-build-enterprise-mcp-gateway/
- https://www.digitalapplied.com/blog/mcp-adoption-statistics-2026-model-context-protocol
- https://www.gartner.com/en/articles/hype-cycle-for-agentic-ai
- https://joget.com/ai-agent-adoption-in-2026-what-the-analysts-data-shows/
- https://identitychallengecard.avatier.com/en/blog/identity-ai-agents-agentic-authentication-2026
- https://tech.cloud.nongshim.co.kr/blog/aws/3892/
- https://www.kimchang.com/ko/insights/detail.kc?sch_section=4&idx=33715

## 6. 시장 필요성 판정과 게이트웨이 전제의 정정 (2026-09-07)

### 6.1 "AgentCore 뒤에서 동작"은 축이 아니라 호환 조건이다

§5.2에서 한 문장에 넣은 "AgentCore Gateway를 포함한 어떤 MCP 게이트웨이 뒤에서도 동작하며"는
과했다. `POSITIONING_FIT_AUDIT.md` §6.2가 이유를 드러냈다.

- AgentCore Gateway는 OpenAPI·MCP 타깃에 token passthrough를 지원하지 않는다. API key로 등록하면
  게이트웨이 뒤의 모든 에이전트가 서비스 계정 하나로 보여, 리드인 "호출자 단위"가 게이트웨이
  단위로 약해진다. 에이전트가 **직접** 호출하면 에이전트당 서비스 계정으로 호출자 단위가 그대로다.
- 첫 세그먼트(한국 파일럿)에는 아직 게이트웨이가 없다. 에이전트 프로덕션 비율 11%.
- 한 문장에 특정 AWS 서비스가 들어가면 "잠기지 않는다"와 sovereign 프로필이 흐려진다.
- 두 제품은 직교한다. 게이트웨이는 도구·에이전트 사이의 중앙 정책, DataPond는 도구가 돌려주는
  데이터의 범위다. 직교는 "뒤에서 동작"이 아니라 "있어도 없어도"로 쓴다.

**권고(2026-09-07 적용됨):** 한 문장에서 해당 구절 삭제. "게이트웨이와의 관계" 절은 "게이트웨이가
있어도 없어도"로 제목을 바꾸고, 기본 경로를 직접 호출(REST, 다음은 MCP)로, 게이트웨이 등록은
how-to로 내린다. OIDC access token resource-server 모드는 게이트웨이가 아니라 MCP 2026-07-28의
OAuth 정렬 때문에 유지한다.

### 6.2 시장이 필요로 하는 제품인가

**문제는 실재하고 급해진다.** 에이전트 보안 사고 88%, 거버넌스 부실로 2027년까지 프로젝트 40%
취소 전망, 개인정보위 과징금·CEO 책임. 세 플랫폼이 같은 달에 같은 말을 했다.

**그러나 이 제품을 산다는 증거는 없다.** Databricks·Snowflake 고객은 제외된다. AWS 네이티브 조합은
기본 이야기를 덮고 Guardrails가 주민번호도 가린다. 남는 자리는 AWS가 스스로 비워 둔 row-level
접근, 검색·인용 감사, 에이전트별 예산이며 그중 둘은 아직 구현이 없다. 진짜 경쟁자는 직접 구축이다.

남는 구매자: **AWS 위에 있거나 온프렘이 필요하고, Databricks가 없으며, 에이전트 파일럿이
보안·컴플라이언스 심사에 막혀 "어느 에이전트가 어떤 행을 읽었는지"를 지금 요구받는 한국 중견
기업·공공.** 존재 가능성은 높지만 단독 제품을 지탱할 크기인지는 모른다.

판정 질문 하나: *파일럿이 심사에 막힌 팀이 있는가. 그 팀이 감사와 행 단위 제한을 이유로 예산을
쓸 수 있는가. AWS 네이티브로는 왜 안 되는가.* 2026-10-27까지 대화 10건에서 셋 다 "예"인 팀이
하나면 필요한 제품이다. 없으면 문제는 실재하되 이 형태로는 사지 않는 것이며, 현실적 출구는 AWS
파트너 채널의 전달 가속기다. 이는 7월에 피하기로 한 서비스 경로와 부딪히므로 창업자가 미리 정할
판단이다.

## 7. 기능·비용 관점의 자리매김 분석 (2026-09-07)

### 7.1 결론

기능만으로도, 비용만으로도 자리매김이 안 된다. 되는 조합은 **"AWS 네이티브와 같은 인프라 비용으로,
AWS가 안 하는 데이터 계층 거버넌스를, 직접 구축 비용의 몇 분의 일에"** 하나다. 그 안의 핵심 기능
둘이 아직 없고 가격은 정해져 있지 않다.

### 7.2 기능 비교

| 기능 | DataPond | AWS 네이티브 (AgentCore + Managed KB + Guardrails) | 직접 구축 | Databricks·Snowflake |
|---|---|---|---|---|
| 벡터 검색·인용 RAG | 있음. PDF·hybrid 없음 | 있음. 멀티모달 파싱·rerank 번들 | 몇 주 | 있음 |
| 호출자별 컬렉션·행 접근 | **있음** (멤버 ACL, RLS) | KB 메타데이터 필터. 행 단위 RLS 없음 | 만들어야 함 | 플랫폼 안 |
| 검색·인용 단위 감사 | **없음, 핵심 갭** | 없음 (AWS 명시) | 만들어야 함 | 있음 |
| 호출자별 spend 귀속·예산 | 귀속 있음, 강제 없음 | tool·그룹 단위 알림만 | 만들어야 함 | 하드 cap |
| PII 마스킹 | 한국형 regex 6종, 적재·인용 시점 | Guardrails, 주민번호 포함, ML | 라이브러리 조합 | 있음 |
| 게이트웨이·에이전트 identity | 없음, 안 만듦 | 있음 | 보통 안 만듦 | 있음 |
| 온프렘·타 클라우드 | **있음** (동일 코드) | 불가 | 가능 | 불가 |
| 운영 UI | 있음 | 콘솔 분산 | 없음 | 있음 |

DataPond가 **혼자 가진 것**: 행 단위 접근 + 온프렘 동일 코드 + 운영 UI. **가지면 혼자가 되는 것**:
검색·인용 단위 감사 + 호출자별 예산 강제. 한국형 PII는 Guardrails가 주민번호를 가리므로 차별점이
아니라 동등 항목이다.

### 7.3 비용 비교

**인프라 운영비는 비슷하다.** 파일럿 규모 월 추정:

| 항목 | DataPond AWS 단일 노드 | AWS 네이티브 기본 구성 |
|---|---|---|
| 컴퓨트 | m6i.xlarge spot 약 $50~60 (온디맨드 $140) | AgentCore Runtime vCPU·GB 시간 과금, 파일럿 수십 달러 |
| 벡터·상태 저장 | Aurora Serverless v2 0~4 ACU, 약 $45~350 | OpenSearch Serverless 바닥 $175~350. S3 Vectors·Aurora pgvector면 $50 이하 |
| 검색 호출 | 컴퓨트에 포함 | Managed KB $1 / 1,000 retrieve + $5 / GB·월 |
| 게이트웨이·정책 | 없음 | $5 / 100만 호출 + $25 / 100만 정책 평가 |
| PII | 포함 | regex 무료, ML 필터 $0.10 / 1,000 text unit |
| 모델 토큰 | Bedrock 동일 | Bedrock 동일 |

둘 다 월 $150~400이며 차이의 대부분은 벡터 스토어 선택이다. DataPond는 인프라 비용으로 이기지
못한다. 월 100만 retrieve를 넘으면 KB 건당 과금이 고정 컴퓨트보다 비싸지지만 그 규모에서 단일
노드는 다른 문제를 만난다.

**구축·통합 비용에서 차이가 난다.** 호출자별 ACL, 행 필터, 감사, spend, PII, 신선도를 직접 만들면
엔지니어 2명 기준 2~3개월, 4~6인월, 한국 인건비로 4천만~8천만 원, 유지보수 별도. AWS 네이티브도
KB·Gateway·Guardrails·CloudTrail·Athena 리포트 통합에 2~4주. DataPond가 파는 것은 이 시간이다.

**구매자가 실제로 세는 비용:** 심사에 막힌 파일럿의 몇 주와 매출 10% 과징금 위험. 이것이 가격을
정당화하는 유일한 근거다.

**가격은 아직 없다.** Community Apache-2.0 무료, EE placeholder. 가격은 두 값 사이여야 한다. 아래로는
AWS 네이티브 대비 추가 인프라비 0, 위로는 직접 구축 비용의 절반 아래. 환경당 연 1~2인월,
1,500만~3,000만 원이 그 사이다. 감사 export·예산 강제·정책 팩을 EE에, 데이터 이동은 Community에
두는 Open Core 원칙과 맞는다.

### 7.4 자리매김 조건

동시에 맞아야 하는 셋:

1. **검색·인용 단위 감사와 호출자별 예산 강제를 먼저 만든다.** 없으면 DataPond만의 칸이 온프렘과
   행 단위 둘뿐이다.
2. **인프라 비용은 같다고 말하고, 구축 시간과 심사 통과로 판다.** Aurora pgvector가 KB 기본 구성의
   OpenSearch 바닥보다 싸다는 말은 가능하지만 S3 Vectors로 사라지는 차이라 헤드라인에 두지 않는다.
3. **구매자를 둘로 좁힌다.** Databricks 없는 AWS 고객 중 파일럿이 심사에 막힌 팀, 그리고 AWS
   네이티브가 갈 수 없는 온프렘·주권 환경. 후자는 AWS 조합과 아예 경쟁하지 않는 유일한 자리다.

되지 않는 조건: 검색 품질로 경쟁(KB 번들에 진다), 인프라 비용으로 경쟁(S3 Vectors에 진다),
게이트웨이 기능 추가(자금 수십 배 상대와 붙는다).

### 출처 (7장)

- https://www.cipherprojects.com/blog/posts/amazon-bedrock-agentcore-pricing-2026/
- https://cloudburn.io/blog/amazon-bedrock-agentcore-pricing
- https://aws.amazon.com/bedrock/pricing/
- https://cloudchipr.com/blog/amazon-bedrock-pricing
- https://www.bacancytechnology.com/blog/aws-bedrock-pricing
- https://ercanermis.com/cutting-amazon-bedrock-knowledge-base-costs-by-90-migrating-from-opensearch-serverless-to-aurora-serverless-v2-with-pgvector/
- https://cloudburn.io/blog/amazon-opensearch-pricing
- https://www.usage.ai/blogs/aws/rds/aurora-serverless-v2/
- https://darryl-ruggles.cloud/the-real-cost-of-vector-storage-s3-vectors-vs-opensearch-vs-pgvector-vs-pinecone/
- 라이브 사이징: `terraform/variables.tf` (`m6i.xlarge`, `db_min_acu=0`, `db_max_acu=4`), `helm/datapond/values-prod-single.yaml` (Titan v2, Claude Haiku 4.5)
