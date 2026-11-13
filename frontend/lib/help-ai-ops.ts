/** Content of the AI and operations guides (Knowledge, Integrate, Governance, Metrics,
 *  Operate): written once as `L` values and rendered by components/help/ai-ops-guide.tsx.
 *  Commands, API paths, identifiers and product nouns stay untranslated. In text,
 *  `backtick spans` render as inline code and **double asterisks** as bold. */
import type { L } from "@/lib/help-locale"

export type Section = {
  title: L
  paras?: L[]
  bullets?: L[]
  code?: string
  links?: { href: string; label: L }[]
}

export type Guide = {
  crumb: L
  title: L
  subtitle: L
  alert?: { title: L; body: L }
  sections: Section[]
  limits?: { title: L; items: L[] }
}

const l = (en: string, ko: string): L => ({ en, ko })

export const KNOWLEDGE: Guide = {
  crumb: l("Knowledge & RAG", "Knowledge & RAG"),
  title: l("Knowledge & RAG", "Knowledge & RAG"),
  subtitle: l(
    "The AI layer on your lakehouse data: build a collection, check what it retrieves, and get answers that cite their sources",
    "레이크하우스 데이터 위의 AI 계층입니다. 컬렉션을 만들고, 검색 결과를 확인하고, 출처가 달린 답변을 받습니다",
  ),
  alert: {
    title: l("The same governed data, and it also runs alone", "같은 데이터를 거버넌스 아래에서 쓰며, 단독으로도 동작합니다"),
    body: l(
      "On a lakehouse profile, Knowledge can ground answers in your Iceberg tables and source databases. On the Core profiles (no catalog, no engine) it needs only PostgreSQL with pgvector and a model provider through LiteLLM. This guide applies to both.",
      "레이크하우스 프로필에서는 Iceberg 테이블과 소스 데이터베이스의 내용을 근거로 답할 수 있습니다. Core 프로필(카탈로그·쿼리 엔진 없음)에서는 pgvector가 있는 PostgreSQL과 LiteLLM 모델 제공자만 있으면 됩니다. 이 가이드는 두 경우 모두에 적용됩니다.",
    ),
  },
  sections: [
    {
      title: l("1. Create a collection", "1. 컬렉션 만들기"),
      paras: [
        l("Knowledge → New collection. A collection is the unit of access, of masking and of refresh. Keep one subject per collection: everything you govern later is governed at this boundary.",
          "Knowledge → New collection에서 만듭니다. 컬렉션은 접근, 마스킹, 갱신의 단위입니다. 주제별로 하나씩 나누세요. 이후의 모든 거버넌스가 이 경계에서 적용됩니다."),
        l("Chunking belongs to the collection, not to each ingest. Set it once here. Two ingests that split differently put passages in one collection that nothing reports as inconsistent.",
          "청킹은 수집(ingest)이 아니라 컬렉션에 속합니다. 여기서 한 번만 정하세요. 분할 방식이 다른 수집이 섞이면 같은 컬렉션 안에 서로 다른 기준의 문단이 쌓이는데, 이를 알려 주는 곳은 없습니다."),
      ],
      links: [{ href: "/knowledge", label: l("Open Knowledge", "Knowledge 열기") }],
    },
    {
      title: l("2. Ingest something representative", "2. 대표적인 데이터부터 수집하기"),
      paras: [l("Three ways in, all landing in the same place:", "세 가지 방법이 있고, 모두 같은 곳에 저장됩니다.")],
      bullets: [
        l("**Paste or upload text** — the fastest way to prove the path end to end.", "**텍스트 붙여넣기·업로드** — 전체 경로를 가장 빠르게 확인하는 방법입니다."),
        l("**S3 objects** — point at a prefix in a configured bucket.", "**S3 객체** — 설정된 버킷의 prefix를 지정합니다."),
        l("**A catalog table column** — in Catalog, open a table and use Send to Knowledge. Works for lake tables and for source tables (`src_<slug>`) alike. Pick a column that holds prose: a column of SKUs embeds fine and retrieves nothing useful, which looks like broken retrieval and is a badly chosen source.",
          "**카탈로그 테이블 컬럼** — Catalog에서 테이블을 열고 Send to Knowledge를 누릅니다. 레이크 테이블과 소스 테이블(`src_<slug>`) 모두 가능합니다. 문장이 들어 있는 컬럼을 고르세요. SKU 같은 컬럼은 임베딩은 되지만 쓸모 있는 검색 결과가 나오지 않습니다. 검색이 고장 난 것처럼 보이지만 실제로는 소스를 잘못 고른 것입니다."),
      ],
      links: [{ href: "/catalog", label: l("Open Catalog", "Catalog 열기") }],
    },
    {
      title: l("3. Search before you ask", "3. 질문하기 전에 먼저 검색하기"),
      paras: [
        l("Use Search mode first and read the passages that come back. If the right passage is not in the results, no prompt will put it in the answer: the model only sees what retrieval hands it.",
          "먼저 Search 모드로 검색해서 돌아온 문단을 읽어 보세요. 필요한 문단이 결과에 없다면 프롬프트를 아무리 고쳐도 답에 들어가지 않습니다. 모델은 검색이 건넨 내용만 봅니다."),
        l("Retrieval is pgvector with an HNSW index. If a reranking model is configured, the top results are reordered through it; when that model is unavailable the order falls back to plain vector similarity instead of failing the request. Re-ingesting the same source replaces its chunks instead of appending.",
          "검색은 HNSW 인덱스를 쓰는 pgvector입니다. 재순위(rerank) 모델이 설정되어 있으면 상위 결과를 다시 정렬하고, 그 모델을 쓸 수 없으면 요청을 실패시키지 않고 벡터 유사도 순서로 돌아갑니다. 같은 소스를 다시 수집하면 청크를 덧붙이지 않고 교체합니다."),
      ],
    },
    {
      title: l("4. Ask, and check the citations", "4. 질문하고 인용 확인하기"),
      paras: [l("Switch to Answer mode. Every answer comes back with the passages it was grounded on. An answer with no citations means the model had nothing to ground on: treat it as a retrieval problem, not a model problem.",
        "Answer 모드로 바꿉니다. 모든 답변에는 근거가 된 문단이 함께 옵니다. 인용이 없는 답변은 근거로 삼을 것이 없었다는 뜻입니다. 모델이 아니라 검색의 문제로 보세요.")],
      code: `curl -sX POST https://your-deployment/api/ai/rag \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"collection": "support-knowledge-base", "question": "환불은 며칠 걸리나요?"}'`,
    },
    {
      title: l("5. Keep it fresh", "5. 최신 상태로 유지하기"),
      paras: [
        l("A collection fed from a saved source can re-embed on an interval. The scheduler runs inside the backend, needs no Airflow, and holds a lock so replicas do not duplicate the work. A source that is a Catalog table is checked for freshness the same way.",
          "저장된 소스에서 만든 컬렉션은 일정 간격으로 다시 임베딩할 수 있습니다. 스케줄러는 백엔드 안에서 돌고 Airflow가 필요 없으며, 락을 잡으므로 레플리카가 작업을 중복 실행하지 않습니다. 카탈로그 테이블이 소스인 경우에도 같은 방식으로 최신 여부를 확인합니다."),
        l("Re-embedding costs model tokens every time it fires. Match the interval to how often the source really changes: hourly on data that changes weekly buys identical vectors.",
          "재임베딩은 실행될 때마다 모델 토큰을 씁니다. 간격은 소스가 실제로 바뀌는 주기에 맞추세요. 매주 바뀌는 데이터를 매시간 갱신하면 똑같은 벡터를 돈 주고 다시 만드는 셈입니다."),
      ],
    },
    {
      title: l("6. What gets masked on the way through", "6. 처리 과정에서 마스킹되는 것"),
      paras: [
        l("The guardrail runs on the question, on the retrieved passages and on the generated answer. It covers Korean personal identifiers (주민등록번호 and 신용카드 are checksum-verified, so random digits are not flagged) and structured credentials: AWS keys, PEM private keys, API tokens and database URLs.",
          "가드레일은 질문, 검색된 문단, 생성된 답변에 모두 적용됩니다. 한국 개인정보(주민등록번호와 신용카드는 체크섬으로 검증하므로 임의의 숫자는 걸리지 않습니다)와 AWS 키, PEM 개인 키, API 토큰, 데이터베이스 URL 같은 자격 증명을 탐지합니다."),
        l("In `mask` mode findings are replaced with a tag. In `block` mode the answer is withheld and the citations still come back, so you can see what would have been used.",
          "`mask` 모드에서는 탐지된 값이 태그로 바뀝니다. `block` 모드에서는 답변을 내보내지 않고 인용만 돌려주므로, 무엇이 쓰였을지 확인할 수 있습니다."),
      ],
    },
    {
      title: l("7. Share it: members and chunk access rules", "7. 공유하기: 멤버와 청크 접근 규칙"),
      paras: [
        l("A collection has an owner. Admins see everything; anyone else needs a grant under Members, as `reader` or `editor`. Service accounts are granted the same way, by their `svc-…` username.",
          "컬렉션에는 소유자가 있습니다. 관리자는 모두 볼 수 있고, 그 외에는 Members에서 `reader` 또는 `editor`로 권한을 받아야 합니다. 서비스 계정도 `svc-…` 사용자 이름으로 같은 방식으로 부여합니다."),
        l("Inside a shared collection you can narrow what each caller retrieves with a chunk access rule: a chunk's metadata value must match one of the caller's attributes (for example a department). The rule runs in the vector query itself, before the top-k cut, and fails closed: a chunk without the label and a caller without the attribute both see nothing. Admins are held to it too.",
          "공유된 컬렉션 안에서도 청크 접근 규칙으로 호출자별 검색 범위를 좁힐 수 있습니다. 청크의 메타데이터 값이 호출자의 속성(예: 부서) 중 하나와 일치해야 합니다. 규칙은 상위 k개를 자르기 전에 벡터 쿼리 안에서 적용되며, 닫힌 방향으로 동작합니다. 라벨이 없는 청크와 속성이 없는 호출자는 아무것도 보지 못합니다. 관리자에게도 똑같이 적용됩니다."),
        l("Collection access is an application-level owner/admin/shared ACL. It is not database-native row security.",
          "컬렉션 접근 제어는 애플리케이션 수준의 소유자·관리자·공유 ACL입니다. 데이터베이스 자체의 행 수준 보안이 아닙니다."),
      ],
    },
    {
      title: l("8. Optional: widen a query with concepts", "8. 선택: 개념으로 질의 넓히기"),
      paras: [
        l("The Concepts tab defines a term and its synonyms (refund alongside 환불, 반품, 환급). The Concepts toggle above the search box expands a query with them before retrieval, and the results panel shows which concepts fired.",
          "Concepts 탭에서 용어와 동의어를 정의합니다(refund와 환불, 반품, 환급). 검색창 위의 Concepts 토글을 켜면 검색 전에 질의를 이 용어로 확장하고, 결과 패널에 적용된 개념이 표시됩니다."),
        l("It is off by default and does nothing until you add concepts. This is deliberate term expansion, not an inference engine: it widens recall for vocabulary your documents and your users spell differently.",
          "기본값은 꺼짐이며 개념을 추가하기 전에는 아무 일도 하지 않습니다. 추론 엔진이 아니라 의도적인 용어 확장입니다. 문서와 사용자가 서로 다르게 쓰는 표현의 재현율을 높여 줍니다."),
      ],
    },
  ],
  limits: {
    title: l("When something looks wrong", "문제가 있어 보일 때"),
    items: [
      l("**Search returns nothing** — check the collection has chunks, then that the embedding model has not changed. A different model means a different vector dimension.",
        "**검색 결과가 없음** — 컬렉션에 청크가 있는지 확인하고, 임베딩 모델이 바뀌지 않았는지 보세요. 모델이 달라지면 벡터 차원도 달라집니다."),
      l("**Answers ignore an obvious document** — search for it directly. If search cannot find it, the problem is the source or the chunking, not the prompt.",
        "**답변이 명백한 문서를 무시함** — 그 문서를 직접 검색해 보세요. 검색에서도 안 나오면 원인은 프롬프트가 아니라 소스나 청킹입니다."),
      l("**Everything is masked** — the effective mode is the strictest of the deployment default, the collection and the caller. A collection can tighten it; nothing can loosen it.",
        "**전부 마스킹됨** — 실제 모드는 배포 기본값, 컬렉션, 호출자 중 가장 엄격한 것입니다. 컬렉션은 더 엄격하게 만들 수는 있어도 완화할 수는 없습니다."),
      l("**A caller sees fewer results than expected** — check the collection's chunk access rule and the caller's attributes.",
        "**호출자에게 결과가 예상보다 적음** — 컬렉션의 청크 접근 규칙과 호출자의 속성을 확인하세요."),
      l("**A scheduled refresh never runs** — confirm the collection has a saved source. A schedule without one has nothing to re-ingest.",
        "**예약된 갱신이 실행되지 않음** — 컬렉션에 저장된 소스가 있는지 확인하세요. 소스가 없으면 다시 수집할 것이 없습니다."),
    ],
  },
}

export const GOVERNANCE: Guide = {
  crumb: l("Governance", "Governance"),
  title: l("Governance", "Governance"),
  subtitle: l(
    "Decide who reads what, what never leaves in the clear, and what the record shows afterwards",
    "누가 무엇을 읽는지, 무엇이 원문 그대로 나가지 않는지, 그리고 사후에 무엇이 기록되는지를 정합니다",
  ),
  alert: {
    title: l("Governed at the data layer", "데이터 계층에서 통제합니다"),
    body: l(
      "These controls apply wherever the data is reached through DataPond: the console, the REST API, an agent over MCP. A caller cannot route around them by changing client. A client that connects straight to Trino is covered only when Layer 2 is on (section 5).",
      "이 통제는 DataPond를 거치는 모든 경로(콘솔, REST API, MCP를 쓰는 에이전트)에 적용됩니다. 클라이언트를 바꿔도 우회할 수 없습니다. Trino에 직접 접속하는 클라이언트는 Layer 2를 켰을 때만 통제됩니다(5절).",
    ),
  },
  sections: [
    {
      title: l("1. Which catalogs a caller may use", "1. 호출자가 쓸 수 있는 카탈로그"),
      paras: [
        l("Catalog grants decide who may name a catalog in SQL. They are set per catalog under Settings → Data catalogs (admins). A catalog with no grants is open; once it has grants, only the listed users and roles reach it.",
          "카탈로그 권한(grant)은 SQL에서 어떤 카탈로그를 쓸 수 있는지 정합니다. Settings → Data catalogs(관리자)에서 카탈로그별로 설정합니다. 권한이 없는 카탈로그는 열려 있고, 권한이 하나라도 생기면 목록에 있는 사용자와 역할만 접근합니다."),
        l("A database source is a Trino catalog `src_<slug>`. Its share list (the owner and the members) is also that catalog's grants, so sharing a source in Sources and granting its catalog are one action. An unowned source is open.",
          "데이터베이스 소스는 Trino 카탈로그 `src_<slug>`입니다. 소스의 공유 목록(소유자와 멤버)이 곧 그 카탈로그의 권한입니다. 따라서 Sources에서 소스를 공유하는 것과 카탈로그 권한을 주는 것은 같은 동작입니다. 소유자가 없는 소스는 열려 있습니다."),
        l("When two catalogs see the same table, one is the owner and the other a read-only mirror. Reads of a mirror run against the owner, so the owner's grants and policies apply.",
          "두 카탈로그가 같은 테이블을 볼 때는 한쪽이 소유자이고 다른 쪽은 읽기 전용 미러입니다. 미러를 읽으면 소유자 쪽에서 실행되므로 소유자의 권한과 정책이 적용됩니다."),
      ],
      links: [{ href: "/settings?tab=catalogs", label: l("Settings → Data catalogs", "Settings → Data catalogs") }],
    },
    {
      title: l("2. Row filters and column masks", "2. 행 필터와 컬럼 마스크"),
      paras: [
        l("Governance → Policies holds row filters and column masks. A policy names a catalog, a schema and a table, so it applies to a lake table and to a source table (`src_crm.public.orders`) in the same way. Mask types: full redaction, partial email, SSN or phone, hash, null, or a custom expression.",
          "Governance → Policies에서 행 필터와 컬럼 마스크를 관리합니다. 정책은 catalog, schema, table을 지정하므로 레이크 테이블과 소스 테이블(`src_crm.public.orders`)에 똑같이 적용됩니다. 마스크 유형은 전체 가림, 이메일·주민번호·전화번호 부분 가림, 해시, null, 사용자 정의 표현식입니다."),
        l("Policies are applied as SQL rewriting on the governed path: Analytics, `/queries/execute`, the catalog preview, metrics and MCP. `custom` inserts SQL as written, so treat write access to policies like the right to run SQL.",
          "정책은 거버넌스 경로(Analytics, `/queries/execute`, 카탈로그 미리보기, 메트릭, MCP)에서 SQL 재작성으로 적용됩니다. `custom`은 입력한 SQL을 그대로 넣으므로, 정책 쓰기 권한은 SQL 실행 권한과 같게 다루세요."),
      ],
      links: [{ href: "/governance", label: l("Open Governance", "Governance 열기") }],
    },
    {
      title: l("3. Personal data, and who decides how hard it is masked", "3. 개인정보와 마스킹 강도를 정하는 주체"),
      paras: [
        l("Three PII modes: `off`, `mask` (findings replaced with a tag) and `block` (the request is refused rather than answered). The deployment sets a default; a collection or a caller can be held to something stricter. The effective mode is the strictest of the three, so a per-collection setting can tighten masking but never loosen it. An unrecognised value is ignored, not read as `off`.",
          "PII 모드는 세 가지입니다. `off`, `mask`(탐지된 값을 태그로 대체), `block`(답하지 않고 요청을 거부). 배포가 기본값을 정하고, 컬렉션이나 호출자는 더 엄격하게 지정할 수 있습니다. 실제 모드는 셋 중 가장 엄격한 것이므로 컬렉션 설정은 강화만 할 수 있고 완화할 수 없습니다. 알 수 없는 값은 `off`가 아니라 무시됩니다."),
        l("Korean identifiers (주민등록번호, 신용카드) are checksum-verified, so ordinary numbers are not swept up. Structured credentials (AWS keys, PEM keys, GitHub and Slack tokens, JWTs, the password in a database URL) follow the same rules. Placeholders such as `changeme` are filtered out: a guardrail that fires on ordinary config gets switched off.",
          "한국 개인정보(주민등록번호, 신용카드)는 체크섬으로 검증하므로 일반 숫자는 걸리지 않습니다. 구조화된 자격 증명(AWS 키, PEM 키, GitHub·Slack 토큰, JWT, 데이터베이스 URL의 비밀번호)도 같은 규칙을 따릅니다. `changeme` 같은 자리표시자는 제외합니다. 평범한 설정에도 울리는 가드레일은 결국 꺼지기 때문입니다."),
        l("Data sync masks PII inside the SELECT, before rows reach Iceberg.",
          "데이터 동기화는 행이 Iceberg에 도달하기 전에 SELECT 안에서 PII를 마스킹합니다."),
      ],
    },
    {
      title: l("4. What the record shows", "4. 기록에 남는 것"),
      paras: [
        l("Governance has these tabs: Tool calls (every search, cited answer, metric query or SQL by any caller, with the masked question, hit count, cited sources and what was refused), Query log (SQL executions), Activity (queries, sign-ins and policy decisions, sync runs), AI Safety, Data Protection, Access Control and Reports.",
          "Governance에는 다음 탭이 있습니다. Tool calls(모든 호출자의 검색, 인용 답변, 메트릭 쿼리, SQL. 마스킹된 질문, 결과 수, 인용 출처, 거부된 호출 포함), Query log(SQL 실행), Activity(쿼리, 로그인, 정책 결정, 동기화 실행), AI Safety, Data Protection, Access Control, Reports."),
        l("Refusals are recorded too: a key asking for something it may not have is the row an auditor most wants. Permission decisions record the permission required and whether it was allowed.",
          "거부도 기록됩니다. 가질 수 없는 것을 요청한 키는 감사자가 가장 보고 싶어 하는 행입니다. 권한 결정에는 필요했던 권한과 허용·거부 여부가 남습니다."),
        l("For a SIEM, export NDJSON from `/api/audit/export` and `/api/audit/tool-calls/export`.",
          "SIEM으로 보내려면 `/api/audit/export`와 `/api/audit/tool-calls/export`에서 NDJSON으로 내보냅니다."),
      ],
    },
    {
      title: l("5. Layer 2: Trino access control (optional)", "5. Layer 2: Trino 접근 제어 (선택)"),
      paras: [
        l("Row filters and masks apply to everything that goes through the backend. A client that connects directly to Trino bypasses that path. Layer 2 generates a Trino file-based access-control rule set from your grants and applies it to the engine, so direct connections are bound too.",
          "행 필터와 마스크는 백엔드를 거치는 모든 요청에 적용됩니다. Trino에 직접 접속하는 클라이언트는 이 경로를 거치지 않습니다. Layer 2는 권한 설정으로부터 Trino 파일 기반 접근 제어 규칙을 만들어 엔진에 적용하므로 직접 연결도 통제됩니다."),
        l("It is off by default (`trino.rls.enabled=false`) and needs Trino, so it does not exist on the Core profiles. It is coarser than the backend path for source tables: Trino's catalog rule has no row filter. Until it is on, a direct Trino or Glue client is not covered by any layer.",
          "기본값은 꺼짐(`trino.rls.enabled=false`)이며 Trino가 필요하므로 Core 프로필에는 없습니다. 소스 테이블에는 백엔드 경로보다 거칠게 적용됩니다. Trino 카탈로그 규칙에는 행 필터가 없기 때문입니다. 켜기 전까지는 Trino나 Glue에 직접 붙는 클라이언트를 통제하는 계층이 없습니다."),
      ],
    },
    {
      title: l("6. Cap what a caller can spend", "6. 호출자별 비용 상한"),
      paras: [
        l("Model spend is attributed per caller, so an agent that loops shows up as itself rather than as the platform. A caller can be given a budget; once reached, its calls are refused with a clear reason (HTTP 402). The budget is shared across backend pods.",
          "모델 비용은 호출자별로 집계되므로, 반복 호출에 빠진 에이전트가 플랫폼 전체가 아니라 그 에이전트로 드러납니다. 호출자에게 예산을 줄 수 있으며, 한도에 도달하면 명확한 사유와 함께 호출이 거부됩니다(HTTP 402). 예산은 백엔드 파드 사이에서 공유됩니다."),
        l("Usage and spend are under AI Gateway. A scheduled re-embed spends on every tick, whether or not its source changed.",
          "사용량과 비용은 AI Gateway에서 봅니다. 예약된 재임베딩은 소스가 바뀌었는지와 상관없이 실행할 때마다 비용이 듭니다."),
      ],
      links: [{ href: "/ai", label: l("Open AI Gateway", "AI Gateway 열기") }],
    },
    {
      title: l("7. Roles at a glance", "7. 역할 요약"),
      bullets: [
        l("`admin` — everything, including catalogs, grants, policies and agents.", "`admin` — 카탈로그, 권한, 정책, 에이전트를 포함한 모든 것."),
        l("`data_engineer` — sources, sync, write statements (`query:write`), catalog export and mirrors (`catalog:write`).", "`data_engineer` — 소스, 동기화, 쓰기 SQL(`query:write`), 카탈로그 내보내기와 미러(`catalog:write`)."),
        l("`ai_engineer` — Knowledge, AI generation, spend view.", "`ai_engineer` — Knowledge, AI 생성, 비용 조회."),
        l("`data_scientist` — SELECT, notebooks and experiments, Knowledge.", "`data_scientist` — SELECT, 노트북과 실험, Knowledge."),
        l("`business_analyst` — SELECT and dashboards.", "`business_analyst` — SELECT와 대시보드."),
        l("`auditor` — Governance, audit and spend, read only.", "`auditor` — Governance, 감사, 비용 (읽기 전용)."),
        l("`viewer` — read and SELECT.", "`viewer` — 읽기와 SELECT."),
        l("A service-account key or IdP token never passes the admin or human-only checks and cannot set a password.", "서비스 계정 키나 IdP 토큰은 관리자 전용·사람 전용 검사를 통과하지 못하며 비밀번호를 설정할 수 없습니다."),
      ],
    },
  ],
  limits: {
    title: l("Known limits worth saying out loud", "분명히 밝혀 둘 한계"),
    items: [
      l("**The audit trail is append-only by permission, not WORM.** The backend can run as a database role that cannot UPDATE, DELETE or TRUNCATE the audit tables; that is an operator cutover (see `docs/DEPLOY_SINGLE_NODE.md`). It is not storage-level WORM.",
        "**감사 기록은 권한상 추가 전용이며 WORM은 아닙니다.** 백엔드를 감사 테이블에 UPDATE, DELETE, TRUNCATE할 수 없는 DB 역할로 실행할 수 있으며, 이는 운영자가 전환해야 합니다(`docs/DEPLOY_SINGLE_NODE.md` 참고). 스토리지 수준의 WORM이 아닙니다."),
      l("**Catalog grants and collection access are application-level ACLs**, not database-native row security.",
        "**카탈로그 권한과 컬렉션 접근 제어는 애플리케이션 수준 ACL**이며 데이터베이스 자체의 행 수준 보안이 아닙니다."),
      l("**Sensitivity labels are not editable from the console yet.** A label raises a collection's masking floor and forbids sending its content to an external model, but today it is a database value.",
        "**민감도 라벨은 아직 콘솔에서 편집할 수 없습니다.** 라벨은 컬렉션의 마스킹 하한을 높이고 내용을 외부 모델로 보내는 것을 막지만, 현재는 데이터베이스 값입니다."),
      l("**Egress control is application-level.** Under a local-only policy the product refuses external providers and fails closed when it cannot verify one is local. It is not a network control.",
        "**외부 송신 통제는 애플리케이션 수준입니다.** 로컬 전용 정책에서는 외부 제공자를 거부하고, 로컬인지 확인할 수 없으면 닫힌 방향으로 동작합니다. 네트워크 통제가 아닙니다."),
      l("**Unstructured content is guarded, not understood.** Retrieved passages are masked and marked as data rather than instructions; instruction-shaped text is counted for an operator to see, not rewritten.",
        "**비정형 콘텐츠는 보호할 뿐 이해하지는 않습니다.** 검색된 문단은 마스킹하고 지시가 아닌 데이터로 표시합니다. 지시문처럼 보이는 텍스트는 운영자가 볼 수 있게 집계만 하고 고치지 않습니다."),
    ],
  },
}

export const METRICS: Guide = {
  crumb: l("Metrics", "Metrics"),
  title: l("Approved metrics", "승인된 메트릭"),
  subtitle: l(
    "A number an agent can cite: defined once, approved, versioned, and computed from the approved definition every time, not from SQL a model wrote for the occasion",
    "에이전트가 인용할 수 있는 숫자입니다. 한 번 정의하고 승인하고 버전을 관리하며, 매번 승인된 정의로 계산합니다. 모델이 그때그때 만든 SQL을 쓰지 않습니다",
  ),
  alert: {
    title: l("Needs a query engine", "쿼리 엔진이 필요합니다"),
    body: l(
      "Metrics sits under Lakehouse and appears when the query capability is on (Trino). It is absent on the Core profiles.",
      "Metrics는 Lakehouse 메뉴에 있으며 query 기능이 켜져 있을 때(Trino) 나타납니다. Core 프로필에는 없습니다.",
    ),
  },
  sections: [
    {
      title: l("1. Define it", "1. 정의하기"),
      paras: [
        l("Metrics → New metric. A definition names a base table and a measure: an aggregate such as `SUM(total_amount)`, or a ratio of aggregates such as `SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) / COUNT(*)`. Use the three-part name `catalog.schema.table`, so a metric can sit on a lake table or a source table.",
          "Metrics → New metric에서 만듭니다. 정의는 기준 테이블과 측정값으로 이루어집니다. `SUM(total_amount)` 같은 집계, 또는 `SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) / COUNT(*)` 같은 집계의 비율입니다. 테이블은 `catalog.schema.table` 세 부분 이름으로 지정하므로 레이크 테이블과 소스 테이블 모두에 메트릭을 만들 수 있습니다."),
        l("Optional: filters, a time column with its grains and the longest period one query may cover, and dimensions to break the number down by. Synonyms are the words people use for it (매출, sales), which is how a question finds the metric.",
          "선택 항목으로 필터, 시간 컬럼(단위와 한 번에 조회할 수 있는 최대 기간), 분해 기준이 되는 차원이 있습니다. 동의어는 사람들이 그 숫자를 부르는 말(매출, sales)이며, 질문이 메트릭을 찾는 단서가 됩니다."),
      ],
      links: [{ href: "/metrics", label: l("Open Metrics", "Metrics 열기") }],
    },
    {
      title: l("2. Approve the joins a dimension needs", "2. 차원에 필요한 조인 승인하기"),
      paras: [l("A dimension on another table (a product's category for an order line) goes through an approved join. Metrics → Joins lists candidates from query history and column names. Only many-to-one joins are accepted, so a join cannot multiply rows.",
        "다른 테이블의 차원(주문 행의 상품 카테고리 등)은 승인된 조인을 거칩니다. Metrics → Joins에 쿼리 이력과 컬럼 이름에서 찾은 후보가 나옵니다. 다대일 조인만 허용하므로 조인 때문에 행이 늘어나지 않습니다.")],
    },
    {
      title: l("3. Approve the version", "3. 버전 승인하기"),
      paras: [l("Agents only see approved versions. A change is a new version that must be approved again; the previous one keeps answering until then, and results already given keep citing the version that produced them.",
        "에이전트는 승인된 버전만 봅니다. 수정하면 새 버전이 되고 다시 승인해야 합니다. 그때까지는 이전 버전이 계속 답하며, 이미 나간 결과는 그것을 만든 버전을 계속 인용합니다.")],
    },
    {
      title: l("4. Use it", "4. 사용하기"),
      paras: [
        l("An agent, over MCP: `metric_list` to find it, `metric_values` to see which values a dimension takes before filtering, then `metric_query` with dimensions, a period, and optionally a sort and limit for a top-N. Its key needs `catalog:read` and `query:run`. See Connect an agent.",
          "에이전트는 MCP로 씁니다. `metric_list`로 찾고, 필터를 걸기 전에 `metric_values`로 차원이 가진 값을 확인한 뒤, 차원과 기간, 필요하면 정렬과 limit(top-N)을 넣어 `metric_query`를 호출합니다. 키에는 `catalog:read`와 `query:run`이 필요합니다. 자세한 내용은 Connect an agent를 보세요."),
        l("A person: Analytics → Ask AI. When the question matches a metric, Query as metric offers it, with the period and dimensions read from the question for you to confirm.",
          "사람은 Analytics → Ask AI에서 씁니다. 질문이 메트릭과 맞으면 Query as metric이 그 메트릭을 제안하고, 질문에서 읽은 기간과 차원을 확인용으로 채워 줍니다."),
      ],
      links: [
        { href: "/help/integrate", label: l("Connect an agent", "에이전트 연결") },
        { href: "/query", label: l("Open Analytics", "Analytics 열기") },
      ],
    },
    {
      title: l("5. Trace any number back", "5. 모든 숫자의 출처 추적하기"),
      paras: [l("Every result carries its citation: metric, version, approver and the exact SQL that ran, after catalog grants, row filters and masks. The call is in Governance → Tool calls as `metric.query`, citing `metric:<name>@v<N>`.",
        "모든 결과에는 인용 정보가 붙습니다. 메트릭, 버전, 승인자, 그리고 카탈로그 권한·행 필터·마스크가 적용된 뒤 실제 실행된 SQL입니다. 호출은 Governance → Tool calls에 `metric.query`로 남고 `metric:<name>@v<N>`을 인용합니다.")],
      links: [{ href: "/governance", label: l("Open Governance", "Governance 열기") }],
    },
  ],
}

export const INTEGRATE_SCOPES: { use: L; scopes: string[] }[] = [
  { use: l("Search and cited answers", "검색과 인용 답변"), scopes: ["knowledge:read", "ai:generate"] },
  { use: l("Approved metrics", "승인된 메트릭"), scopes: ["catalog:read", "query:run"] },
  { use: l("Governed SQL", "거버넌스가 적용된 SQL"), scopes: ["catalog:read", "query:run"] },
  { use: l("SQL written by the model (generate_sql)", "모델이 작성하는 SQL (generate_sql)"), scopes: ["catalog:read", "ai:generate"] },
]

export const INTEGRATE: Guide = {
  crumb: l("Integrate", "Integrate"),
  title: l("Connect an application or agent", "애플리케이션·에이전트 연결"),
  subtitle: l(
    "One identity per agent, a scoped key, then MCP, REST or an agent gateway. Every call is governed and audited as that agent.",
    "에이전트마다 하나의 계정, 범위가 제한된 키를 발급한 뒤 MCP, REST, 에이전트 게이트웨이로 호출합니다. 모든 호출은 그 에이전트로 통제되고 감사됩니다.",
  ),
  sections: [
    {
      title: l("1. Create an agent", "1. 에이전트 만들기"),
      paras: [l("Agents → New agent (admins). Make one account per agent or application, so access, audit and spend stay per agent. It is a service account: it can be scoped, expired and rotated, and it never passes admin or human-only checks.",
        "Agents → New agent에서 만듭니다(관리자). 접근, 감사, 비용이 에이전트별로 남도록 에이전트나 애플리케이션마다 계정을 하나씩 만드세요. 서비스 계정이므로 범위 제한, 만료, 교체가 가능하고 관리자 전용·사람 전용 검사는 통과하지 못합니다.")],
      links: [{ href: "/agents", label: l("Open Agents", "Agents 열기") }],
    },
    {
      title: l("2. Issue a scoped, expiring key", "2. 범위와 만료가 있는 키 발급하기"),
      paras: [l("Issue key → tick the scopes for what the agent does → choose an expiry (90 days by default). The key is shown once; store it as DATAPOND_KEY. Each key also has its own rate limit.",
        "Issue key → 에이전트가 하는 일에 맞는 scope 선택 → 만료 기간 선택(기본 90일). 키는 한 번만 표시되므로 DATAPOND_KEY로 보관하세요. 키마다 호출 빈도 제한도 따로 있습니다.")],
    },
    {
      title: l("3. Grant what it may read", "3. 읽을 수 있는 범위 부여하기"),
      bullets: [
        l("Collections and catalogs: the agent's page under Agents → Data access. Collections can also be shared from Knowledge → the collection → Members.",
          "컬렉션과 카탈로그: Agents의 해당 에이전트 페이지 → Data access. 컬렉션은 Knowledge → 컬렉션 → Members에서도 공유할 수 있습니다."),
        l("A catalog with grants needs one for the agent (or its role). Settings → Data catalogs lists them all, including the share list of each `src_<slug>` source.",
          "권한이 걸린 카탈로그는 에이전트(또는 그 역할)에 대한 권한이 있어야 합니다. Settings → Data catalogs에서 `src_<slug>` 소스의 공유 목록을 포함해 모두 볼 수 있습니다."),
        l("Rows and columns: row filters and masks under Governance apply to its SQL and its metrics. In SQL, source tables need the qualified name `catalog.schema.table`.",
          "행과 컬럼: Governance의 행 필터와 마스크가 에이전트의 SQL과 메트릭에 적용됩니다. SQL에서 소스 테이블은 `catalog.schema.table` 전체 이름이 필요합니다."),
      ],
      links: [
        { href: "/settings?tab=catalogs", label: l("Settings → Data catalogs", "Settings → Data catalogs") },
        { href: "/governance", label: l("Governance", "Governance") },
      ],
    },
  ],
}

export const INTEGRATE_CALL = {
  title: l("4. Call it", "4. 호출하기"),
  collection: l("Calls for the collection", "다음 컬렉션을 위한 호출"),
  intro: l(
    "MCP at `POST /api/mcp` exposes 30 read actions (search, cited answers, catalog, governed SQL, metrics); nothing that writes is reachable. The REST/OpenAPI surface and the gateway document at `GET /api/tools/openapi.json` cover the same tools. The reference below is read from this server.",
    "`POST /api/mcp`의 MCP는 읽기 동작 30개(검색, 인용 답변, 카탈로그, 거버넌스가 적용된 SQL, 메트릭)를 제공하며 쓰기 동작은 노출되지 않습니다. REST/OpenAPI와 `GET /api/tools/openapi.json`의 게이트웨이 문서도 같은 도구를 다룹니다. 아래 참조는 이 서버에서 읽어 온 것입니다.",
  ),
  oauth: l(
    "OAuth resource-server mode is off by default (`auth.oauthResourceServer.enabled`). When enabled, the endpoint also accepts access tokens from your IdP; the subject must match an existing DataPond user, and permissions are narrowed by `datapond:<permission>` scopes. It has not been exercised against a live IdP.",
    "OAuth 리소스 서버 모드는 기본값이 꺼짐입니다(`auth.oauthResourceServer.enabled`). 켜면 IdP가 발급한 액세스 토큰도 받으며, 토큰의 subject는 이미 있는 DataPond 사용자와 일치해야 하고 권한은 `datapond:<permission>` scope로 좁혀집니다. 실제 IdP로는 아직 검증하지 않았습니다.",
  ),
}

export const INTEGRATE_AUDIT: Section = {
  title: l("5. See what it did, and cap it", "5. 무엇을 했는지 확인하고 상한 두기"),
  paras: [
    l("The agent's page under Agents shows its recent calls, its model spend and its cap. Every call (what it read, cited and masked, and what was refused) is also in Governance → Tool calls, next to every other caller.",
      "Agents의 에이전트 페이지에서 최근 호출, 모델 비용, 상한을 볼 수 있습니다. 읽고, 인용하고, 마스킹하고, 거부당한 모든 호출은 Governance → Tool calls에도 다른 호출자와 함께 남습니다."),
    l("Set a budget per agent: past it, calls are refused with 402 instead of continuing to bill.",
      "에이전트별로 예산을 정하면, 한도를 넘는 호출은 계속 과금되지 않고 402로 거부됩니다."),
  ],
  links: [
    { href: "/agents", label: l("Agents", "Agents") },
    { href: "/governance", label: l("Governance → Tool calls", "Governance → Tool calls") },
  ],
}

/** The Operate guide: Helm values per profile, upgrade commands, what is optional. */
export const OPERATE_PAGE = {
  crumb: l("Change the configuration", "설정 변경"),
  title: l("Change this deployment's configuration", "이 배포의 설정 변경하기"),
  subtitle: l(
    "Configuration is the Helm values of the profile this deployment runs; the commands below are filled in for it. Live specs and resource usage are in",
    "설정은 이 배포가 사용하는 프로필의 Helm values입니다. 아래 명령은 이 배포에 맞게 채워져 있습니다. 실시간 사양과 리소스 사용량은 다음 화면에서 봅니다:",
  ),
}
