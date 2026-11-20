# 비용·지출·예산 로직 (현재 코드 기준)

> 작성 2026-11-20, 브랜치 `feat/catalog-ux-1` (커밋 `6a4af66`) 기준. 이 문서는 지금 코드가 실제로 하는 일만 적는다. 줄 번호는 이 커밋 기준이며 코드가 바뀌면 어긋날 수 있다. 코드에서 확인하지 못한 동작은 "코드에서 확인되지 않음"으로 표시했다.

DataPond에는 서로 독립된 비용 로직이 두 갈래 있다.

- **AI 모델 지출**: LiteLLM 게이트웨이가 호출마다 비용을 계산해 기록하고, DataPond는 그 기록을 호출자(caller)별로 귀속·집계·표시하며 호출자별 상한(cap)을 강제한다. DataPond 자체에는 모델 단가표가 없다. 금액은 전부 LiteLLM이 계산한 값이다.
- **AWS 인프라 비용**: AWS Single-Node Reference에서만 켜지는 Infrastructure › Cost 탭. CloudWatch/EC2/RDS 사용량에 코드에 하드코딩된 단가를 곱한 **추정치**, 그리고 (태그가 활성화되어 있으면) Cost Explorer의 **실제 청구액**을 보여 준다. 월 예산은 알림용이며 아무것도 차단하지 않는다.

---

## 1. 한눈에 보기

| 영역 | 무엇을 계산/제한 | 데이터 출처 | 화면 | 핵심 파일 |
|---|---|---|---|---|
| AI 지출 귀속 | 모든 모델 호출에 호출자 id(`user`)와 기능 태그(`app:<기능>`)를 붙임 | 요청 ContextVar → LiteLLM payload | (없음, 이후 집계의 기반) | `backend/app/ai_context.py` |
| AI 지출 집계 (운영자) | 전체/모델별/호출자별/기능별 지출·토큰 | LiteLLM `/global/spend`, `/global/spend/models`, `/spend/logs`, `/key/list`, `/customer/list` | AI Gateway › Spend | `backend/app/api/ai_backends.py`, `frontend/components/settings/ai-backends.tsx` |
| AI 지출 집계 (본인/에이전트) | 한 호출자의 지출·토큰·기능별 분할 | LiteLLM `/spend/logs` (backend에서 필터) | Your account(`/account`), Agents › 에이전트 페이지 | `ai_backends.py` `spend_for_user`, `frontend/components/ai/my-spend.tsx`, `frontend/components/agents/spend-section.tsx` |
| Overview "Model spend" | 게이트웨이 전체 누적 지출, 전역 예산 % | LiteLLM `/global/spend` (via `/settings/ai/budget-alerts`) | Overview(대시보드) Today 카드 | `frontend/components/dashboard/today-card.tsx`, `frontend/lib/dashboard-activity.ts` |
| 호출자별 상한(cap) | spend ≥ cap이면 모델 호출 전 HTTP 402 | Postgres `ai_budget_caps`(0024) + LiteLLM customer budget | AI Gateway › Budgets, Agents › 에이전트 | `backend/app/ai_budget.py`, `backend/app/api/ai_budgets.py` |
| 예산 경고 | 가상 키·전역 예산이 임계치(기본 80%) 이상인지 | LiteLLM `/global/spend`, `/key/list` | AI Gateway › Spend 상단 경고, Overview 타일 경고색 | `ai_backends.py` `budget_alerts` |
| 키별 요청 한도 | 서비스 계정 키당 분당 요청 수 (돈이 아니라 부하) | 프로세스 메모리 토큰 버킷 | (429 응답) | `backend/app/rate_limit.py` |
| AWS 비용 추정 | 이번 달 누계(MTD)·월말 예측·일별 비용·절감 여지 | CloudWatch, EC2, RDS, Scheduler, Secrets Manager + `PRICES` 하드코딩 + LiteLLM `/spend/logs` | Infrastructure › Cost (`/services?tab=cost`) | `backend/app/aws_cost.py`, `backend/app/aws_infra.py` |
| AWS 실제 비용 | `Project=<prefix>` 태그 리소스의 MTD 청구액 | Cost Explorer `ce:GetCostAndUsage` | Infrastructure › Cost | `aws_infra.py` `actual_costs` |
| AWS 월 예산 | 예측치가 예산을 넘었는지 | `system_settings` 키 `infra.monthly_budget_usd` | Cost 탭 Budget 타일, Overview 이슈 `cost_over_budget` | `backend/app/api/infra_aws.py`, `backend/app/api/ops.py`, `frontend/lib/ops-status.ts` |

---

## 2. AI 모델 지출: 귀속과 집계

### 2.1 흐름

```text
요청 (사람 세션 / 서비스 계정 키 / IdP 토큰)
  → 라우트가 set_actor(user)  (ContextVar)
  → 모델 호출 payload에 actor_payload(app) 병합: user=<users.id>, metadata.tags=["app:<기능>"]
  → LiteLLM이 호출 비용 계산 후 spend_logs에 end_user / request_tags / spend / tokens 기록
  → DataPond가 LiteLLM 관리 API를 읽어 집계
  → AI Gateway / Your account / Agents / Overview / Infrastructure › Cost 에 표시
```

### 2.2 귀속 (attribution)

- `set_actor(user)`가 요청의 사용자 `id`(없으면 `username`, 그래도 없으면 `"anonymous"`)를 ContextVar에 넣는다 (`backend/app/ai_context.py:23-28`). ContextVar는 `asyncio.to_thread`로도 전달되므로 동기 호출 경로도 같은 값을 본다 (`ai_context.py:10-13`).
- `actor_payload(app)`는 payload에 두 가지를 넣는다 (`ai_context.py:31-56`).
  - `user`: LiteLLM이 spend_logs의 `end_user`로 기록한다. **호출자별 귀속이 살아남는 유일한 통로**다.
  - `metadata.tags = ["app:<기능>"]`: spend_logs의 `request_tags`로 남는다. 기능별 집계에 쓰인다.
  - `metadata.user_id`/`username`도 보내지만, 코드 주석에 따르면 LiteLLM이 spend_logs의 `metadata`를 자체 객체로 덮어써서 남지 않는다 (`ai_context.py:40-48`).
  - actor가 없으면(백그라운드 작업, 예: RAG 재임베딩 스케줄러) `user` 없이 태그만 보낸다 → 집계에서 `unattributed`가 된다 (`ai_context.py:52-55`).
- `set_actor`를 호출하는 라우트: `/ai/embed`(`backend/app/api/ai_vectors.py:367`), 수집(`ai_vectors.py:884`), 소스 수집(`ai_vectors.py:1130`), 검색(`ai_vectors.py:1618`), RAG(`ai_vectors.py:1703`), NL→SQL(`backend/app/api/ai_sql.py:474`), 어시스턴트 채팅(`backend/app/api/chat_routes.py:138`).
- `actor_payload`를 붙이는 모델 호출과 기능 태그:

  | 태그 | 호출 | 위치 |
  |---|---|---|
  | `app:ai_embed` | `/v1/embeddings` (검색·RAG·수집·`/ai/embed` 공통) | `ai_vectors.py:211-213` |
  | `app:ai_rerank` | `/v1/rerank` | `ai_vectors.py:1240-1244` |
  | `app:ai_rag` | RAG 답변 생성 `/v1/chat/completions` | `ai_vectors.py:1763-1767` |
  | `app:ai_sql` | NL→SQL 생성 | `ai_sql.py:238-243` |
  | `app:ai_chat` | 콘솔 어시스턴트 | `chat_routes.py:365-369` |

- **서비스 계정(에이전트 키)**: 별도 엔티티가 아니라 `auth_method='service'`인 `users` 행이다. 그래서 키로 들어온 호출도 계정의 `users.id`가 그대로 `user`로 전달되어 사람과 같은 방식으로 귀속된다 (`backend/app/service_accounts.py:1-17`).
- **귀속되지 않는 호출**: 모델 테스트 `POST /settings/ai/backends/{model_name}/test`는 `actor_payload` 없이 완성 요청을 보낸다 (`ai_backends.py:429-436`). 코드 주석은 "다른 호출처럼 과금된다"고 적고 있지만(`ai_backends.py:407-410`), spend_logs에서는 `end_user`가 비어 `unattributed`로 잡힐 것이다. LiteLLM 가상 키로 게이트웨이를 직접 부르는 호출도 DataPond를 거치지 않으므로 호출자 귀속·상한·감사 로그가 없다 (`docs/UPGRADING.md:230-233`).

### 2.3 집계 API

모든 금액은 USD이며 LiteLLM이 계산한 값이다. 게이트웨이 주소·키는 `LITELLM_URL`, `LITELLM_MASTER_KEY`에서 읽고, `LITELLM_URL`이 비어 있으면 503 (`ai_backends.py:107-113`).

| API | 권한 | 출처 | 계산 |
|---|---|---|---|
| `GET /api/settings/ai/usage` | `spend:read` | `/global/spend`, `/global/spend/models`, `/spend/logs`, `/key/list`, `/customer/list`, `ai_budget_caps` | `total_spend`·`max_budget`는 `/global/spend` 그대로. 모델별 spend는 `/global/spend/models`, 토큰은 `/spend/logs`를 모델별 합산. 호출자별은 `/spend/logs`를 `end_user`로 묶고 없으면 `unattributed`. 기능별은 `request_tags`의 `app:` 접두사로 묶고 없으면 `untagged`. 각 호출자 행에 이름(`_with_user_names`)과 집행 중인 cap(`_with_user_budgets`, DataPond 값 우선)을 붙인다 (`ai_backends.py:693-806`, 기능별 `585-609`) |
| `GET /api/settings/ai/spend` | `spend:read` | `/key/list` 페이지 순회(100개씩, 최대 50페이지) | 가상 키 `spend` 합. 읽기 실패나 키 5000개 초과면 `{unavailable}`, 부분 합은 반환하지 않음 (`ai_backends.py:530-579`) |
| `GET /api/settings/ai/spend/report` | `spend:read` | `/global/spend/report` | 기간 지정, 기본 최근 30일. 게이트웨이 오류 시 `detail`·`status_code`만 반환 (`ai_backends.py:824-848`) |
| `GET /api/settings/ai/budget-alerts?threshold=80` | `spend:read` | `/global/spend`, `/key/list` | `spend_total` = 게이트웨이 전체 누적 지출. 전역 `max_budget`이 있으면 `pct = spend/max_budget×100`, `alert = pct ≥ threshold`. 가상 키도 같은 식으로 경고 목록 (`ai_backends.py:851-885`) |
| `GET /api/settings/ai/usage/me` | `ai:generate` | `/spend/logs` | `end_user == 본인 id`인 행만 합산 (`ai_backends.py:673-690`, `spend_for_user` `888-907`) |
| `GET /api/service-accounts/{id}/usage` | `ai:generate` + (admin 또는 그 계정 자신) | `/spend/logs` | 위와 같은 `spend_for_user`, 실패 시 `unavailable: true` (`ai_backends.py:642-670`) |

`spend_for_user`는 `end_user`가 없는 행을 누구에게도 넣지 않는다 (`ai_backends.py:888-900`).

### 2.4 화면

- **AI Gateway** (`/ai`, `frontend/app/ai/page.tsx`): admin은 Models·Spend·Budgets·Keys 탭, `spend:read` 보유자(ai_engineer, auditor)는 Spend·Budgets 탭 (`page.tsx:19-20, 49-62`).
  - Spend 탭 = `UsagePanel`: `/settings/ai/usage`와 `/settings/ai/budget-alerts`를 읽어 전체·모델별·호출자별·기능별 지출, 전역 예산 경고와 키 예산 경고를 표시 (`frontend/components/settings/ai-backends.tsx:555-620`).
  - Keys 탭 = LiteLLM 가상 키 목록/발급/폐기 (`frontend/components/ai/virtual-keys.tsx`, API `ai_backends.py:448-527`, admin 전용).
- **Overview "Model spend"** 타일: `spend:read`가 있으면 `/settings/ai/budget-alerts`를 호출해 `spend_total`(게이트웨이 전체 누적)을 표시하고, 전역 예산이 있으면 "all time · N% of $X budget", 없으면 "all time · no global budget". `alert`이면 경고색, 클릭 시 `/ai` (`frontend/app/dashboard/page.tsx:59, 81, 108-110`; `frontend/components/dashboard/today-card.tsx:40-64`; `frontend/lib/dashboard-activity.ts:77-85`). 읽지 못하면 0이 아니라 "—"와 "Not measured"를 보여 준다 (`frontend/lib/spend-summary.ts:16-24`).
- **Your account** (`/account`): `MySpend`가 `/settings/ai/usage/me`를 표시 (`frontend/app/account/page.tsx:102`, `frontend/components/ai/my-spend.tsx:35`).
- **Agents › 에이전트 페이지**: `/service-accounts/{id}/usage`와 `/settings/ai/budgets/{id}`로 지출과 cap을 보여 주고 cap 수정 가능 (`frontend/components/agents/spend-section.tsx:19-43`, `summary-rail.tsx:24`). 목록은 `/settings/ai/budgets` 사용 (`frontend/app/agents/page.tsx:51`).
- **어시스턴트(챗) 액션**: `spend.summarize`(`spend_summary` = 가상 키 합)와 `spend.diagnose_change`(직전 동일 기간 대비 증감과 원인이 호출량인지 호출당 단가인지 판정), 둘 다 `spend:read` (`backend/app/chat/analysis/spend.py:153-171`). 판정식: `delta = cur − prev`, `fraction = delta/prev`, 호출당 단가 `cur_spend/cur_calls` 비교 (`spend.py:117-148`). 이전 기간 지출이 0이면 판정하지 않는다.
- **Per-collection 지출 화면**: 코드에서 확인되지 않음. 컬렉션 id/이름은 LiteLLM payload에 실리지 않으므로 컬렉션 단위 집계 근거가 없다.

### 2.5 권한

- `ai:generate`: 모델 토큰을 쓰는 모든 동작(Ask AI, RAG, 임베딩)에 필요 (`backend/app/permissions.py:10-14, 36`). 보유 역할: admin, ai_engineer, data_scientist (`permissions.py:53-79`). data_engineer는 수집은 하지만 이 권한이 없다.
- `spend:read`: 전체 사용량·비용 보기. 보유: admin, ai_engineer, auditor (`permissions.py:45, 66-69, 86-89`).
- 서비스 계정은 역할과 무관하게 `settings:write`, `user:manage`를 갖지 못한다 (`service_accounts.py:31-37`).

---

## 3. 예산과 상한 (caps)

### 3.1 호출자별 상한: 저장 위치와 집행

상한은 두 곳에 있다.

1. **LiteLLM customer budget**: DataPond 호출자 id = LiteLLM end user(customer). customer의 `max_budget`을 넘으면 게이트웨이가 호출을 거절한다 (`backend/app/ai_budget.py:1-8`).
2. **Postgres `ai_budget_caps`** (migration 0024, `backend/migrations/versions/0024_ai_budget_caps.sql`): `user_id text PK`, `max_budget double precision NOT NULL CHECK (>= 0)`, `updated_at`. DataPond로 설정한 cap을 모든 backend pod가 같은 값으로 보게 하려고 추가됐다.

**호출 전 검사 `assert_within_cap`** (`ai_budget.py:171-199`):

```text
actor.id 없음 → 검사 안 함
shared = ai_budget_caps에서 읽음 (DB 오류면 '없음'으로 간주하고 게이트웨이 값 사용)
shared가 있고 ≤ 0 → 바로 402 (게이트웨이에 묻지 않음)
figures = 게이트웨이 /customer/info?end_user_id=… (pod별 15초 캐시, 404면 cap 없음·spend 0)
게이트웨이 접근 실패 → 검사 통과 (이후 게이트웨이 자체 검사에 맡김)
cap = shared가 있으면 shared, 없으면 게이트웨이 cap
cap이 있고 spend >= cap → 402
```

- 캐시: `CACHE_TTL_SECONDS = 15.0`, 캐시하는 것은 게이트웨이의 (cap, spend) 쌍이며 DB cap은 매 호출마다 읽는다 (`ai_budget.py:88-128, 135-141`).
- 게이트웨이 판정은 `spend > cap`(이미 기록된 spend 기준, 비동기 기록)이라 한 번 더 통과되는 경우가 있었고, DataPond 검사는 `spend >= cap`으로 도달 시점에 막는다 (`ai_budget.py:16-22`).

**이 검사가 걸리는 경로**: 모든 임베딩(`_embed`, `ai_vectors.py:203-208`; 검색·RAG 질의 임베딩·수집·`/ai/embed`가 모두 여기를 지난다), NL→SQL 생성(`ai_sql.py:257-260`, 호출부 `562, 605`).
**걸리지 않는 경로**: 리랭크(`ai_vectors.py:1231-1257`, 사전 검사 없음, 실패 시 벡터 순서로 조용히 대체), RAG 답변 생성 호출 자체(같은 요청의 질의 임베딩 단계에서 이미 검사됨), 어시스턴트 채팅(`chat_routes.py:350-399`), 모델 테스트. 이들은 게이트웨이 자체 검사만 받는다.

### 3.2 상한에 걸렸을 때

- 게이트웨이의 예산 거절은 401 `auth_error` 또는 400 `budget_exceeded`로 오며, 상태 코드가 아니라 메시지(`exceededbudget`, `over budget`, `budget has been exceeded`, `budget_exceeded`)로 식별한다 (`ai_budget.py:42-58`).
- DataPond는 이를 **HTTP 402**로 바꾸고 본문에 "This caller has reached its model spend budget." + 게이트웨이 문구 앞 300자를 담는다 (`ai_budget.py:61-67`).
- `refuse_over_budget`가 `tool_call_log`에 `outcome="refused"` 행을 하나 남긴다 (`ai_budget.py:70-83`). 검색/RAG의 `_logged`는 402일 때 `error` 행을 추가하지 않는다 (`ai_vectors.py:1650-1652`), `/ai/embed`도 마찬가지 (`ai_vectors.py:384-388`). tool 이름은 `ai.search`/`ai.rag`/`ai.embed`/`ai.sql` 중 호출 경로의 것 (`backend/app/tool_call_log.py:33`). 수집(`_ingest_documents`)은 `_embed`를 tool 인자 없이 부르므로 기본값 `ai.search`로 기록된다 (`ai_vectors.py:861`, 기본값 `203`).
- 경로별 결과:
  - 임베딩/검색/RAG/`/ai/embed`: 402 + refused 행.
  - RAG 답변 생성 단계에서 게이트웨이가 거절: 402 + refused 행 (`ai_vectors.py:1768-1775`).
  - NL→SQL: 사전 검사는 402 + refused 행, 게이트웨이 거절 시 `_call_litellm`은 `budget_error`만 raise (refused 행은 이 함수에서 쓰지 않음) (`ai_sql.py:247-251`).
  - 어시스턴트 채팅: `raise_for_status` 예외 → "The assistant is unavailable." **503** (`chat_routes.py:155-162`). 402로 구분되지 않는다.
  - 리랭크: 경고 로그 후 벡터 순서 결과 반환 (`ai_vectors.py:1245-1247`).
- MCP는 라우트의 4xx detail을 호출자에게 그대로 전달한다 (`backend/app/mcp/server.py:149` 부근).

### 3.3 어느 cap이 이기나 ("cap display = enforced")

- **집행**: DB(`ai_budget_caps`)에 행이 있으면 그 값, 없으면 게이트웨이 cap (`ai_budget.py:194-195`).
- **표시**: 같은 규칙. `GET /settings/ai/budgets`, `GET /settings/ai/budgets/{user_id}`, `/settings/ai/usage`의 호출자 행 모두 DB 값으로 게이트웨이 값을 덮어쓴다 (`ai_budgets.py:117-122, 150-152`; `ai_backends.py:799-806`). 게이트웨이는 cap 0을 "없음"으로 보고하므로 DB 값을 덮어써야 표시가 집행과 일치한다 (`ai_budget.py:144-149`). 첫 호출 전에 cap이 설정되어 아직 게이트웨이 customer가 아닌 호출자도 목록에 추가된다 (`ai_budgets.py:121-122`).
- DB를 읽지 못하면 목록은 빈 배열 + `unavailable`, 단건 조회는 503 (`ai_budgets.py:112-116, 146-149`).

### 3.4 설정 (누가, 어떻게)

- `PUT /api/settings/ai/budgets/{user_id}` body `{"max_budget": number|null}` (`ge=0`), **`require_admin`** (`ai_budgets.py:156-186`).
  1. 게이트웨이 `/customer/new` → 실패하면 `/customer/update`.
  2. 게이트웨이 실패 → 502 (본문은 마스터 키 일부를 포함할 수 있어 상태 코드만).
  3. `ai_budget_caps`에 upsert, `null`이면 행 삭제. DB 실패 → 500 ("게이트웨이는 받았지만 기록 못 함").
  4. 이 pod의 캐시만 삭제 (`forget_cached`). 다른 pod의 게이트웨이 수치 캐시는 최대 15초 남는다. 그래서 cap을 **해제**하면 다른 pod가 최대 15초 동안 계속 거절할 수 있다 (`docs/UPGRADING.md:285-287`).
- 조회: `GET /api/settings/ai/budgets`, `GET /api/settings/ai/budgets/{user_id}` — `spend:read` (`ai_budgets.py:91, 129-130`).
- 화면: AI Gateway › Budgets (`frontend/components/settings/caller-budgets.tsx`). admin만 편집, 에이전트(서비스 계정) 행은 여기서 읽기 전용이고 에이전트 페이지에서 설정 (`caller-budgets.tsx:28, 35-36, 64-79`). 상태 표시: `blocked` / `over`(spend ≥ cap) / `ok` / `uncapped` (`frontend/lib/caller-budgets.ts:17-21`). 입력은 0 이상 숫자 (`caller-budgets.ts:24-30`).
- **배포 기본 cap**: Helm `litellm.endUserBudgetId` → LiteLLM `litellm_settings.max_end_user_budget_id`. 자기 cap이 없는 모든 호출자에 적용 (`helm/datapond/values.yaml:991-996`, `helm/datapond/templates/litellm-deployment.yaml:38-41`). 기본값은 빈 문자열(미설정). 예산 자체는 LiteLLM `POST /budget/new`로 직접 만들어야 하며, DataPond에 이를 만드는 API는 코드에서 확인되지 않음.
- **계정 삭제 시**: 서비스 계정 삭제 시 게이트웨이 customer(지출·cap 포함) 삭제 시도 (`backend/app/api/service_account_routes.py:520-521`, `ai_budgets.py:40-61`). 게이트웨이가 마지막 호출의 비동기 기록으로 행을 되살릴 수 있어, 감사 로그 보존 작업이 최근 7일 삭제 계정에 대해 삭제를 재전송한다 (`ai_budgets.py:64-88`, `backend/app/audit_retention.py:145-149`). 이 경로에서 `ai_budget_caps` 행을 지우는 코드는 코드에서 확인되지 않음.

### 3.5 전역 예산과 가상 키 예산

- **전역 예산**: `/global/spend`가 돌려주는 `max_budget`을 읽어 표시·경고만 한다 (`ai_backends.py:704-709, 862-869`). DataPond가 전역 예산을 설정하거나 집행하는 코드는 코드에서 확인되지 않음 (LiteLLM 쪽 설정에 의존).
- **가상 키 예산**: `POST /settings/ai/keys`로 키 발급 시 `max_budget`, `rpm_limit`, `tpm_limit`, `duration`을 LiteLLM에 그대로 넘긴다 (admin, `ai_backends.py:144-152, 486-507`). 집행은 LiteLLM이 한다. `budget_alerts`는 키별 `spend/max_budget ≥ threshold%`를 경고한다.

### 3.6 키별 요청 한도 (돈이 아닌 부하 제어)

- 서비스 계정 키마다 토큰 버킷. 분당 한도는 `API_KEY_RATE_LIMIT_PER_MINUTE`(기본 600)로 **배포 전체 공통값**이며 버킷만 키별이다. 프로세스(pod)별이라 replica 2개면 최대 2배 (`backend/app/rate_limit.py:194-215`). 초과 시 429 + `Retry-After` (`docs/UPGRADING.md:424-428`). 에이전트 페이지는 이 값을 보여 주기만 한다 (`service_account_routes.py:154, 167`).

---

## 4. 임베딩·수집 등 과금되는 동작과 사전 안내

- **임베딩**: 검색 질의, RAG 질의, 수집(64개 청크 단위 배치, `ai_vectors.py:858-861`), 소스 재임베딩, `/ai/embed` 모두 `_embed` → LiteLLM `/v1/embeddings`. 성공 시 CloudWatch 메트릭 `EmbeddingCount`(개수, 주석상 "Bedrock Titan cost driver")를 내보낸다 (`ai_vectors.py:220-224`, `backend/app/metrics.py:52`). 금액이 아니라 개수다.
- **`ai.embed` 감사**: `/ai/embed`는 `ok`/`error`/`refused`(PII block 또는 cap) 행을 `tool_call_log`에 남긴다 (`ai_vectors.py:363-391`).
- **Send to Knowledge** (Catalog의 테이블 레일): 실행 전 "Up to the first 1,000 rows are read per run, and the embedding is billed to you." 문구를 보여 준다. `ROWS_PER_RUN = 1000`은 backend `SourceIngest.limit` 기본값을 프런트에 복사한 상수 (`frontend/components/catalog/table-rail.tsx:142, 250-256`). 금액 추정치는 계산하지 않는다.
- **예약 재임베딩**: 스케줄러(`app/rag_scheduler.py`)가 사용자 세션 없이 실행하므로 actor가 없고, 따라서 지출은 `unattributed`로 집계되고 cap 검사도 하지 않는다 (`ai_context.py:52-55`, `ai_budget.py:177-179`). 예약을 켜는 동작은 `ai:generate`, 끄는 동작은 `knowledge:write`만으로 가능하도록 프런트가 구분한다 (`frontend/lib/knowledge-actions.ts:71-86`, `frontend/app/knowledge/page.tsx:388-392`).
- **모델 테스트**: `POST /settings/ai/backends/{model_name}/test`는 `max_tokens: 5`의 실제 완성 호출 (admin + `ai:generate`, `ai_backends.py:411-443`). 귀속 없음(2.2 참조).
- **리랭크**: `AI_RERANK_MODEL`이 설정된 경우에만 호출, 호출자에게 귀속됨 (`ai_vectors.py:1225-1244`).
- **모델 호출 전 금액을 추정하는 로직**: 코드에서 확인되지 않음. 사전 안내는 문구뿐이다.

---

## 5. AWS 인프라 비용 (Infrastructure › Cost)

### 5.1 켜는 조건과 권한

- `AWS_INFRA_ENABLED`가 참일 때만 동작, 아니면 라우트가 404 (`backend/app/aws_infra.py:36-37`, `backend/app/api/infra_aws.py:32-34`). Helm `backend.awsInfra.enabled`(기본 false, `values-prod-single.yaml`에서 true)와 `namePrefix`(기본 `datapond`) → `AWS_INFRA_ENABLED`, `AWS_INFRA_NAME_PREFIX` (`helm/datapond/values.yaml:170-174`, `values-prod-single.yaml:88-92`, `templates/backend-deployment.yaml:300-303`).
- IAM: 노드 역할에 `InfraRead`(`ce:GetCostAndUsage` 포함), `InfraReadScoped`, `InfraManage` (`terraform/iam.tf:121-150`). 거절된 호출은 이름으로 `missing`에 모이고 나머지는 계속 채워진다 (`aws_infra.py:69-91`).
- 화면: `/services?tab=cost`, AWS 기능이 켜졌을 때만 (`frontend/app/services/page.tsx:21`).
- API 권한: `GET /api/infra/cost`, `GET /api/infra/aws`는 `require_admin`; `PUT /api/infra/budget`, `/infra/aurora-capacity`, `/infra/schedule`는 `settings:write` (`infra_aws.py:65, 93, 116, 140, 161`). `settings:write`는 admin만 가지며 서비스 계정은 가질 수 없으므로 실질적으로 사람 admin 전용.

### 5.2 사용량 수집 (`aws_infra.gather`, 5분 캐시)

`gather()`가 한 번에 읽는 것 (`aws_infra.py:118-250`), `snapshot()`이 5분(`CACHE_SECONDS = 300`) 캐시 (`aws_infra.py:29, 278-287`), `?refresh=true`면 강제 갱신.

| 항목 | 출처 | 비고 |
|---|---|---|
| 노드 타입·Spot 여부·볼륨 크기 | `ec2:DescribeInstances`, `DescribeVolumes` | 인스턴스 id는 인스턴스 메타데이터 |
| 노드 시간당 가격 | Spot: `DescribeSpotPriceHistory` 이번 달(최대 30일) 가격들의 **단순 평균**. On-demand: `ON_DEMAND_HOURLY` 표 | 표에 없는 타입이면 `None` (`aws_infra.py:150-163`) |
| 노드 가동 시간 | CloudWatch `CPUUtilization` 1시간 데이터포인트의 개수 | 데이터포인트 하나 = 가동 1시간 (`aws_infra.py:238`) |
| Aurora ACU | `AWS/RDS ServerlessDatabaseCapacity` 1시간 평균 | |
| Aurora 저장량 | `VolumeBytesUsed` 일 평균 / 1e9 | |
| Aurora min/max ACU | `rds:DescribeDBClusters` | |
| S3 크기 | `AWS/S3 BucketSizeBytes` (StandardStorage) | 버킷은 `GLUE_WAREHOUSE`/`ICEBERG_WAREHOUSE`에서 추출 |
| 알람·대시보드·커스텀 메트릭 수 | `DescribeAlarms`, `ListDashboards`(prefix), `ListMetrics`(`CLOUDWATCH_METRICS_NAMESPACE`, 기본 `DataPond`) | |
| 시크릿 수 | `secretsmanager:ListSecrets` (이름 필터 prefix, 최대 100) | |
| 공인 IP | 노드에 public IP가 있으면 1 | |
| Hosted zone | `APP_BASE_URL`이 `https://`로 시작하면 1 | 실제 Route 53 조회 아님 |
| 시작/정지 스케줄 | `scheduler:GetSchedule` | 편집 가능할 때만 추정에 사용 |

AI 지출은 `infra_aws._ai_spend()`가 LiteLLM `/spend/logs`를 읽어 `(startTime, spend)` 목록으로 만든다 (`infra_aws.py:72-90`). 실패하면 빈 목록.

### 5.3 단가 (`PRICES`, 하드코딩)

us-east-1 정가, 코드 주석 "Checked 2026-11" (`backend/app/aws_cost.py:22-45`).

| 키 | USD |
|---|---|
| `aurora_acu_hour` | 0.12 |
| `aurora_storage_gb_month` | 0.10 |
| `gp3_gb_month` | 0.08 |
| `public_ipv4_hour` | 0.005 |
| `hosted_zone_month` | 0.50 |
| `cw_alarm_month` | 0.10 |
| `cw_dashboard_month` | 3.00 (계정당 3개 무료) |
| `cw_metric_month` | 0.30 (10개 무료) |
| `secret_month` | 0.40 |
| `s3_gb_month` | 0.023 |

`ON_DEMAND_HOURLY`: t3/t3a/m6i/m7i/r6i의 large·xlarge·2xlarge 15종 (`aws_cost.py:39-45`). 리전과 무관하게 이 값을 쓴다.

집계하지 않는 항목(`NOT_COUNTED`, 화면에도 표시): data transfer out, 무료 보존 초과 백업, ECR 저장소, KMS, support plan, 세금, 크레딧 (`aws_cost.py:47-48`).

### 5.4 추정식 (`aws_cost.estimate`)

기호: 월 경계는 UTC 기준 그 달 1일~다음 달 1일 (`month_bounds`, `aws_cost.py:147-150`). `elapsed_h = max(경과 시간, 1)`, `total_h = 그 달 총 시간`, `remaining_h = total_h − elapsed_h`, `month_frac = elapsed_h / total_h` (`aws_cost.py:168-172`).

- **Aurora** (`aws_cost.py:175-182`)
  - `acu_hours` = 이번 달 시간별 평균 ACU의 합
  - `acu_rate` = 최근 7일 시간별 ACU 평균 (없으면 `acu_hours/elapsed_h`, 그것도 없으면 `min_acu`)
  - `storage_month = storage_gb × 0.10`
  - MTD = `acu_hours × 0.12 + storage_month × month_frac`
  - 예측 = MTD + `acu_rate × remaining_h × 0.12` + `storage_month × (1 − month_frac)`
- **EC2 노드 + 볼륨** (`aws_cost.py:184-191`)
  - `volume_month = volume_gb × 0.08`
  - MTD = `가동시간 × hourly_price + volume_month × month_frac`
  - 예측 = MTD + `지금~월말 스케줄상 가동 시간 × hourly_price` + `volume_month × (1 − month_frac)`
  - 스케줄상 가동 시간은 1시간 단위로 스케줄 시간대(tz, 기본 UTC)에서 요일·시각을 판정해 센다 (`scheduled_hours_between`, `aws_cost.py:124-142`). 스케줄이 없거나 꺼져 있으면 24/7.
- **고정비 항목** (월액 `m`에 대해 MTD = `m × month_frac`, 예측 = `m`) (`aws_cost.py:193-206`)
  - 네트워크 = `public_ips × 0.005 × total_h + hosted_zones × 0.50`
  - CloudWatch = `alarms × 0.10 + max(dashboards − 3, 0) × 3.00 + max(custom_metrics − 10, 0) × 0.30`
  - Secrets Manager = `secrets × 0.40`
  - S3 = `s3_gb × 0.023`
- **"Bedrock"** (`aws_cost.py:201-203, 216-217`): MTD = 이번 달 LiteLLM spend 합, 예측 = `MTD / month_frac` (선형 외삽). LiteLLM 전체 spend를 쓰므로 Bedrock이 아닌 모델의 지출도 이 줄에 들어간다.
- 합계: 서비스별 MTD·예측의 합, 예측 큰 순으로 정렬 (`aws_cost.py:221-223`).
- **일별 시리즈** (`aws_cost.py:225-243`): 오늘까지는 측정값(ACU×0.12, 가동시간×가격), 이후는 `acu_rate × 24 × 0.12`와 스케줄상 가동 시간×가격. `other` = (네트워크+CW+시크릿+S3+볼륨+Aurora 저장소 월액)/(그 달 일수) + AI(과거는 실제, 미래는 `ai_fc/일수`).

### 5.5 절감 여지 (`aws_cost.savings`, 한 달 = 730시간 고정)

(`aws_cost.py:256-280`)

- `aurora_idle_floor = min_acu × 0.12 × 730` — 아무것도 안 해도 나가는 Aurora 최소 비용.
- `run_frac = 주당 가동시간 / 168` (`weekly_hours`: 스케줄 없음/꺼짐 = 168, 정지 시각 ≤ 시작 시각이면 +24로 자정 넘김 처리, `aws_cost.py:109-121`).
- `spot_vs_on_demand = (on_demand − hourly_price) × 730 × run_frac` — Spot이고 타입이 표에 있을 때만.
- `schedule_saves = (1 − run_frac) × 730 × hourly_price` — 스케줄이 이미 아끼고 있는 금액.

### 5.6 실제 비용 (`aws_infra.actual_costs`, Cost Explorer)

(`aws_infra.py:301-339`)

- `ce:GetCostAndUsage`, 리전 us-east-1 고정, 기간 = 이번 달 1일 ~ min(내일, 다음 달 1일), `MONTHLY`, `UnblendedCost`, 필터 `Tags: Project = <AWS_INFRA_NAME_PREFIX>`, 서비스(SERVICE)별 그룹.
- 6시간 캐시 (`CE_CACHE_SECONDS`, 주석: 요청당 $0.01, `aws_infra.py:30`). 이 캐시는 `refresh=true`로도 우회되지 않는다(`actual_costs`에 강제 인자 없음).
- 합계가 0보다 클 때만 `active: true`와 서비스별 금액·합계를 반환. 0이면 태그가 아직 비활성이라고 보고 `active: false` → 화면은 추정치 모드.
- 오류 메시지에 "Payer account"와 "linked account"가 함께 있으면 IAM 문제가 아니라 조직의 관리(payer) 계정이 Cost Explorer를 공유하지 않은 것으로 보고 `blocked: "payer"` (`aws_infra.py:80-83, 324-325`).
- Terraform은 provider default tag로 `Project = var.name_prefix`를 붙인다 (`terraform/main.tf:26`). 비용 할당 태그 활성화는 결제 계정에서 사람이 해야 한다.

### 5.7 `/api/infra/cost` 응답과 화면

`infra_cost()`가 snapshot, AI spend, Cost Explorer, 예산 설정을 병렬로 읽고 `estimate`를 계산해 반환한다 (`infra_aws.py:93-108`). 응답: `services`, `total{mtd,forecast}`, `daily`, `savings`, `not_counted`, `actual`, `budget`, `budget_usd`, `missing`, `read_at`, `aurora`, `node`, `schedule`.

화면(`frontend/components/infra/cost-panel.tsx`):

- 상단 문구: `actual.active`면 "Actual — Cost Explorer reports $X billed this month…", 아니면 "Estimated from what each resource used…" (`cost-panel.tsx:171-174`).
- 타일 (`cost-panel.tsx:177-183`):
  - Month to date = `actual.active`면 Cost Explorer 합계, 아니면 추정 MTD.
  - `<월> forecast` = **항상 추정 예측**.
  - Budget = `budget.pct`% 또는 "Not set", 초과 시 경고색.
  - "AI models (in the total)" = 추정의 `bedrock` 항목 MTD, AI Gateway Spend로 링크 (`cost-panel.tsx:143`).
- "Turn on actual costs" 안내(태그 활성화 3단계, payer 차단 시 별도 문구) (`cost-panel.tsx:256-267`).
- 권한 누락 문장: `missingSentence` (`frontend/lib/aws-infra.ts:136-140`).

### 5.8 월 예산과 Overview 이슈

- 설정: `PUT /api/infra/budget` body `{"usd": number|null}`. `0 < usd ≤ 1,000,000`이 아니면 400, `null`이면 해제. `system_settings`의 키 `infra.monthly_budget_usd`에 JSON으로 저장 (`infra_aws.py:28, 47-53, 157-167`). 화면 폼 `cost-panel.tsx:105-120`.
- 판정 `budget_state(forecast, budget)`: 예산이 없거나 ≤ 0이면 `None`, 아니면 `pct = round(forecast/budget×100)`, `over = forecast > budget` (`aws_cost.py:283-288`). 비교 대상은 **추정 예측**이며 Cost Explorer 실제값이 아니다 (`infra_aws.py:100-101`).
- Overview 연결: `/infra/cost`가 호출될 때마다 초과 상태를 모듈 변수 `_last_budget`에 저장하고 (`infra_aws.py:102-103, 181-187`), `GET /api/ops/status`가 **admin에게만** `{"kind": "cost_over_budget", forecast, budget, pct}` 이슈를 추가하고 상태를 `attention`으로 바꾼다 (`backend/app/api/ops.py:149-154`). 프런트 문구: "AWS cost forecast is over budget (N%)", "Open Cost" 링크 (`frontend/lib/ops-status.ts:23, 122-127`).
- 예산 초과 시 리소스를 멈추거나 호출을 막는 동작은 없다. 알림 전송(메일 등)도 코드에서 확인되지 않음.

### 5.9 프런트 미리보기 계산 (`frontend/lib/aws-infra.ts`)

저장 전 폼에서 보여 주는 값으로, backend 추정과 별개다.

- 상수 `ACU_HOUR = 0.12`, `MONTH_HOURS = 730`, Aurora 선택지 min `[0, 0.5, 1, 2]` / max `[2, 4, 8, 16]` (`aws-infra.ts:9-12`, backend `aws_infra.py:344-345`와 같은 값).
- `weeklyHours(days, start, stop, enabled)`: 꺼짐 = 168, 정지 ≤ 시작이면 **0** (`aws-infra.ts:90-95`). backend `weekly_hours`는 같은 경우 +24로 처리하므로 다르다. 다만 `scheduleProblem`이 "Stop must be later in the day than start."로 그런 입력을 막는다 (`aws-infra.ts:98-105`).
- `scheduleDelta(from, to, hourly) = (to − from)/168 × 730 × hourly` (`aws-infra.ts:108-111`).
- `auroraIdle(minAcu) = minAcu × 0.12 × 730` (`aws-infra.ts:114-116`).
- 기타: `money`, `share`(예측 대비 비율), `niceMax`(차트 축), `dayTotal`, `stopsToday`.

### 5.10 AWS 비용과 관련된 쓰기 동작

비용에 영향을 주는 콘솔 변경은 두 가지뿐이다 (`aws_infra.py:1-11`).

- Aurora 용량 범위 `PUT /api/infra/aurora-capacity` (`settings:write`, `rds:ModifyDBCluster`).
- 노드 시작/정지 스케줄 `PUT /api/infra/schedule` (`settings:write`, `scheduler:UpdateSchedule`). 저장 시 `system_settings`의 `infra.expected_starts`와 환경변수 `SYSTEM_EVENTS_EXPECTED_STARTS`도 갱신 (`infra_aws.py:29, 140-154, 170-178`).

---

## 6. 설정·키·환경변수·마이그레이션·권한 요약

| 이름 | 종류 | 용도 | 위치 |
|---|---|---|---|
| `LITELLM_URL`, `LITELLM_MASTER_KEY` | env / 시크릿 | 지출·cap 조회와 설정에 쓰는 게이트웨이 관리 API | `ai_backends.py:107-113` |
| `LITELLM_MODEL` | env | RAG/SQL/채팅 생성 모델 이름 | `ai_vectors.py:1741` 부근 |
| `AI_RERANK_MODEL` | env | 리랭크 모델 (비면 호출 안 함) | `ai_vectors.py:1225-1228` |
| `API_KEY_RATE_LIMIT_PER_MINUTE` | env (기본 600) | 키별 요청 버킷의 분당 한도 | `rate_limit.py:211-213` |
| `litellm.endUserBudgetId` | Helm | 배포 기본 호출자 cap (LiteLLM budget id) | `values.yaml:991-996` |
| `ai_budget_caps` | 테이블 (migration 0024) | DataPond가 설정한 호출자 cap, 모든 pod 공유 | `backend/migrations/versions/0024_ai_budget_caps.sql` |
| `tool_call_log` | 테이블 | 402 거절의 `refused` 행 | `backend/app/tool_call_log.py` |
| `AWS_INFRA_ENABLED`, `AWS_INFRA_NAME_PREFIX` | env (Helm `backend.awsInfra`) | Cost 탭 활성화, 리소스·태그 prefix | `aws_infra.py:36-41` |
| `AWS_INFRA_DB_CLUSTER`, `POSTGRES_HOST` | env | Aurora 클러스터 식별 | `aws_infra.py:44-52` |
| `GLUE_WAREHOUSE` / `ICEBERG_WAREHOUSE` | env | S3 버킷 식별 | `aws_infra.py:55-58` |
| `CLOUDWATCH_METRICS_NAMESPACE` | env (기본 `DataPond`) | 커스텀 메트릭 수 집계 | `aws_infra.py:218` |
| `APP_BASE_URL` | env | hosted zone 1개 여부 추정 | `aws_infra.py:244` |
| `infra.monthly_budget_usd` | `system_settings` 키 | AWS 월 예산 | `infra_aws.py:28` |
| `infra.expected_starts` | `system_settings` 키 | 스케줄 기반 예상 부팅 | `infra_aws.py:29` |
| `ai:generate` | 권한 | 토큰을 쓰는 모든 동작, 본인 지출 조회 | `permissions.py:36` |
| `spend:read` | 권한 | 전체 지출·cap 조회 | `permissions.py:45` |
| `settings:write` | 권한 | AWS 예산·용량·스케줄 변경 | `permissions.py:46` |
| admin (`require_admin`) | 역할 | 호출자 cap 설정, 가상 키, `/infra/cost`·`/infra/aws` 조회, Overview 비용 이슈 | 각 라우트 |

---

## 7. 한계와 확인 필요 사항

### 7.1 AI 지출

1. **모델 단가는 LiteLLM의 계산에 전적으로 의존한다.** DataPond에는 모델 가격표가 없고, LiteLLM이 0으로 기록하는 모델(가격 정보 없는 로컬 모델 등)은 0으로 보인다.
2. **`/spend/logs`를 기간 인자 없이 매번 통째로 읽는다** (`ai_backends.py:663, 685, 718`, `infra_aws.py:78`). LiteLLM이 몇 건까지 돌려주는지(페이지네이션/상한)는 코드에서 확인되지 않음. 기록이 많아지면 본인/에이전트 지출, 토큰 집계, AWS 추정의 AI 항목이 잘리거나 느려질 수 있다. `usage_summary` 주석도 "recent"라고만 적는다 (`ai_backends.py:715`).
3. **"전체 지출" 숫자가 화면마다 출처가 다르다.** Overview와 AI Gateway Spend는 `/global/spend`(게이트웨이 전체), 어시스턴트 `spend.summarize`는 `/settings/ai/spend`(가상 키 합)다. 프런트 주석은 후자가 "$0.30을 쓴 배포에서 $0.00을 읽었다"고 적고 있다 (`frontend/lib/dashboard-activity.ts:77-79`). 그런데 `spend.summarize`는 여전히 가상 키 합을 쓴다 (`chat/analysis/spend.py:22-24, 154-156`).
4. **cap 사전 검사가 모든 모델 호출에 걸리지 않는다.** 어시스턴트 채팅, 리랭크, 모델 테스트는 게이트웨이 검사만 받는다. 채팅은 cap에 걸려도 402가 아니라 503 "assistant unavailable"을 돌려준다 (`chat_routes.py:158-162`).
5. **게이트웨이에 접근할 수 없으면 사전 검사는 통과시킨다** (`ai_budget.py:114-116, 190-192`). DB cap이 0인 경우만 게이트웨이 없이 거절한다.
6. **pod별 15초 캐시**: cap 해제 직후 다른 pod가 최대 15초 더 거절할 수 있다. spend도 15초 지연된다.
7. **0024 이전에 게이트웨이에만 설정된 cap**은 DB에 행이 없으므로 pod별 캐시 동작을 그대로 가진다. 다시 저장해야 DB에 기록된다 (`docs/UPGRADING.md:282-285`).
8. **귀속 누락**: 백그라운드 재임베딩과 모델 테스트는 `unattributed`이고 cap 대상이 아니다. 백그라운드 재임베딩 비용에 상한을 거는 장치는 코드에서 확인되지 않음.
9. **per-collection 지출**: 집계도 화면도 없다. LiteLLM에 컬렉션 정보가 전달되지 않는다.
10. **수집 경로의 refused 행 tool 이름이 `ai.search`로 기록된다** (`ai_vectors.py:861`). 감사 로그에서 수집 거절을 검색 거절과 구분할 수 없다.
11. **NL→SQL의 게이트웨이 단계 거절**은 `_call_litellm`에서 `refused` 행을 쓰지 않는다 (`ai_sql.py:247-251`). 상위에서 기록하는지는 코드에서 확인되지 않음.
12. **예산 알림 전달**: 임계치 경고는 화면 표시뿐이다. 메일/웹훅 전달은 README에서도 미구현 항목으로 남아 있다 (`README.md:181` "Durable budget notification delivery").
13. **가상 키**: 가상 키로 게이트웨이를 직접 부르면 DataPond의 귀속·cap·감사·ACL을 모두 우회한다 (`docs/UPGRADING.md:230-233`).

### 7.2 AWS 비용

1. **단가 하드코딩, us-east-1 기준.** 노드가 다른 리전에 있어도 같은 단가를 쓴다. 가격 API 조회는 없다 (`aws_cost.py:22-45`).
2. **Spot 가격은 실제 지불액이 아니라 가격 이력의 단순 평균**이다 (`aws_infra.py:150-158`). 시간 가중이 아니고, 이력 페이지 상한은 200건이다.
3. **가동 시간 = CPU 메트릭 데이터포인트 수**라는 근사 (`aws_infra.py:238`). 메트릭 누락이나 부분 가동 시간은 반영되지 않는다.
4. **ON_DEMAND_HOURLY에 없는 인스턴스 타입**이면 on-demand 노드의 시간당 가격이 `None`이 되고 EC2 비용이 0(볼륨만)으로 계산되며 Spot 절감 문장도 빠진다.
5. **"Bedrock" 줄은 LiteLLM 전체 지출**이라 Bedrock이 아닌 모델 비용도 포함된다. 예측은 단순 선형 외삽 (`aws_cost.py:201-203`).
6. **Hosted zone은 `APP_BASE_URL`이 https인지로 추정**하며 Route 53을 조회하지 않는다 (`aws_infra.py:244`). 시크릿 수는 최대 100개까지만 센다.
7. **집계 제외 항목**(데이터 전송, 백업, ECR, KMS, 지원, 세금, 크레딧)은 추정에 없다. 화면에 명시된다.
8. **예산 판정은 추정 예측 기준**이다. Cost Explorer가 활성이어도 Budget 타일과 Overview 이슈는 추정 예측과 비교한다 (`infra_aws.py:100-101`). Month to date 타일만 실제값으로 바뀐다.
9. **Overview 초과 이슈는 마지막 Cost 탭 조회 결과**를 pod 메모리(`_last_budget`)에 둔다. 누군가 Cost 탭을 열기 전, pod 재시작 후, 또는 다른 pod가 응답할 때는 나타나지 않을 수 있다 (`infra_aws.py:181-187`).
10. **Cost Explorer 6시간 캐시는 새로고침으로 우회되지 않는다**(pod별). 태그 활성화 후 최대 24시간 + 캐시 6시간이 걸릴 수 있다.
11. **Linked account의 payer 차단**은 오류 메시지 문자열("Payer account", "linked account")로 판정한다 (`aws_infra.py:80-83`). AWS가 문구를 바꾸면 일반 오류로 떨어진다.
12. **Cost Explorer 합계 0 = 비활성**으로 본다 (`aws_infra.py:333`). 실제 청구가 0인 달 초에도 추정 모드로 표시된다.
13. **월 경계는 UTC**다. KST 기준 월초 9시간은 이전 달로 계산된다 (`aws_cost.py:147-150`).
14. **프런트 `weeklyHours`와 backend `weekly_hours`의 자정 넘김 처리가 다르다** (5.9). 현재는 폼 검증이 그런 입력을 막아 차이가 드러나지 않는다.

### 7.3 코드와 문서가 맞지 않는 곳

1. `docs/UPGRADING.md:230-237`은 "Virtual Keys & Budgets (AI Gateway) is removed"이고 `/api/settings/ai/keys`가 다음 릴리스에서 제거될 것이라고 적는다. 그런데 코드에는 AI Gateway의 admin 전용 **Keys 탭**(`frontend/app/ai/page.tsx:19, 54, 62`, `frontend/components/ai/virtual-keys.tsx`)과 라우트(`ai_backends.py:448-527`)가 그대로 있다.
2. `docs/UPGRADING.md:249-251`은 "a service account's own spend stays on its row in Settings → Service accounts"라고 적지만, 같은 문서 216-221행과 코드상 서비스 계정 지출은 Agents 페이지(`spend-section.tsx`)에 있다.
3. `frontend/app/knowledge/page.tsx:219-222` 주석은 개인 지출이 Knowledge 페이지에 있다고 하지만, 실제 `MySpend`는 `/account`에만 렌더링된다 (`frontend/app/account/page.tsx:102`).
4. `docs/ARCHITECTURE.md:142`와 CLAUDE.md의 "actor identity → LiteLLM `user`/metadata → usage and spend aggregation"에서 metadata의 사용자 정보는 LiteLLM이 덮어써서 남지 않는다. 실제 귀속은 `user`(→ `end_user`)만, 기능 구분은 `metadata.tags`(→ `request_tags`)만 쓴다 (`ai_context.py:34-48`).
5. CLAUDE.md는 서비스 계정 키에 "per-key rate limit"이 있다고 적는다. 실제로는 버킷만 키별이고 한도 값은 배포 전체 공통(`API_KEY_RATE_LIMIT_PER_MINUTE`)이며, pod별이라 replica 수만큼 배가된다 (`rate_limit.py:194-215`).
6. `aws_cost.py:5` 모듈 docstring은 "the Spot price the node actually paid"라고 적지만, 실제 값은 Spot 가격 이력의 평균이다 (`aws_infra.py:150-158`).
7. `ai_backends.py:407-410` 주석은 모델 테스트 호출이 "다른 호출처럼 과금된다"고 한다. 과금은 맞지만 actor 귀속이 없어 호출자별 집계에는 잡히지 않는다.
