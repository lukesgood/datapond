# 포지셔닝 적합도 점검 — 기능·사용성 vs v6.0

> 점검일: 2026-09-07 · 기준 커밋: `1b19d38` (main) · 대상: `PRODUCT_CONCEPT.md` v6.0 한 문장
> **§6에 트렌드 조정 이후 문장에 대한 갭 분석, §7에 최종 포지셔닝(§6.1 적용 이후) 기준 축별 보유
> 항목 갭 분석을 추가했다.** §7이 현재 시점의 종합이다. §1~§5는 오전의 초안 문장 기준이며 판정은
> 그대로 유효하다.
> 방식: 문장을 여덟 개 주장으로 나누고, 각 주장을 코드·마이그레이션·Helm·프런트엔드와 대조했다.
> 라이브 호출은 하지 않았다. 모든 근거는 `path:line`으로 남긴다.

## 1. 결론

**새 문장은 "거의 맞지만 세 군데에서 거짓"이다.** 도구 면, 호출자 식별, 컬렉션 ACL, PII 마스킹,
spend 귀속은 실제로 있다. 그러나 문장이 약속하는 "호출자 단위 **감사**"는 에이전트가 실제로
부르는 네 엔드포인트의 성공 호출을 기록하지 않고, "**비용 통제**"는 조회일 뿐 강제가 아니며, UI는
아직 열두 곳에서 "Portable AI Data Foundation"이라고 말한다.

| 주장 | 판정 | 한 줄 요약 |
|---|---|---|
| 에이전트·앱이 접근한다 | **부분** | 서비스 계정 키·스코프·만료는 있음. UI가 발급하는 키는 스코프가 비어 role 전체 권한 |
| 인용 RAG·governed SQL을 도구로 | **부분** | 4개 엔드포인트 있음. 인용에 chunk id·URI 없음, `/connect`는 `/api/ai/*`만 노출, MCP 없음 |
| 호출자 단위 접근 | **대체로 충족** | 멤버 ACL이 서비스 계정에도 적용. 키를 컬렉션·테이블에 직접 묶지는 못함 |
| PII 마스킹 | **부분** | 적재·검색·인용은 마스킹. `/queries/execute` 결과 행과 `/ai/sql` 출력은 미검사 |
| 감사 | **미충족** | 권한 거부·쓰기 허용만 기록. 성공한 search/rag/sql/query는 무엇을 물었는지 남지 않음 |
| 비용 통제 | **부분** | 호출자별 귀속·조회는 됨. 어떤 호출도 예산으로 거부되지 않음 |
| AWS 위에서 바로 운영 | **충족** | 단일 노드·업무시간 제약은 문서화됨 |
| 잠기지 않음 | **설계만** | 계약은 있음. export CLI·exit drill 없음 (이미 roadmap 표기) |

사용성은 **"운영자가 RAG를 만드는 제품"의 여정**이지 **"에이전트에 도구를 열어주는 제품"의
여정**이 아니다. 첫 화면·IA·도움말 어디에도 "당신의 에이전트를 연결하라"는 문장이 없다.

## 2. 주장별 근거

### 2.1 에이전트·앱이 접근한다 — 부분

있는 것:

- 서비스 계정은 `users` 행(`auth_method='service'`) — `backend/app/service_accounts.py:8-16`
- 키 `dp_sk_…`, SHA-256 저장, 상수 시간 비교 — `service_accounts.py:25,49-62`
- 권한 = role ∩ 요청 스코프, `user:manage`·`settings:write` 제외, 절대 넓어지지 않음 —
  `service_accounts.py:34-37,74-85`; 아무 권한도 없는 키는 발급 거부 —
  `backend/app/api/service_account_routes.py:126-130`
- 만료 1~3650일 옵션, 인증 시 강제 — `service_account_routes.py:33,134-136`, `api/auth.py:1135-1136`
- `admin` role 서비스 계정 거부 — `service_account_routes.py:85-89`; 키로 키를 만들 수 없음 —
  `api/auth.py:349-354`

없는 것:

- **UI가 발급하는 키는 `scopes: []`** — `frontend/components/settings/service-accounts.tsx:71`.
  즉 화면에서 만든 키는 role 전체 권한이다. "스코프로 좁힌 키"는 API로만 가능하다.
- 키 회전 없음(발급·폐기만) — `service_account_routes.py:113,153-166`
- API 키 호출에 rate limit 없음. `rate_limit.py:31-36`은 로그인 전용이고 유일한 호출처가
  `api/auth.py:583,644-647`
- SDK·클라이언트 없음. `/openapi.json`·`/docs`는 FastAPI 기본값이며 `/api/` 밖이라 **인증 없이
  열려 있음** — `backend/main.py:52-56,93-94`

### 2.2 인용 RAG·governed SQL을 도구로 — 부분

있는 것:

- `POST /api/ai/search`(`ai:generate`) — `backend/app/api/ai_vectors.py:1282-1299`, k≤50
- `POST /api/ai/rag` — `ai_vectors.py:1302-1378`, `[n]` 인용, LLM 실패 시 hit만 반환
- `POST /api/ai/sql` — `backend/app/api/ai_sql.py:352-376`, 생성만
- `POST /api/queries/execute`(`query:run`, 쓰기 문장은 `query:write`) — `backend/app/api/queries.py:199,231-239`
- `/connect` 페이지: 실행 중인 라우트에서 생성된 목록 + `Bearer $DATAPOND_KEY` curl 예시 —
  `frontend/app/connect/page.tsx:44-51,164-177`
- 도구 정의 생성기가 이미 있음: `tool_definitions`가 pydantic 스키마에서 Anthropic 형식
  `name/description/input_schema`를 만든다 — `backend/app/chat/actions.py:131-152`

없는 것:

- 인용 hit는 `source, chunk_index, content, metadata, score`뿐. **chunk id·URI 없음** —
  `ai_vectors.py:1121-1125`. 에이전트가 근거를 되짚거나 dedupe할 안정 키가 없다.
- 스트리밍 없음(단일 `httpx.post`) — `ai_vectors.py:1362-1367`
- `/connect`의 목록은 `/api/ai/*`로 한정 — `backend/app/api/api_surface.py:19`. 따라서
  `/queries/execute`와 컬렉션 목록은 "도구 면"에서 보이지 않는다.
- MCP·webhook·도구 스키마 export 없음. `tool_calls` 파싱은 내부 어시스턴트 인바운드뿐 —
  `backend/app/api/chat_routes.py:340,382`

### 2.3 호출자 단위 접근 — 대체로 충족

- 규칙: admin → owner → member(reader/editor) → `owner_id IS NULL`이면 `knowledge:read` 보유자 전체 —
  `backend/app/resource_access.py:111-139`
- 멤버 테이블 `ai_collection_members` — `backend/migrations/versions/0003_collection_members.sql:5-25`.
  **그룹·팀 단위 없음**, 사용자 id 단위만.
- 서비스 계정도 동일 규칙(owner·member 가능), 키 권한이 `_holds`의 정본 — `resource_access.py:99-108`
- 단, admin 우회는 **role 문자열**로 판단해 키 스코프로 좁혀지지 않음 — `resource_access.py:79-84`
  (`admin` 서비스 계정은 생성 자체가 거부되므로 실제 노출은 제한적)
- 테이블 쪽은 RLS/마스킹이 서비스 계정 user 행 기준으로 적용 — `backend/app/rls/loader.py:41-62`
- 키를 컬렉션·테이블에 **직접** 묶는 필드는 없다. 간접(멤버십·RLS)만 가능.

### 2.4 PII 마스킹 — 부분

- 엔진은 한국형 구조화 regex 6종 + RRN·Luhn 체크섬, NER 없음 — `backend/app/guardrails/pii_ko.py:7,26,39,55-66`
- 적재 시 마스킹 — `ai_vectors.py:1092-1119`; 검색·인용 재마스킹 — `ai_vectors.py:1080-1132`
- `/ai/sql`은 질문·컨텍스트만 마스킹, 생성된 SQL·설명은 재검사 안 함 — `ai_sql.py:380-392`
- **`/queries/execute` 결과 행은 어디서도 PII 검사 없음** — `queries.py` 전체
- 모드는 전역 env 하나(`PII_GUARDRAIL_MODE`, 기본 mask) — `pii_ko.py:100-101`. 호출자·컬렉션별 정책 없음.
  유일한 리소스별 설정은 커넥터의 `pii_columns` — `backend/app/connectors/database.py:57-79`

### 2.5 감사 — 미충족

- `security_audit.py`는 **권한 결정만** 기록: 모든 거부 + `:write`형 허용 + `user:manage`/`service:manage` —
  `backend/app/security_audit.py:53-61`. `query:run`·`ai:generate` 허용은 **의도적으로 미기록** — `:16-28`
- 따라서 키를 가진 에이전트의 성공한 `/ai/search`·`/ai/rag`·`/ai/sql`·`/queries/execute`는 감사 행이 0건이다.
  무엇을 물었고, 어느 컬렉션을 읽었고, 무엇이 인용됐는지 남지 않는다.
- 쿼리 이력은 호출자가 끌 수 있음(`save_history` 요청 필드) — `backend/app/schemas/query.py:13`,
  `queries.py:312,336`. 에이전트가 자기 흔적을 지울 수 있다.
- DDL 거부는 인라인 403이라 `security_audit_log`에 남지 않음 — `queries.py:192-197`
- append-only는 트리거 + REVOKE UPDATE로 실재 — `migrations/versions/0005_audit_append_only.sql:27-60`.
  단 앱 role이 테이블 owner라 WORM이 아니라고 파일 스스로 명시 — `:4-24`
- export는 NDJSON 스트림, `audit:read` — `backend/app/api/audit_export.py:34-64`

이 항목이 문장과 가장 크게 어긋난다. "호출자 단위 감사"는 지금 "호출자 단위 권한 거부 감사"다.

### 2.6 비용 통제 — 부분

- 호출자 id가 LiteLLM `end_user`로 전달 — `backend/app/ai_context.py:23-56`; search/rag/sql/chat 전부 호출 —
  `ai_vectors.py:1283,1305`, `ai_sql.py:378`, `chat_routes.py:124`
- 서비스 계정별 usage 조회 엔드포인트 — `backend/app/api/ai_backends.py:530-556`
- 예산은 LiteLLM 가상 키 속성일 뿐 — `ai_backends.py:123,415-421`. `api_keys`에 예산 컬럼 없음.
  **LLM 호출 전에 spend를 확인하는 코드가 없다.** 거부되는 요청은 없다.
- 호출당 rate limit 없음(2.1 참조)

### 2.7 AWS 위에서 바로 운영 — 충족

- `values-prod-single.yaml` Terraform reference, 라이브 가동 중(평일 07:30~18:00 KST) —
  `OPERATIONS_PAUSE.md`. 제약은 문서화돼 있으므로 문장과 어긋나지 않는다.

### 2.8 잠기지 않음 — 설계만

- 계약은 `ARCHITECTURE.md` §3. export/import CLI·exit drill은 `PORTABILITY.md`에 roadmap으로 명시.
  v6.0은 이를 헤드라인에서 내렸으므로 과대주장은 아니다.

## 3. 사용성 점검 — 여정이 옛 문장을 따른다

### 3.1 UI 카피가 v5.0이다

"Portable AI Data Foundation"과 그 파생어가 남아 있는 곳:

| 위치 | 파일 |
|---|---|
| 브라우저 제목 | `frontend/app/layout.tsx:14` |
| 사이드바 로고 부제(모든 페이지) | `frontend/components/app-sidebar.tsx:151` |
| 로그인 로고·푸터·모바일 | `frontend/app/login/page.tsx:269,302,318` |
| 비밀번호 찾기·재설정 | `frontend/app/forgot/page.tsx:55,66,80`, `frontend/app/reset/page.tsx:79,90,104` |
| 대시보드 H1 **"Foundation health"** | `frontend/app/dashboard/page.tsx:168` |
| Operate 그룹 힌트 "Govern and run the foundation" | `app-sidebar.tsx:94` |
| 여정 스트립 "Portable core workflow" | `frontend/components/dashboard/journey-strip.tsx:77` |
| 문서 페이지 프레임 | `frontend/app/docs/[slug]/page.tsx:26-129`, `components/docs/docs-index.tsx:60-153` |

로그인 히어로 "Governed AI. Without the lock-in."(`login/page.tsx:283-285`)은 v6.0과 호환된다.
`product-profile.ts`의 "Portable Core" 프로필 라벨은 배포 프로필 이름이므로 유지해도 된다.

### 3.2 첫 여정이 "앱 연결"에서 끝나지 않는다

- 온보딩·체크리스트·빈 상태 없음. 신규 admin은 "Overview / Foundation health" + 상태 문장 +
  여정 스트립 + 통계 + 서비스 그리드를 본다 — `dashboard/page.tsx:166-250`
- 여정 스트립 5단계 Connect → Organize → Ground → Serve → Govern — `journey-strip.tsx:26-68`.
  04 Serve가 `/connect`로 가지만 번호 칩이지 CTA가 아니다(`:57-61`). "에이전트를 연결하라"는
  말이 없다.
- Knowledge 페이지 탭: Search/RAG · Composition · Ingest · Schedule · Members · (Concepts) · Compare —
  `frontend/app/knowledge/page.tsx:348-367`. **"이 컬렉션을 앱에서 쓰기" 스니펫이 없다.**
  Members 패널은 reader/editor 부여 가능 — `components/knowledge/members-panel.tsx:37,97,120`
- `/connect`: 목록·curl·브라우저 세션 실행은 좋다. 그러나 (a) `/api/ai/*`만 보이고, (b) 키 발급 UI가
  스코프를 비워 발급하며(2.1), (c) 비관리자는 "관리자에게 `knowledge:read`, `ai:generate` 요청"
  안내만 본다 — `connect/page.tsx:111-140`
- Help 가이드: Knowledge & RAG, AI Gateway, Governance, Sources, Catalog, SQL Lab — `frontend/app/help/page.tsx:32-79`.
  **"앱·에이전트와 통합" 주제가 없다.** `docs/*.md`의 curl 예시는 전부 사람 JWT(`$TOKEN`)를 쓴다 —
  `DEPLOY_SINGLE_NODE.md:385`, `AWS_BEDROCK_SETUP.md:240,277,344`, `AWS_MVP_RUNBOOK.md:114-146`

### 3.3 사이드바 IA는 대체로 맞다

Build AI(Knowledge, API) · Data(Sources, Catalog, Analytics) · Pipelines · Data Science · Operate(AI Gateway,
Governance, Storage, Infrastructure, Settings) · Help — `app-sidebar.tsx:47-117`. "API"가 Build AI에
있는 것은 v6.0과 맞다. 다만 호출자별 spend가 사는 "AI Gateway"와 호출자별 접근이 사는
"Governance"가 분리돼 있어 "어떤 에이전트가 무엇에 접근했고 얼마를 썼나"를 한 화면에서 볼 수 없다.

### 3.4 어시스턴트 레지스트리는 도구 면으로 바로 재사용 가능하다

방향을 뒤집을 수 있다는 판단의 근거:

- 액션 40개, 전부 `(params, user) -> dict` 시그니처, HTTP가 아니라 내부 함수 호출 —
  `backend/app/chat/analysis/knowledge.py:42-56`, `query.py:26-95`. Request·쿠키·브라우저 상태 의존 없음.
- 파라미터는 `extra="forbid"` pydantic, `tool_definitions`가 이미 도구 스키마를 생성 — `chat/actions.py:62-66,131-152`
- 게이트는 권한·capability를 서버에서 재계산, 파괴적 액션은 사용자가 이름을 댄 대상만 —
  `backend/app/chat/gate.py:96-118,168-183,246-276`. invocation 저장과 감사 이벤트 6종 — `chat/store.py`, `gate.py:87`
- 서비스 계정 차단은 **라우트 계층**(`require_human`)에만 있다 — `chat_routes.py:236-248,359-361,414`,
  `api/auth.py:474-492`. `gate.propose`는 서비스 계정을 막지 않는다(`approve`만 막음, `gate.py:236-241`).
  즉 read 액션을 서비스 계정으로 태우는 MCP 어댑터는 라우트 하나와 인증 매핑이면 된다.
- 약점: 필드 단위 `description`이 전체에서 7개뿐 — `analysis/knowledge.py:192,200`, `users.py:57`,
  `settings.py:62`. 도구로 노출하려면 필드 설명을 채워야 모델이 제대로 쓴다.

## 4. 우선순위

P0는 "문장이 거짓이 되는" 항목이고, 파트너 데모 전에 닫는다. P1은 데모 슬라이스 자체다. P2는 그 뒤다.

### P0 — 문장을 참으로 만드는 최소

1. **성공한 도구 호출을 감사한다.** `/ai/search`·`/ai/rag`·`/ai/sql`·`/queries/execute`의 성공 호출에
   actor·컬렉션(또는 테이블)·마스킹된 질문·반환 건수·인용 source 목록을 기록한다. 서비스 계정에는
   `save_history=false`를 허용하지 않는다. `security_audit.py:16-28`의 "허용은 기록 안 함" 결정을
   도구 엔드포인트에 한해 뒤집는다.
2. **UI 키 발급에 스코프를 넣는다.** `service-accounts.tsx:71`의 `scopes: []`를 명시적 선택으로 바꾸고,
   기본 제안을 `knowledge:read` + `ai:generate`로 둔다.
3. **UI 카피 교체.** §3.1의 열두 곳에서 "Portable AI Data Foundation"·"Foundation health"·
   "run the foundation"·"Portable core workflow"를 v6.0 문장으로 바꾼다.
4. **`/openapi.json`·`/docs` 인증 뒤로.** `main.py:93-94`의 미들웨어 범위 밖이다. 도구 면을 앞세우는
   제품이 스키마를 무인증으로 여는 것은 안 된다.

### P1 — 파트너 데모 슬라이스

> 2026-09-07 트렌드 조정(`POSITIONING_REVIEW.md` §5) 이후 순서: **9번 MCP 어댑터를 P1의 첫 항목으로
> 올린다.** 스펙이 stateless HTTP로 바뀐 지금이 가장 싸고, AgentCore Gateway 타깃 등록이 AWS 안의
> 유통 경로다. 8번 예산 강제는 보조 메시지이므로 P1 마지막으로 내린다.

5. **`/connect`를 진짜 도구 면으로.** `api_surface.py:19`의 `/api/ai/*` 한정을 풀어 `/queries/execute`와
   컬렉션 목록을 포함하고, 각 엔드포인트에 "이 키로 무엇이 보이는가"를 함께 보여준다.
6. **Knowledge 컬렉션에 "앱에서 쓰기" 스니펫.** 컬렉션 이름이 채워진 curl과 Python 예시 한 블록.
7. **호출자 화면.** Governance 또는 AI Gateway에 "서비스 계정 → 접근한 컬렉션·테이블 → 호출 수 →
   spend" 한 표. P0-1의 감사 행이 있어야 만들 수 있다.
8. **호출자별 예산 강제.** 최소안은 서비스 계정마다 LiteLLM 가상 키를 1:1로 만들어 게이트웨이가
   거부하게 하는 것. 정석은 `api_keys`에 예산 컬럼과 LLM 호출 전 확인.
9. **MCP 서버(read 전용).** 어시스턴트 레지스트리의 read 액션을 서비스 계정 인증으로 노출하는
   얇은 어댑터. `require_human` 대신 서비스 계정을 받는 라우트 하나, 필드 `description` 보강.
   이것이 v6.0의 "MCP roadmap"을 데모 가능한 크기로 만드는 조각이다.
10. **통합 도움말.** Help에 "앱·에이전트 연결" 주제 하나. `docs/*.md`의 curl을 서비스 키 기준으로.

### P2 — 그 다음

11. 인용에 안정 chunk id와 source URI, 스트리밍 응답
12. 키별 rate limit과 회전
13. `/queries/execute` 결과 행과 `/ai/sql` 출력의 PII 검사, 호출자·컬렉션별 PII 정책
14. Production default-deny RLS, 별도 DB role로 WORM 감사
15. 그룹·팀 단위 컬렉션 멤버십
16. 여정 스트립을 "Connect your agent" CTA가 있는 온보딩 체크리스트로

## 5. 점검 제한

- 라이브 API 호출·성능·실제 Bedrock 과금은 확인하지 않았다.
- 프런트엔드는 정적 대조만 했고 브라우저 E2E는 돌리지 않았다.
- 근거 라인 번호는 `1b19d38` 기준이며 다음 커밋에서 달라질 수 있다.

---

## 6. 조정된 문장에 대한 갭 분석 (2026-09-07, 트렌드 조정 이후)

> §1~§5는 오전의 v6.0 초안 문장을 기준으로 했다. 같은 날 `POSITIONING_REVIEW.md` §5의 트렌드
> 조정으로 문장이 바뀌었고, 새 문장은 이전에 없던 주장 다섯 개를 추가했다. 이 절은 그 다섯을
> 코드와 AWS 문서로 대조한다. 기존 판정(§1 표)은 그대로 유효하다.

### 6.1 새로 추가된 주장과 판정

| 새 주장 | 판정 | 갭 요약 |
|---|---|---|
| **어떤 MCP 게이트웨이 뒤에서도 동작, AgentCore Gateway 타깃으로 등록** | **미충족** | 등록 자체는 API key + `credentialPrefix: Bearer`로 가능. 그러나 생성 OpenAPI가 게이트웨이가 거부하는 `anyOf`를 포함하고, 게이트웨이 뒤에서는 **모든 에이전트가 하나의 서비스 계정으로 합쳐져** 호출자 단위 거버넌스가 사라진다 |
| **어떤 호출자가 어떤 컬렉션·행·청크를 읽을 수 있는지** | **컬렉션·행은 충족, 청크는 미충족** | 컬렉션 멤버십과 테이블 RLS는 있음. 컬렉션 안에서 청크·문서 단위로 호출자를 제한할 수단이 없다 |
| **무엇이 인용되고 무엇이 마스킹됐는지** | **미충족** | 응답에는 `citations`와 `pii_masked` 수가 있지만 어디에도 저장되지 않는다 |
| **한국 규제 증빙 셋** (식별자 마스킹 증적, CEO 책임 감사 export, ISMS-P NDJSON) | **미충족** | export 엔드포인트는 있으나 내용이 권한 결정뿐이다. 마스킹 증적은 커넥터 sync에만 남는다 |
| **MCP 서버(다음 슬라이스)** | **없음** (문서가 shipped라 하지 않으므로 과대주장은 아님) | 레지스트리·게이트·도구 스키마 생성기는 있음. 라우트·인증·필드 설명이 없다 |
| 게이트웨이 기능을 만들지 않는다 | **충족** | 레지스트리·SSO/SCIM·rug-pull 탐지 없음. 단 메뉴 이름 "AI Gateway"가 이 문장과 충돌 |

### 6.2 게이트웨이 뒤 등록 — 근거

AWS 문서(`gateway-schema-openapi`, `gateway-building-adding-targets-authorization`, `gateway-outbound-auth`,
2026-09-07 확인)와 대조했다.

되는 것:

- OpenAPI 3.0·3.1 타깃 지원. `operationId`가 MCP tool 이름이 된다.
- OpenAPI·MCP 타깃 아웃바운드 인증: API key(`credentialLocation: HEADER`, `credentialParameterName:
  Authorization`, `credentialPrefix: Bearer`) → DataPond의 `dp_sk_…` 키가 그대로 맞는다.
- 라이브가 EC2 직접 엔드포인트이므로 SigV4(IAM) 아웃바운드는 불가, API key 또는 OAuth만 가능.
  문서가 명시.

안 되는 것:

1. **생성 OpenAPI가 게이트웨이 규격에 맞지 않는다.** 게이트웨이는 `oneOf`/`anyOf`/`allOf`를 지원하지
   않는다. FastAPI 0.128이 내는 스펙은 3.1.0이고, `Optional[bool]`·`Optional[dict]` 필드가 전부
   `anyOf: [{type}, {type: null}]`로 렌더링된다. 2026-09-07 로컬 생성 결과: 도구 면 18개 path 중
   `SearchRequest`·`RagRequest`·`AskRequest` 스키마 모두 `anyOf` 포함(`ai_vectors.py:320-338`의
   `rerank: Optional[bool]`, `ai_sql.py:352-354`의 `context`). 그대로 올리면 타깃 생성이 실패한다.
   `operationId`도 `generate_sql_api_ai_sql_post` 같은 자동 생성 이름이라 tool 이름으로 부적절하다.
   → **도구 전용 OpenAPI 서브셋**(4~6개 operation, 명시적 operationId, `nullable` 대신 optional
   생략)을 별도로 내야 한다. `api_surface.py:19`가 이미 `/api/ai/*`만 고르므로 그 위에 얹을 수 있다.
2. **호출자 identity가 게이트웨이를 통과하지 못한다.** 아웃바운드 표에서 OpenAPI·MCP 타깃은 Token
   passthrough **불가**, Caller IAM credentials **불가**다. API key로 등록하면 게이트웨이 뒤의 모든
   에이전트·사용자가 DataPond에는 **서비스 계정 하나**로 보인다. 컬렉션 ACL·RLS·spend 귀속·감사가
   전부 그 하나에 붙는다. 문장의 "호출자 단위"가 게이트웨이 뒤에서는 "게이트웨이 단위"가 된다.
   유일한 통과 경로는 OAuth **token exchange(on-behalf-of)**인데, 이는 (a) 고객 IdP가 RFC 8693
   token exchange를 지원하고 (b) DataPond가 외부 IdP의 access token을 **resource server로 검증**해야
   가능하다. 현재 DataPond API는 자체 JWT와 `dp_sk_` 키만 받는다(`api/auth.py:221-233`). EE OIDC는
   로그인 플로우이고 JWKS 검증(`ee/backend/ee/sso/oidc.py:107-110`)은 API bearer 검증에 쓰이지
   않는다. `X-…` 계열 identity 헤더 처리도 없다(`backend/app` grep 0건).
   → 데모 최소안: 에이전트마다 서비스 계정 1개 + 게이트웨이 타깃 1개(운영은 무겁지만 코드 변경
   없음). 제품안: 외부 OIDC access token을 API bearer로 받는 resource-server 모드 + token exchange
   문서. 이것이 "게이트웨이 뒤에서도 호출자 단위"를 참으로 만드는 유일한 길이다.
3. Guardrails PII, 정책 엔진, rate limit은 게이트웨이가 이미 한다. DataPond 쪽 프롬프트 PII 마스킹
   (`chat_routes.py:111-115`)과 겹치지만 데이터 쪽 마스킹(적재·인용)은 겹치지 않는다. 문장의
   경계와 일치한다.

### 6.3 청크 단위 접근 — 근거

- `SearchRequest`/`RagRequest`에는 `collection, query, k, expand_concepts, rerank`뿐이다
  (`ai_vectors.py:320-338`). 호출자·문서·메타데이터 필터 파라미터가 없다.
- `_retrieve`는 `_collection_id`로 컬렉션 접근만 확인하고 그 컬렉션의 전체 청크를 대상으로 한다
  (`ai_vectors.py:1080-1100`). `ai_chunks.metadata JSONB`(`:117`)는 저장되지만 검색 조건으로 쓰이지 않는다.
- 즉 "행" 단위는 SQL 경로의 RLS로 참이지만, RAG 경로에서 "청크" 단위는 거짓이다. 컬렉션을 쪼개는
  것이 유일한 우회다. Bedrock Knowledge Bases는 메타데이터 필터로 이 단위를 이미 제공한다.
  → 문장을 "컬렉션·행"으로 줄이거나, 청크 메타데이터 기반 호출자 필터(예: `source_group`·`metadata`
  조건을 멤버십 행에 붙임)를 만든다. 전자가 정직하고 후자는 P1이다.

### 6.4 인용·마스킹 감사 — 근거

- `/ai/rag`는 `answer, citations, has_ai, pii_masked, concepts`를 돌려주지만(`ai_vectors.py:1378`)
  `INSERT`·`record_*`·history 호출이 없다(`:1300-1380` grep 0건). `/ai/search`도 같다.
- `pii_masked` 수가 영속되는 곳은 커넥터 sync 결과뿐이다(`connectors/custom.py:348`, `rest.py:324`,
  `storage.py:514`). RAG 경로의 마스킹 증적은 응답이 끝나면 사라진다.
- `security_audit_log` 행 필드는 `actor, permission, route, method, outcome, reason, client_address,
  occurred_at`(`security_audit.py:85-95`)이다. 컬렉션·질문·인용·마스킹 수를 담을 자리가 없다.
- 이 갭은 §4 P0-1과 같은 항목이다. 트렌드 조정 이후에는 문장의 리드 차별점 둘째가 됐으므로 무게가
  더 커졌다. 별도 테이블(`tool_call_log`: actor, tool, collection/table, question_masked_hash,
  hit_count, citation_sources[], pii_masked, spend_tokens, occurred_at)이 필요하다.

### 6.5 한국 규제 증빙 셋 — 근거

| 증빙 | 현재 | 갭 |
|---|---|---|
| 식별자 마스킹 증적 | 마스킹 자체는 6종 regex + 체크섬(`pii_ko.py:55-66`). 증적은 커넥터 sync만 | RAG 경로 증적 없음(6.4). 어떤 규칙이 몇 건을 가렸는지 기간별 리포트 없음 |
| CEO 책임 대응 감사 export | `GET /audit/export` NDJSON, `audit:read`(`audit_export.py:34-64`) | 내용이 권한 결정뿐. "누가 어떤 데이터를 어떤 에이전트로 읽었는가"가 없음 |
| ISMS-P 증빙 | 위 export | 기간·행위자·자원·결과가 한 행에 있어야 하는데 자원(컬렉션·테이블)이 없음 |

세 증빙 모두 6.4의 `tool_call_log`가 있어야 만들 수 있다. 즉 **P0-1 하나가 규제 세그먼트의 증빙
셋을 전부 연다.**

### 6.6 MCP 슬라이스 — 준비도

있는 것(§3.4 재확인): 액션 40개 `(params, user)` 시그니처, `extra="forbid"` pydantic,
`tool_definitions`(`chat/actions.py:131-152`), 서버측 권한·capability 재검사(`gate.py:96-118`).

없는 것:

- MCP 2026-07-28 streamable HTTP 엔드포인트와 `tools/list`·`tools/call` 핸들러
- 서비스 계정을 받는 라우트(`require_human`이 `chat_routes.py:236-248, 359-361`에서 차단)
- 필드 `description`(전체 7개), tool 이름 규칙(현재 `knowledge.search`처럼 점 포함 — LLM ToolSpec의
  이름 제약과 충돌 가능, AWS 문서가 경고)
- MCP 타깃 등록 시 필요한 `tools/list` 정적 카탈로그 또는 2LO

크기 추정: read 액션 12~15개만 노출하는 얇은 어댑터. 게이트웨이 뒤 identity 문제(6.2-2)는 MCP로
가도 동일하다. MCP 타깃도 Token passthrough 불가, token exchange만 가능하다.

### 6.7 사용성 갭 — 조정된 문장 기준

1. **메뉴 "AI Gateway"가 포지셔닝과 충돌한다.** 사이드바(`app-sidebar.tsx:103`)와 페이지 H1
   (`frontend/app/ai/page.tsx:33`)이 "AI Gateway"다. 문장은 "우리는 게이트웨이를 만들지 않는다"고
   말한다. 내용은 LiteLLM 모델 라우팅·가상 키·spend이므로 "Models & Spend" 같은 이름이 맞다.
2. **"게이트웨이에 등록하기" 여정이 없다.** `/connect`는 curl만 보여준다. 도구 전용 OpenAPI 다운로드,
   AgentCore Gateway 타깃 등록 절차, 에이전트별 서비스 계정 매핑 안내가 없다. `docs/*.md`의 curl은
   전부 사람 JWT다.
3. **호출자 한 화면이 없다.** 조정된 리드("어떤 호출자가 무엇을 읽었고 무엇이 인용됐나")를 보여줄
   화면이 Governance에도 AI Gateway에도 없다. 6.4의 로그가 생겨야 만들 수 있다.
4. **컬렉션 페이지가 "누가 이 컬렉션을 도구로 쓰는가"를 모른다.** Members 탭은 사람·서비스 계정
   부여만 한다. 어떤 게이트웨이·에이전트가 붙어 있는지, 최근 호출이 있었는지 표시가 없다.
5. §3.1의 "Foundation" 카피 열두 곳은 그대로 남아 있다.

### 6.8 갭 순위 (조정된 문장 기준으로 재정렬)

> 2026-09-07 §6.1 권고 적용 이후 순서. "게이트웨이 뒤"가 문장에서 빠졌으므로 게이트웨이 등록
> 항목은 내려가고 직접 호출 경로(에이전트당 서비스 계정 UX, MCP)가 올라간다.

| 순위 | 갭 | 왜 이 순서인가 | 크기 |
|---|---|---|---|
| 1 | 도구 호출 로그(`tool_call_log`) + 성공 호출 감사 | 리드 차별점 둘째, 규제 증빙 셋, 호출자 화면의 전제. 트렌드에서도 첫째 | 중 |
| 2 | 에이전트당 서비스 계정 발급 UX: 스코프 명시, "이 에이전트용 키" 흐름, 컬렉션 페이지 스니펫 | 직접 호출이 기본 경로가 됐으므로 이 여정이 제품의 첫인상 | 소 |
| 3 | UI 카피 "Foundation" 열두 곳, "AI Gateway" 메뉴 이름, `/openapi.json` 인증 | 문장과 화면의 불일치. 전부 작음 | 소 |
| 4 | read 전용 MCP 서버 | 직접 호출 경로의 다음 슬라이스 | 중 |
| 5 | 외부 OIDC access token resource-server 모드 | OAuth 기반 MCP 클라이언트가 요구. 게이트웨이 token exchange도 이것으로 해결 | 중/대 |
| 6 | 도구 전용 OpenAPI 서브셋 + 게이트웨이 등록 how-to | 게이트웨이를 쓰는 고객이 나타났을 때. 코드 변경 작음 | 소 |
| 7 | 청크 메타데이터 기반 호출자 필터 | 문장은 "컬렉션·행"으로 이미 정정됨. 구현은 P1 | 중 |
| 8 | 호출자 화면, 컬렉션의 "누가 도구로 쓰나" 표시 | 1번 뒤에만 가능 | 중 |
| 9 | 호출자별 예산 강제 | 보조 메시지로 강등됐으므로 마지막 | 중 |

### 6.9 문장에 대한 권고

갭 분석 결과 조정된 문장에서 **지금 당장 정정할 곳은 한 군데**다. "컬렉션·행·청크"에서 "청크"는
구현이 없으므로 "컬렉션·행"으로 줄이거나 "(청크 단위는 roadmap)"을 붙인다. "AgentCore Gateway 뒤에서
동작"은 API key 등록이 가능하므로 거짓은 아니지만, "호출자 단위"가 게이트웨이 뒤에서는 약해진다는
사실을 `PRODUCT_CONCEPT.md` 거버넌스 경계 절에 한 줄 적어야 한다.

---

## 7. 최종 포지셔닝 기준 보유 항목 갭 분석 (2026-09-07, §6.1 권고 적용 이후)

> 최종 포지셔닝의 다섯 축을 각각 "무엇을 보유해야 하는가"로 풀고, 항목마다 보유 여부를 코드로
> 대조했다. §1~§6과 겹치는 근거는 절 번호로만 가리킨다. 이 절이 현재 시점의 종합이다.

### 7.1 축별 보유 현황

**축 A — 직접 호출이 기본 경로다** (에이전트당 서비스 계정 키로 REST, 다음은 MCP)

| 보유해야 할 항목 | 보유 | 근거 | 갭 |
|---|---|---|---|
| 서비스 계정 생성(이름·역할) UI | ○ | `components/settings/service-accounts.tsx:53-62`, 역할 선택 `:151-155` | — |
| 키 발급 시 스코프 선택 | ✕ | `:71` `scopes: []` 고정 | UI 키는 role 전체 권한 |
| 키 발급 시 만료 선택 | ✕ | 표시만(`:12` `expires_at`), 입력 없음 | 무기한 키가 기본 |
| 키 폐기 | ○ | `:82`, `:228` | — |
| 서비스 계정별 호출 수·spend 표시 | ○ | `AccountSpend` `:250-267` | — |
| 서비스 계정에 컬렉션 부여 | △ | 컬렉션 쪽 Members 탭에서 가능(§3.2). 계정 쪽에서 "이 에이전트가 볼 수 있는 컬렉션" 없음 | 방향이 하나뿐 |
| `/connect`의 curl 예시와 브라우저 실행 | ○ | `connect/page.tsx:164-206` | — |
| `/connect`가 `/queries/execute` 포함 | ✕ | `api_surface.py:19` | governed SQL이 도구 면에서 안 보임 |
| 컬렉션 페이지 "앱에서 쓰기" 스니펫 | ✕ | §3.2 | — |
| MCP 엔드포인트 | ✕ | §6.6 | 다음 슬라이스 |
| OAuth resource-server(호스티드 MCP 클라이언트용) | ✕ | §6.2-2 | — |
| API 키 호출 rate limit·회전 | ✕ | §2.1 | — |
| 통합 도움말·문서(서비스 키 기준 curl) | ✕ | §3.2, docs의 curl은 사람 JWT | — |

첫 governed 호출까지의 여정을 세면 **화면 4개, 조작 약 12회**다: 로그인 → Knowledge에서 컬렉션 생성·적재 →
Settings → Service accounts 탭 → 계정 생성 → 키 발급·복사 → API 페이지 → curl 붙여넣기. 안내된 흐름이
없어 관리자가 순서를 알아야 한다. 이 여정이 "구축 시간으로 판다"는 주장의 첫인상이다.

**축 B — 호출자 단위 데이터 계층 거버넌스** (컬렉션·행 접근, 인용·마스킹 감사, 호출자별 예산)

| 보유해야 할 항목 | 보유 | 근거 | 갭 |
|---|---|---|---|
| 컬렉션 멤버 ACL, 서비스 계정 포함 | ○ | §2.3 | 그룹 단위 없음 |
| 테이블 행 필터·컬럼 마스킹, 서비스 계정 기준 | ○ | §2.3, 라이브 `rls.enabled: true` | `defaultDeny: false`(`values-prod-single.yaml:162`) |
| SQL 문장 종류 게이트 | ○ | §2.2 | — |
| PII 마스킹(적재·검색·인용) | ○ | §2.4 | SQL 결과 행 미검사 |
| **성공한 검색·답변의 감사 기록** | ○ | `backend/app/tool_call_log.py`, `backend/app/api/tool_call_routes.py` | — |
| 인용·마스킹 수의 영속 | ○ | `backend/app/tool_call_log.py`, `frontend/lib/compliance-report.ts` | — |
| 호출자별 spend 귀속 | ○ | §2.6 | — |
| **호출자별 예산 강제** | ✕ | §2.6 | 조회만 |
| 권한 결정 감사 append-only + NDJSON export | ○ | §2.5 | WORM 아님 |

**축 C — 심사 통과와 구축 시간으로 판다** (컴플라이언스 검토자에게 낼 증빙)

| 보유해야 할 항목 | 보유 | 근거 | 갭 |
|---|---|---|---|
| Governance 화면의 감사·활동·AI 안전·데이터 보호·접근 제어·비용·리포트 탭 | ○ | `frontend/app/governance/page.tsx:1030-1036` | — |
| 기간 지정 컴플라이언스 리포트(JSON 다운로드) | ○ | `:821-891`, 항목은 `queries, aiSql, pii, tool_calls`; `frontend/lib/compliance-report.ts` | — |
| 감사 NDJSON export(SIEM) | ○ API | `audit_export.py:34-64` | UI 버튼 없음(grep 0건) |
| RLS 커버리지(보호 안 된 테이블 목록) | ○ | `governance/rls/coverage` | — |
| "이 에이전트가 무엇을 읽었나" 화면 | ✕ | §6.7-3 | B의 감사 기록이 전제 |
| ISMS-P 증빙 형태(기간·행위자·자원·결과) | ✕ | §6.5 | 자원(컬렉션·테이블) 열 없음 |

검토자가 지금 받을 수 있는 것은 "누가 로그인했고 무엇이 거부됐고 어떤 SQL이 실행됐는가"이지,
"어떤 에이전트가 어떤 컬렉션에서 무엇을 인용받았는가"가 아니다. 파일럿을 막는 질문이 후자다.

**축 D — 온프렘·주권 환경이 가장 안전한 자리다** (AWS 네이티브와 경쟁하지 않는 유일한 칸)

| 보유해야 할 항목 | 보유 | 근거 | 갭 |
|---|---|---|---|
| 동일 코드의 온프렘 프로필 | ○ | `values-onprem.yaml`: MinIO(`:191-197`), Ollama/vLLM(`:62`, `:306-309`) | — |
| **lean 온프렘 코어 프로필**(코어 + MinIO + 로컬 모델, add-on 없음) | ✕ | `values-onprem.yaml`은 add-on 8개 전부 `enabled: true`, maturity `community`(`:17`); foundation은 S3·Bedrock 전제 | 가장 안전한 자리에 "지원되는" 프로필이 없다 |
| 온프렘 코어의 지원 티어 | △ | `SUPPORT.md`: 코어는 지원, add-on은 미지원. 그러나 프로필 단위로는 community | 문서와 프로필 라벨이 어긋남 |
| 로컬 임베딩 차원 호환 안내 | ○ | `DEPLOYMENT_PROFILES.md` 권고 5 | — |
| 에어갭 설치 검증 | ○ 과거 | CLAUDE.md 완료 로그 #59 | 최근 acceptance 없음 |

**축 E — 첫 세그먼트: 개인정보보호법 대응이 걸리는 한국 기업**

| 보유해야 할 항목 | 보유 | 근거 | 갭 |
|---|---|---|---|
| 한국형 식별자 마스킹 | ○ | §2.4 | Guardrails와 동등, 차별점 아님 |
| **한국어 UI** | ✕ | `frontend/app`·`components`에서 한글 파일 4개뿐, 전부 상수·주석(`governance/page.tsx:145-155`). i18n 없음 | **정본의 "한국어 UI 있음"은 거짓 → 정정** |
| 한국어 문서 | ○ | `docs/*.md` 다수 | 운영자용. 구매자용 한 장 없음 |
| 개인정보위 가이드 대응 매핑 | ✕ | 문서 없음 | "어느 조항을 어떤 기능이 충족하는가" 표 없음 |
| ISMS-P 증빙 | ✕ | 축 C | — |

### 7.2 종합

| 축 | 보유율(항목 기준) | 판정 |
|---|---:|---|
| A 직접 호출 | 5 / 13 | 뼈대는 있고 여정이 없다 |
| B 데이터 거버넌스 | 6 / 9 | 접근은 있고 **감사·예산이 없다** |
| C 심사 통과 | 2 / 6 | 리포트 틀은 있고 **에이전트 호출이 빠져 있다** |
| D 온프렘 | 2 / 5 | 코드는 있고 **지원되는 프로필이 없다** |
| E 한국 세그먼트 | 2 / 5 | 마스킹은 있고 **UI·매핑이 없다** |

다섯 축 모두 같은 모양이다. **기반은 있고, 포지셔닝이 약속한 마지막 한 조각이 없다.** 그 마지막
조각은 축마다 다르지만 셋으로 모인다.

1. **도구 호출 감사 로그** — B·C·E 세 축의 빈칸을 한 번에 채운다(§6.4, §6.5).
2. **에이전트 온보딩 여정** — 스코프·만료가 있는 키 발급, 계정 쪽에서 컬렉션 부여, 컬렉션 페이지
   스니펫, `/connect`에 SQL 포함. A축의 빈칸 대부분이 UI 작업이다.
3. **lean 온프렘 코어 프로필** — `values-sovereign-core.yaml` 하나와 지원 티어 명시. D축은 코드가
   아니라 파일 하나와 문장 하나다.

### 7.3 정본 정정

- `PRODUCT_CONCEPT.md` 첫 세그먼트 절의 "한국어 UI"는 삭제한다. UI는 영어이고 한국어인 것은 문서다.
  한국어 UI가 세그먼트에 필요한지는 파트너 대화에서 확인할 항목으로 남긴다.
