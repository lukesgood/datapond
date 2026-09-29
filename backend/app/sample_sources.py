"""Sample sources of every kind the connector registry can reach without leaving the cluster.

What this is for: the Sources page with one PostgreSQL sample shows one connector
type. A person evaluating the product wants to see files in object storage, a REST
feed, a custom Python source and a database reached by URL go through the same sync
into the same catalog — and then join to each other.

Why it is structured this way:

  * Every kind is served from inside the deployment. Files go to the bucket the
    deployment already owns, the REST feed is a route on this backend, the finance
    database sits beside `sampledb`, and the custom source computes its rows. A demo
    that needs egress fails on exactly the installs (Sovereign, air-gapped) that most
    need to see it work.
  * The rows are derived from app/sample_data.py, not invented beside it. A return
    points at an order item that exists, a carrier scan at a shipment that exists, an
    invoice at an order that exists. tests/test_sample_sources.py checks each of those
    references against the seed, because a join across sources that finds nothing is
    the demo lying.
  * Nothing here touches a network or a database. The route in app/api/connectors.py
    does the writing; this module only says what to write.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import csv
import io
import json
from typing import Any, Dict, List, Tuple

from app.sample_data import (
    ForeignKey, ORDER_ITEMS, ORDERS, SHIPMENTS, Table, WAREHOUSES, _EPOCH, _n, _pick,
)


@dataclass(frozen=True)
class SampleSource:
    kind: str                 # stable key the API and UI use
    name: str                 # connector_connections.name — how an existing one is found
    connector_type: str
    description: str
    tables: Tuple[str, ...]


@dataclass(frozen=True)
class CrossSourceReference:
    """A join that spans two sources. Declared so it can be tested; never emitted as a
    constraint, because the two sides live in different databases or files."""
    child: str
    column: str
    parent: str
    parent_column: str = "id"


POSTGRES_SAMPLE_NAME = "Sample E-Commerce DB"

SAMPLE_SOURCES: List[SampleSource] = [
    SampleSource(
        "postgresql", POSTGRES_SAMPLE_NAME, "postgresql",
        "PostgreSQL 데이터베이스 — 커머스·지원·물류·마케팅·텔레메트리 16개 테이블",
        ("customers", "orders", "order_items", "shipments", "warehouses", "…")),
    SampleSource(
        "object_storage", "Sample Object Storage", "s3",
        "S3 호환 버킷의 파일 — CSV(반품), JSON Lines(택배 스캔), Parquet(창고 센서)",
        ("product_returns", "carrier_scans", "warehouse_sensors")),
    SampleSource(
        "rest_api", "Sample FX Rates API", "rest_api",
        "API 키로 보호되는 REST JSON 피드 — 일별 원화 환율",
        ("fx_rates",)),
    SampleSource(
        "custom_python", "Sample Business Calendar", "custom",
        "Custom Python 커넥터 — 2026년 영업일·공휴일 캘린더를 코드로 생성",
        ("business_calendar",)),
    SampleSource(
        "database_url", "Sample Finance DB", "database_url",
        "SQLAlchemy URL로 연결한 데이터베이스 — 주문별 청구서와 결제",
        ("invoices", "payments")),
]


def sample_source(kind: str) -> SampleSource:
    for s in SAMPLE_SOURCES:
        if s.kind == kind:
            return s
    raise KeyError(kind)


def kinds() -> List[str]:
    return [s.kind for s in SAMPLE_SOURCES]


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── object storage: three formats, one folder per table ──────────────────────
# The S3 connector reads each folder directly under its prefix as a table, and picks
# the parser from the file extension. Files are split by month because that is what
# an export actually looks like, and because a table spread over several objects is
# the case the connector's concatenation exists for.

OBJECT_PREFIX = "samples/sources/"
DOCS_PREFIX = "samples/docs/"

_SCAN_HUB = ["곤지암 허브", "대전 허브", "옥천 허브", "칠곡 허브", "인천공항 화물터미널"]
_SCAN_LAST_MILE = ["서울 강남 영업소", "성남 분당 영업소", "부산 해운대 영업소",
                   "대구 수성 영업소", "광주 서구 영업소"]

# Every fourth shipment: enough rows to aggregate, few enough that the upload is a
# couple of megabytes rather than a download someone waits for.
_SCANNED_SHIPMENTS = [s for s in SHIPMENTS if s["id"] % 4 == 0]


def _scans_for(shipment: Dict[str, Any]) -> List[Dict[str, Any]]:
    sid = shipment["id"]
    warehouse = WAREHOUSES[shipment["warehouse_id"] - 1]
    shipped = shipment["shipped_at"]
    steps = [("picked_up", f"{warehouse['city']} 창고({warehouse['code']})", shipped),
             ("hub_arrival", _pick(_SCAN_HUB, "hub", sid),
              shipped + timedelta(hours=_n("hub", sid) % 18 + 6))]
    if shipment["delivered_at"]:
        delivered = shipment["delivered_at"]
        steps.append(("out_for_delivery", _pick(_SCAN_LAST_MILE, "lm", sid),
                      delivered - timedelta(hours=_n("ofd", sid) % 5 + 1)))
        steps.append(("delivered", _pick(_SCAN_LAST_MILE, "lm", sid), delivered))
    return [{
        "scan_id": sid * 10 + k,
        "shipment_id": sid,
        "tracking_no": shipment["tracking_no"],
        "carrier": shipment["carrier"],
        "scan_type": scan_type,
        "location": location,
        "scanned_at": _iso(at),
    } for k, (scan_type, location, at) in enumerate(steps, start=1)]


CARRIER_SCANS: List[Dict[str, Any]] = [
    scan for s in _SCANNED_SHIPMENTS for scan in _scans_for(s)]

_ORDERS_BY_ID = {o["id"]: o for o in ORDERS}
_RETURN_REASON = ["단순 변심", "제품 불량", "오배송", "배송 지연", "사양 불일치"]
_RETURN_STATUS = ["refunded", "refunded", "refunded", "approved", "requested", "rejected"]

PRODUCT_RETURNS: List[Dict[str, Any]] = [{
    "return_id": n,
    "order_id": item["order_id"],
    "order_item_id": item["id"],
    "product_id": item["product_id"],
    "quantity": 1,
    "reason": _pick(_RETURN_REASON, "rreason", item["id"]),
    "refund_amount": item["unit_price"],
    "status": _pick(_RETURN_STATUS, "rstatus", item["id"]),
    "requested_at": _iso(_ORDERS_BY_ID[item["order_id"]]["ordered_at"]
                         + timedelta(days=_n("rdays", item["id"]) % 14 + 3)),
} for n, item in enumerate(
    (i for i in ORDER_ITEMS
     if _ORDERS_BY_ID[i["order_id"]]["status"] == "delivered" and _n("ret", i["id"]) % 25 == 0),
    start=1)]

_SENSOR_START = datetime(2026, 7, 20, tzinfo=timezone.utc)

def _sensor_readings() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for w in WAREHOUSES:
        sensor = f"{w['code']}-ENV-{_n('sensor', w['id']) % 90 + 10}"
        for step in range(30 * 4):                      # 30 days, every six hours
            temperature = 18.0 + (_n("temp", w["id"], step) % 60) / 10
            # One warehouse runs hot for a day: something for a threshold query to find.
            if w["code"] == "SIN" and 60 <= step < 64:
                temperature += 9.5
            humidity = 40 + (_n("hum", w["id"], step) % 250) / 10
            for metric, value in (("temperature_c", temperature), ("humidity_pct", humidity)):
                rows.append({
                    "reading_id": len(rows) + 1,
                    "warehouse_id": w["id"],
                    "sensor": sensor,
                    "metric": metric,
                    "value": round(value, 1),
                    "observed_at": _SENSOR_START + timedelta(hours=6 * step),
                })
    return rows


WAREHOUSE_SENSORS: List[Dict[str, Any]] = _sensor_readings()


def _month(ts: str) -> str:
    return ts[:7]


def _by_month(rows: List[Dict[str, Any]], column: str) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(_month(row[column]), []).append(row)
    return dict(sorted(out.items()))


def _csv_bytes(rows: List[Dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _jsonl_bytes(rows: List[Dict[str, Any]]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")


def _parquet_bytes(rows: List[Dict[str, Any]]) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), buf)
    return buf.getvalue()


# Knowledge reads text and markdown from a prefix; these sit beside the table files
# rather than inside them, because the S3 connector would read a docs folder as a table.
POLICY_DOCS: Dict[str, str] = {
    "return-policy.md": """# 반품·환불 정책

배송 완료 후 14일 이내에 반품을 요청할 수 있습니다. 반품 사유는 단순 변심, 제품 불량,
오배송, 배송 지연, 사양 불일치 중 하나로 기록됩니다.

- 제품 불량과 오배송은 회수 비용을 회사가 부담하며, 검수 후 3영업일 이내에 환불합니다.
- 단순 변심은 미개봉 제품에 한해 승인되며, 왕복 배송비를 차감합니다.
- 환불 금액은 주문 품목의 단가 기준이며, 주문 단위 할인은 비례 배분하여 차감합니다.
- 반품 상태는 requested → approved → refunded 순서로 진행되며, 검수 불합격 시 rejected로 종료됩니다.

환불 처리 기준일은 공휴일과 주말을 제외한 영업일(업무 캘린더 기준)로 계산합니다.
""",
    "shipping-sla.md": """# 배송 서비스 수준(SLA)

출고는 결제 완료 후 72시간 이내를 목표로 합니다. 택배사 스캔은 picked_up(창고 인수),
hub_arrival(허브 도착), out_for_delivery(배송 출발), delivered(배송 완료) 네 단계로 기록됩니다.

- 국내 배송 목표: 출고 후 2영업일 이내 배송 완료
- 해외 창고(나리타, 싱가포르, 홍콩, 프랑크푸르트, 로스앤젤레스, 시드니) 출고 건: 출고 후 6일 이내
- hub_arrival 이후 48시간 동안 다음 스캔이 없으면 지연 건으로 분류하고 고객에게 안내합니다.

창고 온도는 15~26°C를 유지해야 하며, 26°C를 넘는 측정값이 6시간 이상 이어지면
해당 창고의 출고를 보류하고 품질 점검을 진행합니다.
""",
    "payment-terms.md": """# 청구·결제 조건

파트너 채널 주문은 월말 청구서로 일괄 청구하고, 웹·모바일 주문은 주문 시점에 결제합니다.

- 청구서 지급 기한은 발행일로부터 30일입니다.
- 외화 결제는 결제일의 원화 환율(일별 고시 환율)로 환산하여 장부에 기록합니다.
- 기한을 넘긴 청구서는 overdue로 표시하고, 15일이 더 지나면 채권 관리 대상으로 이관합니다.
- 결제 수단은 카드, 계좌이체, 가상계좌 중 하나로 기록합니다.
""",
}


def object_files() -> List[Tuple[str, bytes, str]]:
    """(key, body, content type) for every object the object-storage sample writes."""
    files: List[Tuple[str, bytes, str]] = []
    for month, rows in _by_month(PRODUCT_RETURNS, "requested_at").items():
        files.append((f"{OBJECT_PREFIX}product_returns/{month}.csv",
                      _csv_bytes(rows), "text/csv"))
    for month, rows in _by_month(CARRIER_SCANS, "scanned_at").items():
        files.append((f"{OBJECT_PREFIX}carrier_scans/{month}.jsonl",
                      _jsonl_bytes(rows), "application/x-ndjson"))
    files.append((f"{OBJECT_PREFIX}warehouse_sensors/readings.parquet",
                  _parquet_bytes(WAREHOUSE_SENSORS), "application/vnd.apache.parquet"))
    for name, body in POLICY_DOCS.items():
        files.append((f"{DOCS_PREFIX}{name}", body.encode("utf-8"), "text/markdown"))
    return files


# ── REST: a daily FX feed ─────────────────────────────────────────────────────
# Served by this backend (app/api/sample_api.py) so the REST connector has something
# to call on an install with no egress. A random walk rather than independent draws:
# rates that jump 5% a day look fabricated, which they are, but they need not look it.

FX_BASE = "KRW"
_FX_START = {"USD": 1382.0, "JPY": 9.21, "EUR": 1498.0, "CNY": 190.4, "SGD": 1031.0}
FX_DAYS = 120


def fx_rates() -> List[Dict[str, Any]]:
    rows = []
    level = dict(_FX_START)
    start = _EPOCH.date()
    for d in range(FX_DAYS):
        day = start + timedelta(days=d)
        for currency in _FX_START:
            if d:
                drift = ((_n("fx", currency, d) % 81) - 40) / 10000   # ±0.4% a day
                level[currency] = level[currency] * (1 + drift)
            rows.append({"rate_date": day.isoformat(), "currency": currency,
                         "krw_per_unit": round(level[currency], 4 if currency == "JPY" else 2)})
    return rows


def fx_payload() -> Dict[str, Any]:
    """The response body, nested so the connector's data_path has something to do."""
    return {"base": FX_BASE, "source": "DataPond sample FX feed",
            "data": {"rates": fx_rates()}}


FX_DATA_PATH = "data.rates"


# ── custom Python: a business calendar computed in the sandbox ────────────────
# The custom connector runs code with no imports and a small builtin whitelist
# (app/connectors/custom.py), so the calendar is arithmetic, not `datetime`. Holidays
# are the 2026 Korean public holidays including substitute days; a sample, not an
# authority to schedule payroll by.

CUSTOM_CALENDAR_CODE = '''\
# 2026년 영업일 캘린더. import 없이 동작합니다 — Custom 커넥터 샌드박스에서는
# 허용된 내장 함수만 쓸 수 있습니다.
HOLIDAYS = {
    "2026-01-01": "신정",
    "2026-02-16": "설날 연휴", "2026-02-17": "설날", "2026-02-18": "설날 연휴",
    "2026-03-01": "삼일절", "2026-03-02": "대체공휴일(삼일절)",
    "2026-05-05": "어린이날",
    "2026-05-24": "부처님오신날", "2026-05-25": "대체공휴일(부처님오신날)",
    "2026-06-03": "전국동시지방선거",
    "2026-06-06": "현충일",
    "2026-08-15": "광복절", "2026-08-17": "대체공휴일(광복절)",
    "2026-09-24": "추석 연휴", "2026-09-25": "추석", "2026-09-26": "추석 연휴",
    "2026-10-03": "개천절", "2026-10-05": "대체공휴일(개천절)",
    "2026-10-09": "한글날",
    "2026-12-25": "성탄절",
}
MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def fetch_data():
    rows = []
    weekday = 3  # 2026-01-01 is a Thursday
    business_day_of_year = 0
    for month in range(1, 13):
        for day in range(1, MONTH_DAYS[month - 1] + 1):
            iso = "2026-%02d-%02d" % (month, day)
            is_weekend = weekday >= 5
            holiday = HOLIDAYS.get(iso)
            is_business_day = not is_weekend and holiday is None
            if is_business_day:
                business_day_of_year += 1
            rows.append({
                "cal_date": iso,
                "year": 2026,
                "quarter": (month - 1) // 3 + 1,
                "month": month,
                "day": day,
                "weekday": WEEKDAYS[weekday],
                "is_weekend": is_weekend,
                "is_holiday": holiday is not None,
                "holiday_name": holiday,
                "is_business_day": is_business_day,
                "business_day_of_year": business_day_of_year if is_business_day else None,
            })
            weekday = (weekday + 1) % 7
    return rows
'''


# ── database URL: a finance database beside sampledb ──────────────────────────
# A second PostgreSQL database reached through the SQLAlchemy URL connector rather
# than the native one, so the same engine shows up as a different connector kind.
# invoices.order_id points into sampledb: declared below as a cross-source reference
# and tested, never as a constraint, because Postgres cannot reference across databases.

FINANCE_DATABASE = "samplefinance"

_INVOICED = [o for o in ORDERS if o["status"] != "cancelled" and o["id"] % 3 == 0]
_PAY_METHOD = ["card", "card", "bank_transfer", "virtual_account"]


def _invoice_status(order: Dict[str, Any]) -> str:
    bucket = _n("inv", order["id"]) % 10
    return "paid" if bucket < 7 else ("overdue" if bucket < 9 else "issued")


INVOICES: List[Dict[str, Any]] = [{
    "id": n,
    "order_id": order["id"],
    "invoice_no": f"INV-2026-{n:05d}",
    "amount": round(order["total_amount"] - order["discount"], 2),
    "currency": "KRW",
    "status": _invoice_status(order),
    "issued_on": order["ordered_at"].date(),
    "due_on": order["ordered_at"].date() + timedelta(days=30),
} for n, order in enumerate(_INVOICED, start=1)]

PAYMENTS: List[Dict[str, Any]] = [{
    "id": n,
    "invoice_id": invoice["id"],
    "method": _pick(_PAY_METHOD, "pay", invoice["id"]),
    "amount": invoice["amount"],
    "paid_at": datetime.combine(invoice["issued_on"], datetime.min.time(), tzinfo=timezone.utc)
               + timedelta(days=_n("paid", invoice["id"]) % 28, hours=9),
} for n, invoice in enumerate((i for i in INVOICES if i["status"] == "paid"), start=1)]

FINANCE_DATASET: List[Table] = [
    Table("invoices", "finance", {
        "id": "SERIAL PRIMARY KEY", "order_id": "INTEGER NOT NULL",
        "invoice_no": "VARCHAR(20) UNIQUE NOT NULL", "amount": "NUMERIC(12,2) NOT NULL",
        "currency": "VARCHAR(3) NOT NULL DEFAULT 'KRW'",
        "status": "VARCHAR(20) NOT NULL DEFAULT 'issued'",
        "issued_on": "DATE NOT NULL", "due_on": "DATE NOT NULL",
    }, INVOICES),
    Table("payments", "finance", {
        "id": "SERIAL PRIMARY KEY", "invoice_id": "INTEGER NOT NULL",
        "method": "VARCHAR(20) NOT NULL", "amount": "NUMERIC(12,2) NOT NULL",
        "paid_at": "TIMESTAMPTZ NOT NULL",
    }, PAYMENTS, [ForeignKey("payments", "invoice_id", "invoices")]),
]


def finance_sequence_reset_statements() -> List[str]:
    return [
        f"SELECT setval(pg_get_serial_sequence('{t.name}', '{t.primary_key}'), "
        f"(SELECT COALESCE(MAX({t.primary_key}), 1) FROM {t.name}));"
        for t in FINANCE_DATASET
    ]


# ── how the sources reach back into the e-commerce sample ─────────────────────

CROSS_SOURCE_REFERENCES: List[CrossSourceReference] = [
    CrossSourceReference("product_returns", "order_id", "orders"),
    CrossSourceReference("product_returns", "order_item_id", "order_items"),
    CrossSourceReference("product_returns", "product_id", "products"),
    CrossSourceReference("carrier_scans", "shipment_id", "shipments"),
    CrossSourceReference("warehouse_sensors", "warehouse_id", "warehouses"),
    CrossSourceReference("invoices", "order_id", "orders"),
]

SOURCE_ROWS: Dict[str, List[Dict[str, Any]]] = {
    "product_returns": PRODUCT_RETURNS,
    "carrier_scans": CARRIER_SCANS,
    "warehouse_sensors": WAREHOUSE_SENSORS,
    "invoices": INVOICES,
    "payments": PAYMENTS,
}


def rest_config(base_url: str, api_key: str) -> Dict[str, Any]:
    return {
        "base_url": base_url,
        "auth_type": "api_key",
        "auth_header": "X-Sample-Key",
        "auth_value": api_key,
        "data_path": FX_DATA_PATH,
        "table_name": "fx_rates",
        "timeout": 30,
    }


def custom_config() -> Dict[str, Any]:
    return {"code": CUSTOM_CALENDAR_CODE, "table_name": "business_calendar"}


def s3_config(bucket: str, region: str, endpoint_url: str = "",
              access_key: str = "", secret_key: str = "") -> Dict[str, Any]:
    config: Dict[str, Any] = {"bucket": bucket, "region": region, "prefix": OBJECT_PREFIX}
    # Native S3 takes the pod's role; only an S3-compatible endpoint gets keys, and only
    # the ones the deployment already runs with.
    if endpoint_url:
        config["endpoint_url"] = endpoint_url
        if access_key and secret_key:
            config["access_key"] = access_key
            config["secret_key"] = secret_key
    return config


def database_url(host: str, port: int, user: str, password: str) -> str:
    from urllib.parse import quote
    return (f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
            f"@{host}:{port}/{FINANCE_DATABASE}")


def join_examples() -> List[Dict[str, str]]:
    """Questions the combined samples answer, for the response and the docs. Each one
    spans at least two sources — that is the point of adding them."""
    return [
        {"question": "반품 사유별 환불 금액과 해당 제품 카테고리",
         "tables": "product_returns (S3 CSV) × products (PostgreSQL)"},
        {"question": "택배사별 허브 도착에서 배송 완료까지 걸린 시간",
         "tables": "carrier_scans (S3 JSONL) × shipments (PostgreSQL)"},
        {"question": "26°C를 넘은 창고와 그 기간에 출고된 주문",
         "tables": "warehouse_sensors (S3 Parquet) × shipments × warehouses"},
        {"question": "달러 환산 월별 매출",
         "tables": "orders (PostgreSQL) × fx_rates (REST)"},
        {"question": "영업일 기준 청구서 연체 일수",
         "tables": "invoices (Database URL) × business_calendar (Custom Python)"},
    ]
