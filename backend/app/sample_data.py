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
} for i in range(1, 41)]

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
} for i in range(1, 25)]

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
} for i in range(1, 121)]

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
    "session_id": f"s-{_n('sess', i) % 400:04d}",
    "occurred_at": _when("event", i),
} for i in range(1, 301)]


# ── support ───────────────────────────────────────────────────────────────────

AGENTS = [{
    "id": i,
    "name": _pick(_FAMILY, "afam", i) + _pick(_GIVEN, "agiv", i),
    "team": _pick(["tier1", "tier1", "tier2", "escalation"], "team", i),
    "hired_on": (_EPOCH - timedelta(days=_n("hire", i) % 1500)).date(),
} for i in range(1, 7)]

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
} for i in range(1, 46)]

_MESSAGE_BODY = [
    "주문한 상품이 예정일보다 사흘 늦게 도착했습니다. 배송 상태가 계속 '발송됨'으로만 표시되어 "
    "어디까지 진행됐는지 확인이 어렵습니다. 현재 위치를 알려주실 수 있을까요?",
    "결제 시도 시 카드 승인이 반복해서 거절됩니다. 카드사에는 문제가 없다고 확인받았고, "
    "다른 카드로도 동일한 증상이 재현됩니다. 주문 번호를 함께 남깁니다.",
    "설정 화면에서 프로파일 값을 바꾼 뒤 서비스가 기동되지 않습니다. 되돌렸는데도 같은 상태이고, "
    "로그에는 권한 관련 메시지만 반복됩니다. 확인 부탁드립니다.",
    "확인해 주셔서 감사합니다. 안내해 주신 대로 재시도하니 정상 처리되었습니다. "
    "같은 증상이 다시 나오면 이 티켓으로 회신드리겠습니다.",
    "담당 팀에 전달했고, 원인은 캐시 계층의 권한 설정으로 확인되었습니다. "
    "수정 배포는 오늘 중 적용되며, 적용 후 다시 안내드리겠습니다.",
]

TICKET_MESSAGES = [{
    "id": n,
    "ticket_id": ticket["id"],
    "sender": "customer" if k == 0 else _pick(["agent", "customer"], "sender", ticket["id"], k),
    # The support knowledge base embeds this column.
    "body": _pick(_MESSAGE_BODY, "body", ticket["id"], k),
    "sent_at": ticket["opened_at"] + timedelta(hours=k * 3 + 1),
} for n, (ticket, k) in enumerate(
    ((t, k) for t in SUPPORT_TICKETS for k in range(_n("msgs", t["id"]) % 3 + 1)), start=1)]


# ── logistics ─────────────────────────────────────────────────────────────────

WAREHOUSES = [
    {"id": 1, "code": "ICN", "city": "인천", "country": "KR", "capacity_units": 120000},
    {"id": 2, "code": "NRT", "city": "나리타", "country": "JP", "capacity_units": 64000},
    {"id": 3, "code": "SIN", "city": "싱가포르", "country": "SG", "capacity_units": 48000},
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
    "session_id": f"s-{_n('tsess', i) % 400:04d}",
} for i in range(1, 151)]


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


def insert_statement(t: Table) -> Tuple[str, List[Any]]:
    """A single multi-row INSERT with bound parameters.

    Bound, not interpolated: the seed is prose, and Korean support tickets contain
    apostrophes. Columns are named because a positional insert breaks the moment a
    column is added in the middle.
    """
    columns = list(t.columns)
    args: List[Any] = []
    tuples = []
    for row in t.rows:
        placeholders = []
        for column in columns:
            args.append(row[column])
            placeholders.append(f"${len(args)}")
        tuples.append("(" + ", ".join(placeholders) + ")")
    sql = (f"INSERT INTO {t.name} ({', '.join(columns)}) VALUES\n"
           + ",\n".join(tuples) + "\nON CONFLICT DO NOTHING")
    return sql, args


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
                       "Creates the collections and embeds the three columns that "
                       "hold prose, so Knowledge has a real source to show.",
                       requires="sync"),
    ]


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


def knowledge_ingest_requests() -> List[Dict[str, Any]]:
    """One ingest per collection, in the shape /ai/collections/{name}/ingest-source takes."""
    return [{
        "collection": source.collection,
        "description": source.description,
        "source": {
            "type": "iceberg",
            "schema": CATALOG_SCHEMA,
            "table": source.table,
            "text_column": source.column,
            "limit": 1000,
        },
    } for source in KNOWLEDGE_SOURCES]
