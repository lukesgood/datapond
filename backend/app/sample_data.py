"""The sample dataset, as data rather than as SQL text inside a request handler.

What this is for: a deployment somebody can actually look at. Five tables of one
domain join to nothing, so the relationship graph has nothing to draw, Knowledge has
no prose to embed, and every query is a single-table SELECT. Four domains that reach
into each other give all three something real to show.

Why it is structured this way:

  * Columns are declared once, and the DDL is generated from them. Hand-written DDL
    beside a column list is two truths that drift, and the first symptom is an insert
    naming a column the table does not have.
  * Foreign keys are declared, not parsed. tests/test_sample_data.py then checks that
    every one resolves — in the schema *and* in the generated rows — before anything
    reaches a database. Postgres would catch a dangling reference too, but only on a
    machine that has Postgres, and by then it is a 500 from a demo endpoint in front
    of whoever is being shown the product.
  * Rows are generated deterministically from a hash, not sampled at random. The same
    call produces the same database, so a demo is repeatable and a diff means
    something.

Referential integrity is the whole point here. An edge in the relationship graph with
nothing behind it teaches whoever is looking that the product is lying to them.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json as _json
from hashlib import sha256
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ForeignKey:
    child: str
    column: str
    parent: str
    parent_column: str = "id"


@dataclass
class Table:
    name: str
    domain: str
    columns: Dict[str, str]
    rows: List[Dict[str, Any]] = field(default_factory=list)
    references: List[ForeignKey] = field(default_factory=list)
    primary_key: str = "id"


@dataclass(frozen=True)
class JoinQuery:
    name: str
    tables: Tuple[str, ...]
    sql: str
    question: str          # what a person would have asked to write it


@dataclass(frozen=True)
class KnowledgeSource:
    collection: str
    description: str
    table: str
    column: str


# ── deterministic generation ──────────────────────────────────────────────────

def _n(*key) -> int:
    """A stable non-negative integer for a key. Same input, same database."""
    return int(sha256("\x1f".join(str(k) for k in key).encode()).hexdigest()[:8], 16)


def _pick(options, *key):
    return options[_n(*key) % len(options)]


_EPOCH = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _when(*key, span_days: int = 110) -> datetime:
    return _EPOCH + timedelta(minutes=_n("t", *key) % (span_days * 24 * 60))


# ── commerce ──────────────────────────────────────────────────────────────────

_FAMILY = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임"]
_GIVEN = ["민준", "서연", "도윤", "지우", "하준", "서윤", "예준", "지민", "시우", "수아"]
_COUNTRY = ["KR", "KR", "KR", "JP", "US", "SG"]
_TIER = ["standard", "standard", "standard", "gold", "platinum"]

CUSTOMERS = [{
    "id": i,
    "email": f"user{i:03d}@example.com",
    "full_name": _pick(_FAMILY, "fam", i) + _pick(_GIVEN, "giv", i),
    "country": _pick(_COUNTRY, "country", i),
    "tier": _pick(_TIER, "tier", i),
    "signup_date": (_EPOCH - timedelta(days=_n("signup", i) % 900)).date(),
    "is_active": _n("active", i) % 10 != 0,
} for i in range(1, 1201)]

_CATEGORY = ["hardware", "software", "service", "accessory"]
_PRODUCT_NOUN = ["스토리지 노드", "분석 워크벤치", "임베딩 게이트웨이", "카탈로그 커넥터",
                 "스트리밍 싱크", "거버넌스 콘솔", "벡터 인덱스", "쿼리 가속기"]
_PRODUCT_QUALIFIER = ["기본형", "고성능형", "확장형"]

PRODUCTS = [{
    "id": i,
    "sku": f"DP-{_pick(_CATEGORY, 'cat', i)[:2].upper()}-{i:04d}",
    "name": f"{_pick(_PRODUCT_NOUN, 'noun', i)} {_pick(_PRODUCT_QUALIFIER, 'qual', i)}",
    "category": _pick(_CATEGORY, "cat", i),
    "price": round(50000 + (_n("price", i) % 400) * 2500, 2),
    "cost": round(30000 + (_n("cost", i) % 200) * 1800, 2),
    "stock_qty": _n("stock", i) % 500,
    "is_active": True,
    # Prose, deliberately: this column is what the product-catalogue collection
    # embeds, and a column of SKUs retrieves nothing useful.
    "description": (
        f"{_pick(_PRODUCT_NOUN, 'noun', i)}는 {_pick(_CATEGORY, 'cat', i)} 계열 구성요소로, "
        f"{_pick(['단일 노드', '소규모 클러스터', '대규모 클러스터'], 'scale', i)} 환경에서 "
        f"{_pick(['수집', '검색', '재순위화', '거버넌스 감사'], 'role', i)} 경로를 담당합니다. "
        f"교체 시 다운타임은 약 {_n('dt', i) % 20 + 5}분이며, 설정은 프로파일 값으로만 바뀝니다."),
} for i in range(1, 301)]

_ORDER_STATUS = ["delivered", "delivered", "delivered", "shipped", "pending", "cancelled"]
_CHANNEL = ["web", "web", "mobile", "partner"]

ORDERS = [{
    "id": i,
    "customer_id": CUSTOMERS[_n("ocust", i) % len(CUSTOMERS)]["id"],
    "status": _pick(_ORDER_STATUS, "ostatus", i),
    "total_amount": round(60000 + (_n("amount", i) % 900) * 1500, 2),
    "discount": round((_n("disc", i) % 6) * 2500, 2),
    "channel": _pick(_CHANNEL, "chan", i),
    "ordered_at": _when("order", i),
} for i in range(1, 6001)]

ORDER_ITEMS = [{
    "id": n,
    "order_id": order["id"],
    "product_id": PRODUCTS[_n("oip", order["id"], k) % len(PRODUCTS)]["id"],
    "quantity": _n("qty", order["id"], k) % 4 + 1,
    "unit_price": round(50000 + (_n("uprice", order["id"], k) % 300) * 2500, 2),
} for n, (order, k) in enumerate(
    ((o, k) for o in ORDERS for k in range(_n("items", o["id"]) % 3 + 1)), start=1)]

_EVENT = ["view", "view", "view", "add_to_cart", "checkout", "search"]
_DEVICE = ["desktop", "mobile", "mobile", "tablet"]

PAGE_EVENTS = [{
    "id": i,
    # No declared foreign key, deliberately: an event stream outlives the accounts it
    # mentions. The relationship graph still guesses the edge from the column name,
    # and shows it dashed — which is the distinction that view exists to make.
    "customer_id": CUSTOMERS[_n("ecust", i) % len(CUSTOMERS)]["id"],
    "event_type": _pick(_EVENT, "etype", i),
    "page": _pick(["/products", "/cart", "/checkout", "/search", "/account"], "page", i),
    "device": _pick(_DEVICE, "dev", i),
    "session_id": f"s-{_n('sess', i) % 6000:05d}",
    "occurred_at": _when("event", i),
} for i in range(1, 30001)]


# ── support ───────────────────────────────────────────────────────────────────

AGENTS = [{
    "id": i,
    "name": _pick(_FAMILY, "afam", i) + _pick(_GIVEN, "agiv", i),
    "team": _pick(["tier1", "tier1", "tier2", "escalation"], "team", i),
    "hired_on": (_EPOCH - timedelta(days=_n("hire", i) % 1500)).date(),
} for i in range(1, 41)]

_TICKET_SUBJECT = ["배송 지연 문의", "결제 오류", "제품 설정 문의", "환불 요청",
                   "계정 접근 불가", "성능 저하 신고"]
_TICKET_STATUS = ["resolved", "resolved", "resolved", "open", "pending"]

SUPPORT_TICKETS = [{
    "id": i,
    # Reaches into commerce twice: the person, and the specific order they are
    # asking about. Two edges, not one, and both are queried below.
    "customer_id": CUSTOMERS[_n("tcust", i) % len(CUSTOMERS)]["id"],
    "order_id": (ORDERS[_n("torder", i) % len(ORDERS)]["id"]
                 if _n("hasorder", i) % 4 else None),
    "agent_id": AGENTS[_n("tagent", i) % len(AGENTS)]["id"],
    "subject": _pick(_TICKET_SUBJECT, "subj", i),
    "status": _pick(_TICKET_STATUS, "tstatus", i),
    "priority": _pick(["low", "normal", "normal", "high", "urgent"], "prio", i),
    "opened_at": _when("ticket", i),
} for i in range(1, 1501)]

# Composed, not picked. Subject-keyed content was the right half — a refund ticket
# must read about refunds — but choosing from a fixed list caps the corpus at as many
# openings as the list is long: six subjects x two bodies gave 18 distinct first-40
# characters across 3006 messages, and retrieval still returned near-identical
# passages. The pieces below combine, the way products.description always did, so the
# opening varies per message instead of per subject.
_WHEN = ["어제 오후부터", "지난주 금요일에", "오늘 오전에", "이번 주 들어",
         "주문 직후부터", "업데이트를 적용한 뒤"]

_SYMPTOM_BY_SUBJECT = {
    "배송 지연 문의": [
        "주문한 상품이 예정일을 사흘 넘겨 도착했습니다",
        "배송 상태가 '발송됨'에서 더 이상 바뀌지 않습니다",
        "배송 예정일이 두 번 변경되었는데 안내를 받지 못했습니다",
        "받는 주소를 수정했는데 이전 주소로 출고된 것 같습니다",
    ],
    "결제 오류": [
        "결제 시도 시 카드 승인이 반복해서 거절됩니다",
        "같은 금액이 두 번 청구된 것으로 보입니다",
        "결제는 완료됐는데 주문 내역에 반영되지 않았습니다",
        "할인 코드가 적용되지 않은 채로 결제가 끝났습니다",
    ],
    "제품 설정 문의": [
        "프로파일 값을 바꾼 뒤 서비스가 기동되지 않습니다",
        "초기 설치 후 어떤 값을 기본으로 두어야 하는지 문서에서 찾지 못했습니다",
        "설정을 되돌렸는데도 이전 동작으로 돌아오지 않습니다",
        "환경별로 설정이 달라야 하는지 판단이 서지 않습니다",
    ],
    "환불 요청": [
        "환불을 요청드립니다. 반품 회수는 이미 완료된 것으로 확인됩니다",
        "부분 환불이 가능한지 문의드립니다. 두 개 중 하나만 반품했습니다",
        "환불 예정 금액이 결제 금액과 달라 계산 근거를 알고 싶습니다",
        "환불이 승인됐다는 안내는 받았는데 입금이 확인되지 않습니다",
    ],
    "계정 접근 불가": [
        "계정에 로그인할 수 없고 비밀번호 재설정 메일도 오지 않습니다",
        "이중 인증 기기를 교체한 뒤로 인증 코드가 맞지 않습니다",
        "로그인 시도가 계속 실패해 계정이 잠긴 것 같습니다",
        "담당자가 퇴사해 관리자 계정에 접근할 수 없습니다",
    ],
    "성능 저하 신고": [
        "조회 응답이 평소 2초에서 20초 이상으로 늘어났습니다",
        "대량 조회 시 간헐적으로 시간 초과가 발생합니다",
        "같은 질의인데 실행할 때마다 소요 시간이 크게 다릅니다",
        "동시 사용자가 늘면 응답이 급격히 느려집니다",
    ],
}

_CONTEXT = [
    "다른 기기에서도 동일하게 재현됩니다.",
    "같은 조건에서 지난달에는 문제가 없었습니다.",
    "재현 조건을 좁히지 못해 로그를 함께 첨부합니다.",
    "영향 범위가 어디까지인지 파악이 어렵습니다.",
    "임시로 우회했지만 근본 원인은 알지 못합니다.",
]

_ACK = ["확인해 주셔서 감사합니다.", "문의 주신 내용 확인했습니다.",
        "담당 팀에 전달했습니다.", "이력을 조회해 보았습니다.",
        "말씀하신 증상을 재현해 보았습니다."]

_RESOLUTION_BY_SUBJECT = {
    "배송 지연 문의": "배송사에 추적을 요청했고 현재 위치와 재배송 일정을 확인해 회신드리겠습니다.",
    "결제 오류": "결제 로그에서 승인 요청이 중복 전송된 이력을 확인했고, 중복 건은 취소 처리하겠습니다.",
    "제품 설정 문의": "원인은 캐시 계층의 권한 설정으로 확인되었으며 수정 배포는 오늘 중 적용됩니다.",
    "환불 요청": "환불은 회수 확인 후 영업일 기준 3~5일 내 결제 수단으로 환급되며, 부분 환불은 반품 수량 기준으로 계산됩니다. 배송비는 정책에 따라 차감될 수 있습니다.",
    "계정 접근 불가": "계정 잠금을 해제하고 재설정 메일을 다시 발송했습니다. 수신함을 확인해 주세요.",
    "성능 저하 신고": "해당 시간대의 질의 계획을 확인하고 있으며, 통계 갱신 후 응답 시간이 회복되는지 함께 보겠습니다.",
}

_MESSAGE_TAIL = [
    "회신은 등록된 이메일로 받고 싶습니다.",
    "담당자 배정 후 진행 상황을 공유해 주세요.",
    "동일 증상이 재현되면 로그를 첨부해 다시 올리겠습니다.",
    "처리 완료까지 예상 소요 시간을 알려주시면 좋겠습니다.",
    "우선순위 조정이 필요하면 알려주세요.",
    "관련 주문 번호를 함께 확인 부탁드립니다.",
    "동일 문의가 반복되지 않도록 원인을 기록해 두었습니다.",
]

TICKET_MESSAGES = [{
    "id": n,
    "ticket_id": ticket["id"],
    "sender": "customer" if k == 0 else _pick(["agent", "customer"], "sender", ticket["id"], k),
    # The support knowledge base embeds this column.
    # Varied per message, not picked whole. Five bodies reused verbatim gave the
    # support collection 1000 chunks of 5 distinct texts (0.5% unique), and vector
    # search then returned the same sentence five times for any query — retrieval
    # looked broken when the corpus was. products.description was always fine at 98%
    # unique because it composes its pieces from `i`; this now does the same.
    # Keyed on the ticket's own subject so the first clause already says what this is
    # about, then varied per message. A refund ticket now reads about refunds; before,
    # "환불" appeared only in a parenthetical appended to an unrelated body.
    # Opening varies per message: when x symptom for a customer turn, acknowledgement
    # x subject for an agent's. The subject still decides what it is about.
    "body": ((f"{_pick(_WHEN, 'when', ticket['id'], k)} "
              f"{_pick(_SYMPTOM_BY_SUBJECT[ticket['subject']], 'sym', ticket['id'], k)}. "
              f"{_pick(_CONTEXT, 'ctx', ticket['id'], k)}")
             if k == 0 else
             (f"{_pick(_ACK, 'ack', ticket['id'], k)} "
              f"{_RESOLUTION_BY_SUBJECT[ticket['subject']]}")
             ) + f" (티켓 {ticket['id']}) " + _pick(_MESSAGE_TAIL, "tail", ticket["id"], k),
    "sent_at": ticket["opened_at"] + timedelta(hours=k * 3 + 1),
} for n, (ticket, k) in enumerate(
    ((t, k) for t in SUPPORT_TICKETS for k in range(_n("msgs", t["id"]) % 3 + 1)), start=1)]


# ── logistics ─────────────────────────────────────────────────────────────────

WAREHOUSES = [
    {"id": 1, "code": "ICN", "city": "인천", "country": "KR", "capacity_units": 120000},
    {"id": 2, "code": "NRT", "city": "나리타", "country": "JP", "capacity_units": 64000},
    {"id": 3, "code": "SIN", "city": "싱가포르", "country": "SG", "capacity_units": 48000},
    # `code` is UNIQUE and these are hand-written, so each one is spelled out rather
    # than generated. Eight warehouses also widen `inventory`, which is products x
    # warehouses and is the one table that multiplies.
    {"id": 4, "code": "PUS", "city": "부산", "country": "KR", "capacity_units": 90000},
    {"id": 5, "code": "HKG", "city": "홍콩", "country": "HK", "capacity_units": 52000},
    {"id": 6, "code": "FRA", "city": "프랑크푸르트", "country": "DE", "capacity_units": 71000},
    {"id": 7, "code": "LAX", "city": "로스앤젤레스", "country": "US", "capacity_units": 83000},
    {"id": 8, "code": "SYD", "city": "시드니", "country": "AU", "capacity_units": 36000},
]

_CARRIER = ["대한통운", "한진", "우체국", "DHL"]

SHIPMENTS = [{
    "id": n,
    "order_id": order["id"],
    "warehouse_id": WAREHOUSES[_n("swh", order["id"]) % len(WAREHOUSES)]["id"],
    "carrier": _pick(_CARRIER, "carrier", order["id"]),
    "tracking_no": f"TRK{_n('trk', order['id']) % 10**9:09d}",
    "status": "delivered" if order["status"] == "delivered" else "in_transit",
    "shipped_at": order["ordered_at"] + timedelta(hours=_n("ship", order["id"]) % 72 + 4),
    "delivered_at": (order["ordered_at"] + timedelta(days=_n("deliv", order["id"]) % 6 + 2)
                     if order["status"] == "delivered" else None),
} for n, order in enumerate(
    (o for o in ORDERS if o["status"] in ("delivered", "shipped")), start=1)]

INVENTORY = [{
    "id": n,
    "product_id": product["id"],
    "warehouse_id": warehouse["id"],
    "on_hand": _n("onhand", product["id"], warehouse["id"]) % 400,
    "reserved": _n("resv", product["id"], warehouse["id"]) % 40,
    "reorder_point": 50,
    "counted_at": _when("count", product["id"], warehouse["id"], span_days=30),
} for n, (product, warehouse) in enumerate(
    ((p, w) for p in PRODUCTS for w in WAREHOUSES), start=1)]


# ── marketing ─────────────────────────────────────────────────────────────────

CAMPAIGNS = [{
    "id": i,
    "name": name,
    "channel": channel,
    "started_on": (_EPOCH - timedelta(days=days)).date(),
    "budget": budget,
    # The runbook collection embeds this column.
    "brief": brief,
} for i, (name, channel, days, budget, brief) in enumerate([
    ("여름 스토리지 프로모션", "email", 90, 12000000,
     "여름 시즌 스토리지 계열 제품을 대상으로 기존 고객 재구매를 유도한다. "
     "골드 등급 이상 고객에게 우선 발송하며, 장바구니 이탈 세그먼트를 2차 대상으로 둔다."),
    ("신규 가입 온보딩", "email", 200, 4000000,
     "가입 후 14일 이내 첫 주문이 없는 고객에게 온보딩 시퀀스를 발송한다. "
     "성공 지표는 첫 주문 전환율이며, 제품 문서 조회를 보조 지표로 본다."),
    ("분석 워크벤치 런칭", "paid_search", 45, 30000000,
     "분석 워크벤치 신규 라인 출시에 맞춘 검색 광고 집행. "
     "소프트웨어 카테고리 검색 의도를 대상으로 하며 파트너 채널 유입과 중복을 제거한다."),
    ("이탈 고객 회수", "sms", 30, 6000000,
     "최근 120일간 주문이 없는 고객 중 과거 2회 이상 구매 이력이 있는 대상에게 "
     "한정 할인을 발송한다. 발송 빈도는 주 1회를 넘기지 않는다."),
    ("파트너 공동 마케팅", "partner", 60, 18000000,
     "파트너 채널을 통한 공동 프로모션. 파트너 유입 주문은 채널 값으로 구분되며, "
     "정산은 배송 완료 기준으로 집계한다."),
], start=1)]

CAMPAIGN_TOUCHES = [{
    "id": i,
    "campaign_id": CAMPAIGNS[_n("tcamp", i) % len(CAMPAIGNS)]["id"],
    "customer_id": CUSTOMERS[_n("tcust2", i) % len(CUSTOMERS)]["id"],
    "touched_at": _when("touch", i),
    "outcome": _pick(["delivered", "delivered", "opened", "clicked", "bounced"], "outc", i),
    "session_id": f"s-{_n('tsess', i) % 6000:05d}",
} for i in range(1, 8001)]


# ── telemetry ─────────────────────────────────────────────────────────────────
# Shapes the four commercial domains do not have: a time series, a semi-structured
# payload, and a prose corpus long enough to retrieve against. Charts drawn from
# `orders` are bar charts of categories; nothing here could draw a line over time,
# and Knowledge had three short prose columns and nothing resembling a document.

_SERVICE = ["backend", "frontend", "litellm", "postgres", "valkey"]
_METRIC = ["cpu_percent", "memory_mb", "request_rate", "p95_latency_ms"]

SERVICE_METRICS = [{
    "id": i,
    "service": _pick(_SERVICE, "svc", i),
    "metric": _pick(_METRIC, "met", i),
    # A walk rather than noise: a flat random series makes every line chart look the
    # same and teaches nothing about the data.
    "value": round(20 + (_n("mval", i) % 60) + (i % 240) * 0.05, 2),
    "observed_at": _EPOCH + timedelta(minutes=(i % 2880) * 5),
} for i in range(1, 12001)]

_API_PATH = ["/api/ai/rag", "/api/ai/search", "/api/queries/execute",
             "/api/catalog/schemas", "/api/connectors", "/api/auth/login"]
_API_METHOD = ["GET", "GET", "GET", "POST", "POST"]

API_EVENTS = [{
    "id": i,
    "customer_id": CUSTOMERS[_n("acust", i) % len(CUSTOMERS)]["id"],
    "path": _pick(_API_PATH, "apath", i),
    "method": _pick(_API_METHOD, "amethod", i),
    "status_code": _pick([200, 200, 200, 200, 400, 403, 500], "acode", i),
    "latency_ms": _n("alat", i) % 1800 + 12,
    # The semi-structured column. json.dumps here, cast in the insert: asyncpg sends
    # a str and Postgres will not coerce text into jsonb by itself.
    "payload": _json.dumps({
        "request_id": f"req-{_n('areq', i) % 10**8:08d}",
        "client": _pick(["sdk-python", "sdk-node", "curl", "console"], "acli", i),
        "tokens": {"prompt": _n("atp", i) % 900, "completion": _n("atc", i) % 400},
        "flags": [f for f in ("cached", "reranked", "masked")
                  if _n("aflag", i, f) % 3 == 0],
    }, ensure_ascii=False),
    "occurred_at": _when("api", i),
} for i in range(1, 9001)]

_ARTICLE_TOPIC = [
    ("컬렉션 재임베딩이 지연될 때 확인할 것",
     "재임베딩이 예정 시각에 돌지 않는 경우, 먼저 컬렉션의 refresh_enabled 와 "
     "refresh_interval_minutes 를 확인합니다. 스케줄러는 인프로세스로 동작하며 복제본이 "
     "여럿이어도 advisory lock 으로 한 번만 수행됩니다. 소스가 가리키는 스키마와 테이블이 "
     "동기화 이후 이름이 바뀌었다면 재임베딩은 성공으로 기록되지만 아무 문서도 갱신되지 "
     "않습니다. 마지막 수행 시각과 문서 수를 함께 보는 것이 가장 빠른 판별법입니다."),
    ("외부 모델로 데이터가 나가지 않게 하는 방법",
     "egress 정책을 local-only 로 두면 임베딩과 채팅 모두 외부 제공자를 차단합니다. "
     "이 판정은 fail-closed 입니다 — 게이트웨이를 조회할 수 없어 제공자가 로컬임을 "
     "증명하지 못하면 호출을 막습니다. 다만 이것은 애플리케이션 수준 통제이며 네트워크 "
     "차단이 아니므로, 망 분리가 요구되는 환경에서는 별도의 네트워크 정책이 필요합니다."),
    ("감사 로그가 지워지지 않도록 하는 구성",
     "런타임이 감사 테이블을 수정하지 못하게 하려면 소유자가 아닌 별도 역할로 접속해야 "
     "합니다. 마이그레이션이 만드는 역할은 DML 은 가지되 세 감사 테이블에 대한 UPDATE 와 "
     "DELETE 가 회수되어 있습니다. 전환 후에는 접속 role 과 UPDATE 거부 여부를 함께 "
     "확인해야 하며, 마이그레이션 작업은 스키마를 바꿔야 하므로 소유자 자격을 유지합니다."),
    ("개인정보 마스킹 범위를 컬렉션별로 좁히는 법",
     "배포 전체 기본값 위에 컬렉션과 호출자 단위로 더 엄격한 모드를 걸 수 있습니다. "
     "완화는 불가능하며 언제나 가장 엄격한 값이 적용됩니다. 주민등록번호와 신용카드는 "
     "체크섬까지 검증하므로 무작위 숫자열의 오탐이 적고, 자격증명은 이름이 붙은 대입 "
     "형태이거나 구조적으로 명백한 경우에만 탐지합니다."),
    ("검색 결과가 비어 있을 때의 점검 순서",
     "먼저 컬렉션에 문서가 적재되었는지 확인하고, 그 다음 임베딩 차원이 저장된 벡터와 "
     "일치하는지 봅니다. 모델을 바꾸면 차원이 달라질 수 있고, 차원이 어긋나면 적재는 "
     "실패하지만 검색은 조용히 0건을 돌려줍니다. 재순위화 모델이 설정되어 있으나 응답하지 "
     "않는 경우에는 유사도 순서로 대체되며 검색이 실패하지는 않습니다."),
]

# Same reason as the ticket bodies: five articles repeated verbatim made 60 chunks
# of 5 distinct texts, so every query into the runbook returned the same paragraph.
_ARTICLE_SCOPE = ["단일 노드 배포", "다중 복제본 배포", "에어갭 환경",
                  "외부 모델 사용 배포", "온프레미스 모델 배포"]
_ARTICLE_TRIGGER = ["배포 직후", "스케줄 실패가 반복될 때", "모델을 교체한 뒤",
                    "권한 변경 이후", "감사 지적을 받은 뒤"]

KNOWLEDGE_ARTICLES = [{
    "id": i,
    "title": f"{_ARTICLE_TOPIC[(i - 1) % len(_ARTICLE_TOPIC)][0]} — {_pick(_ARTICLE_SCOPE, 'scope', i)}",
    "category": _pick(["운영", "보안", "거버넌스", "검색"], "acat", i),
    # Long-form prose. The three existing sources are a product blurb, a support
    # message and a campaign brief; none of them is a document.
    # The frame goes first. Five topic paragraphs repeated verbatim left 60 articles
    # with five distinct openings; leading with category x scope x trigger varies what
    # an embedding sees from the first words.
    "body": (f"[{_pick(['운영', '보안', '거버넌스', '검색'], 'acat', i)}] "
             f"{_pick(_ARTICLE_SCOPE, 'scope', i)}에서 "
             f"{_pick(_ARTICLE_TRIGGER, 'trig', i)} 확인하는 절차입니다. "
             f"점검 주기는 {_n('cycle', i) % 4 * 7 + 7}일입니다.\n\n"
             + _ARTICLE_TOPIC[(i - 1) % len(_ARTICLE_TOPIC)][1]),
    "published_on": (_EPOCH - timedelta(days=_n("apub", i) % 400)).date(),
} for i in range(1, 61)]


# ── the dataset ───────────────────────────────────────────────────────────────

DATASET: List[Table] = [
    Table("customers", "commerce", {
        "id": "SERIAL PRIMARY KEY", "email": "VARCHAR(255) UNIQUE NOT NULL",
        "full_name": "VARCHAR(100) NOT NULL", "country": "VARCHAR(50) DEFAULT 'KR'",
        "tier": "VARCHAR(20) DEFAULT 'standard'", "signup_date": "DATE",
        "is_active": "BOOLEAN DEFAULT true",
    }, CUSTOMERS),
    Table("products", "commerce", {
        "id": "SERIAL PRIMARY KEY", "sku": "VARCHAR(50) UNIQUE NOT NULL",
        "name": "VARCHAR(255) NOT NULL", "category": "VARCHAR(50) NOT NULL",
        "price": "NUMERIC(10,2) NOT NULL", "cost": "NUMERIC(10,2)",
        "stock_qty": "INTEGER DEFAULT 0", "is_active": "BOOLEAN DEFAULT true",
        "description": "TEXT",
    }, PRODUCTS),
    Table("orders", "commerce", {
        "id": "SERIAL PRIMARY KEY", "customer_id": "INTEGER",
        "status": "VARCHAR(20) DEFAULT 'pending'", "total_amount": "NUMERIC(10,2) NOT NULL",
        "discount": "NUMERIC(10,2) DEFAULT 0", "channel": "VARCHAR(30) DEFAULT 'web'",
        "ordered_at": "TIMESTAMPTZ",
    }, ORDERS, [ForeignKey("orders", "customer_id", "customers")]),
    Table("order_items", "commerce", {
        "id": "SERIAL PRIMARY KEY", "order_id": "INTEGER", "product_id": "INTEGER",
        "quantity": "INTEGER NOT NULL DEFAULT 1", "unit_price": "NUMERIC(10,2) NOT NULL",
    }, ORDER_ITEMS, [ForeignKey("order_items", "order_id", "orders"),
                     ForeignKey("order_items", "product_id", "products")]),
    Table("page_events", "commerce", {
        "id": "BIGSERIAL PRIMARY KEY", "customer_id": "INTEGER",
        "event_type": "VARCHAR(50) NOT NULL", "page": "VARCHAR(255)",
        "device": "VARCHAR(20) DEFAULT 'desktop'", "session_id": "VARCHAR(64)",
        "occurred_at": "TIMESTAMPTZ",
    }, PAGE_EVENTS),

    Table("agents", "support", {
        "id": "SERIAL PRIMARY KEY", "name": "VARCHAR(100) NOT NULL",
        "team": "VARCHAR(30) NOT NULL", "hired_on": "DATE",
    }, AGENTS),
    Table("support_tickets", "support", {
        "id": "SERIAL PRIMARY KEY", "customer_id": "INTEGER", "order_id": "INTEGER",
        "agent_id": "INTEGER", "subject": "VARCHAR(255) NOT NULL",
        "status": "VARCHAR(20) DEFAULT 'open'", "priority": "VARCHAR(20) DEFAULT 'normal'",
        "opened_at": "TIMESTAMPTZ",
    }, SUPPORT_TICKETS, [ForeignKey("support_tickets", "customer_id", "customers"),
                         ForeignKey("support_tickets", "order_id", "orders"),
                         ForeignKey("support_tickets", "agent_id", "agents")]),
    Table("ticket_messages", "support", {
        "id": "SERIAL PRIMARY KEY", "ticket_id": "INTEGER",
        "sender": "VARCHAR(20) NOT NULL", "body": "TEXT NOT NULL",
        "sent_at": "TIMESTAMPTZ",
    }, TICKET_MESSAGES, [ForeignKey("ticket_messages", "ticket_id", "support_tickets")]),

    Table("warehouses", "logistics", {
        "id": "SERIAL PRIMARY KEY", "code": "VARCHAR(10) UNIQUE NOT NULL",
        "city": "VARCHAR(100) NOT NULL", "country": "VARCHAR(50) NOT NULL",
        "capacity_units": "INTEGER NOT NULL",
    }, WAREHOUSES),
    Table("shipments", "logistics", {
        "id": "SERIAL PRIMARY KEY", "order_id": "INTEGER", "warehouse_id": "INTEGER",
        "carrier": "VARCHAR(50) NOT NULL", "tracking_no": "VARCHAR(50)",
        "status": "VARCHAR(20) DEFAULT 'in_transit'",
        "shipped_at": "TIMESTAMPTZ", "delivered_at": "TIMESTAMPTZ",
    }, SHIPMENTS, [ForeignKey("shipments", "order_id", "orders"),
                   ForeignKey("shipments", "warehouse_id", "warehouses")]),
    Table("inventory", "logistics", {
        "id": "SERIAL PRIMARY KEY", "product_id": "INTEGER", "warehouse_id": "INTEGER",
        "on_hand": "INTEGER NOT NULL DEFAULT 0", "reserved": "INTEGER NOT NULL DEFAULT 0",
        "reorder_point": "INTEGER NOT NULL DEFAULT 0", "counted_at": "TIMESTAMPTZ",
    }, INVENTORY, [ForeignKey("inventory", "product_id", "products"),
                   ForeignKey("inventory", "warehouse_id", "warehouses")]),

    Table("campaigns", "marketing", {
        "id": "SERIAL PRIMARY KEY", "name": "VARCHAR(255) NOT NULL",
        "channel": "VARCHAR(30) NOT NULL", "started_on": "DATE",
        "budget": "NUMERIC(14,2)", "brief": "TEXT",
    }, CAMPAIGNS),
    Table("service_metrics", "telemetry", {
        "id": "BIGSERIAL PRIMARY KEY", "service": "VARCHAR(50) NOT NULL",
        "metric": "VARCHAR(50) NOT NULL", "value": "DOUBLE PRECISION NOT NULL",
        "observed_at": "TIMESTAMPTZ NOT NULL",
    }, SERVICE_METRICS),
    Table("api_events", "telemetry", {
        "id": "BIGSERIAL PRIMARY KEY", "customer_id": "INTEGER",
        "path": "VARCHAR(255) NOT NULL", "method": "VARCHAR(10) NOT NULL",
        "status_code": "INTEGER NOT NULL", "latency_ms": "INTEGER NOT NULL",
        "payload": "JSONB", "occurred_at": "TIMESTAMPTZ",
    }, API_EVENTS, [ForeignKey("api_events", "customer_id", "customers")]),
    Table("knowledge_articles", "telemetry", {
        "id": "SERIAL PRIMARY KEY", "title": "VARCHAR(255) NOT NULL",
        "category": "VARCHAR(50) NOT NULL", "body": "TEXT NOT NULL",
        "published_on": "DATE",
    }, KNOWLEDGE_ARTICLES),

    Table("campaign_touches", "marketing", {
        "id": "SERIAL PRIMARY KEY", "campaign_id": "INTEGER", "customer_id": "INTEGER",
        "touched_at": "TIMESTAMPTZ", "outcome": "VARCHAR(20)", "session_id": "VARCHAR(64)",
    }, CAMPAIGN_TOUCHES, [ForeignKey("campaign_touches", "campaign_id", "campaigns"),
                          ForeignKey("campaign_touches", "customer_id", "customers")]),
]


def table_names() -> List[str]:
    return [t.name for t in DATASET]


def table(name: str) -> Table:
    for t in DATASET:
        if t.name == name:
            return t
    raise KeyError(name)


def foreign_keys() -> List[ForeignKey]:
    return [fk for t in DATASET for fk in t.references]


# ── generated SQL ─────────────────────────────────────────────────────────────

def ddl_statement(t: Table) -> str:
    """CREATE TABLE from the declared columns, so the two cannot drift."""
    by_child = {fk.column: fk for fk in t.references}
    lines = []
    for name, spec in t.columns.items():
        fk = by_child.get(name)
        suffix = f" REFERENCES {fk.parent}({fk.parent_column})" if fk else ""
        lines.append(f"    {name} {spec}{suffix}")
    return (f"CREATE TABLE IF NOT EXISTS {t.name} (\n" + ",\n".join(lines) + "\n);")


def column_backfill_statements() -> List[str]:
    """ALTER for every column, because CREATE TABLE IF NOT EXISTS does nothing to a
    table that already exists.

    A deployment seeded before a column was added would otherwise never get it, and
    the insert then fails on exactly the column that is missing — which is what would
    have happened to `products.description` on every environment already running.
    """
    statements = []
    for t in DATASET:
        for name, spec in t.columns.items():
            if "PRIMARY KEY" in spec:
                continue
            # Type only: defaults and constraints belong to the create, and adding
            # NOT NULL to a populated table would fail.
            sql_type = spec.split(" DEFAULT ")[0].replace(" NOT NULL", "").replace(" UNIQUE", "")
            statements.append(
                f"ALTER TABLE {t.name} ADD COLUMN IF NOT EXISTS {name} {sql_type};")
    return statements


# The Bind message carries its parameter count as a SIGNED int16, so the ceiling is
# 32767 — not the 65535 an unsigned reading suggests. asyncpg refuses past it with
# "the number of query arguments cannot exceed 32767", which is how the real limit
# was learned: seeding died on `orders` at 6000 rows x 7 columns = 42,000.
#
# At the original scale the widest table was 300 rows of 7 columns, nowhere near
# either number. Deriving the chunk from the table's own width means no table has to
# be thought about again; the margin below leaves room for a table gaining a column.
MAX_BIND_PARAMS = 30000


def _rows_per_statement(column_count: int) -> int:
    return max(1, MAX_BIND_PARAMS // max(1, column_count))


def _cast_for(spec: str) -> str:
    """The cast a placeholder needs, from the column's declared type.

    asyncpg sends a Python str as text, and Postgres will not coerce text into jsonb
    on its own — "column is of type jsonb but expression is of type text". Every
    other jsonb write in this codebase spells the cast out ($5::jsonb); deriving it
    from the declaration keeps the two from drifting when a column is added.
    """
    declared = spec.strip().upper()
    if declared.startswith("JSONB"):
        return "::jsonb"
    return ""


def _insert_for(t: Table, rows: List[Dict[str, Any]]) -> Tuple[str, List[Any]]:
    columns = list(t.columns)
    casts = [_cast_for(t.columns[c]) for c in columns]
    args: List[Any] = []
    tuples = []
    for row in rows:
        placeholders = []
        for column, cast in zip(columns, casts):
            args.append(row[column])
            placeholders.append(f"${len(args)}{cast}")
        tuples.append("(" + ", ".join(placeholders) + ")")
    sql = (f"INSERT INTO {t.name} ({', '.join(columns)}) VALUES\n"
           + ",\n".join(tuples) + "\nON CONFLICT DO NOTHING")
    return sql, args


def insert_statements(t: Table) -> List[Tuple[str, List[Any]]]:
    """The table's rows as one or more multi-row INSERTs, each within the bind limit.

    Bound, not interpolated: the seed is prose, and Korean support tickets contain
    apostrophes. Columns are named because a positional insert breaks the moment a
    column is added in the middle.
    """
    size = _rows_per_statement(len(t.columns))
    return [_insert_for(t, t.rows[i:i + size]) for i in range(0, len(t.rows), size)]


def insert_statement(t: Table) -> Tuple[str, List[Any]]:
    """The first (often only) statement for this table. Anything writing to a database
    wants insert_statements(); this stays for the single-statement case."""
    return insert_statements(t)[0]


def sequence_reset_statements() -> List[str]:
    """Rows carry explicit ids so foreign keys can be checked before insert. That
    leaves every SERIAL sequence at 1, and the next real insert collides."""
    return [
        f"SELECT setval(pg_get_serial_sequence('{t.name}', '{t.primary_key}'), "
        f"(SELECT COALESCE(MAX({t.primary_key}), 1) FROM {t.name}));"
        for t in DATASET if "SERIAL" in t.columns.get(t.primary_key, "")
    ]


# ── the queries that make relationship edges observed ─────────────────────────
# The graph draws an edge solid only when a join appears in query_history. Naming
# convention alone draws it dashed. Running these after the sync is what turns the
# declared schema into an observed one — see /catalog/relationships.

JOIN_QUERIES: List[JoinQuery] = [
    JoinQuery("tickets_by_customer_tier", ("support_tickets", "customers"),
              "SELECT c.tier, count(*) AS tickets\n"
              "FROM support_tickets t JOIN customers c ON t.customer_id = c.id\n"
              "GROUP BY c.tier ORDER BY tickets DESC",
              "등급별로 지원 티켓이 몇 건인가?"),
    JoinQuery("tickets_per_order", ("support_tickets", "orders"),
              "SELECT o.status, count(*) AS tickets\n"
              "FROM support_tickets t JOIN orders o ON t.order_id = o.id\n"
              "GROUP BY o.status ORDER BY tickets DESC",
              "주문 상태별로 문의가 얼마나 들어오나?"),
    JoinQuery("ticket_threads", ("ticket_messages", "support_tickets"),
              "SELECT t.priority, count(m.id) AS messages\n"
              "FROM ticket_messages m JOIN support_tickets t ON m.ticket_id = t.id\n"
              "GROUP BY t.priority ORDER BY messages DESC",
              "우선순위가 높은 티켓일수록 대화가 길어지나?"),
    JoinQuery("agent_load", ("support_tickets", "agents"),
              "SELECT a.team, count(*) AS tickets\n"
              "FROM support_tickets t JOIN agents a ON t.agent_id = a.id\n"
              "GROUP BY a.team ORDER BY tickets DESC",
              "팀별 티켓 처리량은?"),
    JoinQuery("shipment_lead_time", ("shipments", "orders"),
              "SELECT o.channel, count(*) AS shipments\n"
              "FROM shipments s JOIN orders o ON s.order_id = o.id\n"
              "GROUP BY o.channel ORDER BY shipments DESC",
              "채널별 배송 건수는?"),
    JoinQuery("stock_by_product", ("inventory", "products"),
              "SELECT p.category, sum(i.on_hand) AS on_hand\n"
              "FROM inventory i JOIN products p ON i.product_id = p.id\n"
              "GROUP BY p.category ORDER BY on_hand DESC",
              "카테고리별 재고는 얼마나 남았나?"),
    JoinQuery("stock_by_warehouse", ("inventory", "warehouses"),
              "SELECT w.code, sum(i.on_hand) AS on_hand\n"
              "FROM inventory i JOIN warehouses w ON i.warehouse_id = w.id\n"
              "GROUP BY w.code ORDER BY on_hand DESC",
              "창고별 재고 총량은?"),
    JoinQuery("shipments_by_warehouse", ("shipments", "warehouses"),
              "SELECT w.city, count(*) AS shipments\n"
              "FROM shipments s JOIN warehouses w ON s.warehouse_id = w.id\n"
              "GROUP BY w.city ORDER BY shipments DESC",
              "어느 창고에서 가장 많이 나갔나?"),
    JoinQuery("campaign_reach", ("campaign_touches", "customers"),
              "SELECT c.country, count(*) AS touches\n"
              "FROM campaign_touches t JOIN customers c ON t.customer_id = c.id\n"
              "GROUP BY c.country ORDER BY touches DESC",
              "국가별로 캠페인이 얼마나 도달했나?"),
    JoinQuery("campaign_outcomes", ("campaign_touches", "campaigns"),
              "SELECT ca.name, count(*) AS touches\n"
              "FROM campaign_touches t JOIN campaigns ca ON t.campaign_id = ca.id\n"
              "GROUP BY ca.name ORDER BY touches DESC",
              "캠페인별 발송 건수는?"),
    JoinQuery("revenue_by_category", ("order_items", "products"),
              "SELECT p.category, sum(oi.quantity * oi.unit_price) AS revenue\n"
              "FROM order_items oi JOIN products p ON oi.product_id = p.id\n"
              "GROUP BY p.category ORDER BY revenue DESC",
              "카테고리별 매출은?"),
    JoinQuery("orders_per_customer", ("orders", "customers"),
              "SELECT c.tier, count(*) AS orders\n"
              "FROM orders o JOIN customers c ON o.customer_id = c.id\n"
              "GROUP BY c.tier ORDER BY orders DESC",
              "등급별 주문 건수는?"),
    JoinQuery("api_traffic_by_tier", ("api_events", "customers"),
              "SELECT c.tier, count(*) AS calls\n"
              "FROM api_events e JOIN customers c ON e.customer_id = c.id\n"
              "GROUP BY c.tier ORDER BY calls DESC",
              "등급별로 API 를 얼마나 호출하나?"),
    JoinQuery("basket_size", ("order_items", "orders"),
              "SELECT o.channel, avg(oi.quantity) AS avg_qty\n"
              "FROM order_items oi JOIN orders o ON oi.order_id = o.id\n"
              "GROUP BY o.channel ORDER BY avg_qty DESC",
              "채널별 평균 구매 수량은?"),
]


# ── knowledge ─────────────────────────────────────────────────────────────────
# Every collection ingests a column that holds prose. A column of SKUs embeds fine and
# retrieves nothing, which looks like the retrieval is broken rather than the source.

KNOWLEDGE_SOURCES: List[KnowledgeSource] = [
    KnowledgeSource("product-catalogue",
                    "제품 설명 — 구성요소별 역할, 적용 규모, 교체 시 영향",
                    "products", "description"),
    KnowledgeSource("support-knowledge-base",
                    "고객 지원 대화 — 실제 문의와 처리 내용",
                    "ticket_messages", "body"),
    KnowledgeSource("operations-runbook",
                    "운영 문서 — 재임베딩, egress, 감사 보관, 마스킹 점검 절차",
                    "knowledge_articles", "body"),
    KnowledgeSource("campaign-briefs",
                    "캠페인 기획 의도, 대상 세그먼트, 성공 지표",
                    "campaigns", "brief"),
]


# ── activation ────────────────────────────────────────────────────────────────
# Seeding PostgreSQL is half the job. The tables reach the catalog through a connector
# sync; the relationship graph draws a solid edge only from a join in query_history;
# and Knowledge shows a source only once a collection has ingested one.
#
# Each step depends on the one before and each can be half-done, so the plan is data
# rather than a sequence of calls buried in a handler — which is how the order gets
# quietly wrong and the failure shows up as an empty graph nobody can explain.

# Where the connector sync writes. The ingest and the join queries both have to name
# it: a collection pointed at the wrong schema ingests nothing and reports success.
CATALOG_SCHEMA = "default"


@dataclass(frozen=True)
class ActivationStep:
    key: str
    label: str
    detail: str
    requires: Optional[str] = None


def activation_steps() -> List[ActivationStep]:
    return [
        ActivationStep("sync", "Sync into the catalog",
                       "Runs the sample connector so the 13 tables become catalog "
                       "tables. Everything below reads them."),
        ActivationStep("queries", "Run the demo joins",
                       "Puts real joins in query_history, which is the only thing "
                       "that makes a relationship edge solid rather than a guess "
                       "from column names.", requires="sync"),
        ActivationStep("knowledge", "Ingest the prose columns",
                       "Creates the collections and embeds the columns that hold "
                       "prose, so Knowledge has a real source to show.",
                       requires="sync"),
        ActivationStep("refresh", "Arm the re-embed schedule",
                       "Sets each collection to re-embed on an interval. This is the "
                       "one workload on this profile that recurs without being asked: "
                       "the in-process scheduler runs due collections, so it needs no "
                       "Airflow. Quality checks already run after every sync.",
                       requires="knowledge"),
    ]


# How often a seeded collection re-embeds. Long enough that a demo deployment is not
# re-embedding constantly for data that changes only when someone re-seeds it, short
# enough that the schedule visibly fires while someone is looking at it.
REFRESH_INTERVAL_MINUTES = 360


def knowledge_schedule_requests() -> List[Dict[str, Any]]:
    """One schedule per collection, in the shape /ai/collections/{name}/schedule takes.

    Separate from knowledge_ingest_requests() because arming a recurring spend is a
    different decision from loading data once: the ingest can be re-run by hand, and
    this commits the deployment to embedding on every tick from now on.
    """
    return [{"collection": source.collection,
             "interval_minutes": REFRESH_INTERVAL_MINUTES,
             "source": _source_block(source)}
            for source in KNOWLEDGE_SOURCES]


def _qualify(sql: str, tables) -> str:
    """Prefix each table name with the catalog schema, in FROM and JOIN only.

    Only after FROM/JOIN, so an alias, a column, or a word that happens to match a
    table name is left alone — `SELECT p.category ... JOIN products p` must keep both
    halves intact.
    """
    import re
    out = sql
    for name in tables:
        out = re.sub(rf"\b(FROM|JOIN)\s+{re.escape(name)}\b",
                     rf"\1 {CATALOG_SCHEMA}.{name}", out)
    return out


def catalog_join_queries() -> List[JoinQuery]:
    """The demo joins, addressed to the catalog rather than to sampledb.

    They were written against the seed database, where an unqualified name resolves
    correctly. Through the query engine it resolves to whatever the session's default
    schema happens to be, which is not necessarily this one.
    """
    return [JoinQuery(q.name, q.tables, _qualify(q.sql, q.tables), q.question)
            for q in JOIN_QUERIES]


def _source_block(source: KnowledgeSource) -> Dict[str, Any]:
    """Where a collection's rows come from, in the shape both routes take.

    Derived once because ScheduleRequest requires `source` with no default: the
    re-embed scheduler has to know what to re-ingest, and a schedule request built
    without it fails validation rather than arming anything. Writing the block twice
    is how the schedule half came to omit it.
    """
    return {
        "type": "iceberg",
        "schema": CATALOG_SCHEMA,
        "table": source.table,
        "text_column": source.column,
        "limit": 1000,
    }


def knowledge_ingest_requests() -> List[Dict[str, Any]]:
    """One ingest per collection, in the shape /ai/collections/{name}/ingest-source takes."""
    return [{
        "collection": source.collection,
        "description": source.description,
        "source": _source_block(source),
    } for source in KNOWLEDGE_SOURCES]


def connector_action(exists: bool, decryptable: bool) -> str:
    """What to do with the sample connector: create it, repair it, or leave it.

    Repair exists because of a live failure: an incident regenerated ENCRYPTION_KEY,
    the connector's stored config could no longer be decrypted, and every sync failed
    with "Decryption failed". The seed route saw a row with the right name and left it
    alone, so re-running the seed — the obvious thing to try — fixed nothing.

    This is the one credential the product can rebuild by itself; host, port, database,
    user and password all come from the deployment's own configuration. Repair rather
    than recreate: the row keeps its id, and sync history and schedules point at it.
    """
    if not exists:
        return "create"
    return "keep" if decryptable else "repair"
