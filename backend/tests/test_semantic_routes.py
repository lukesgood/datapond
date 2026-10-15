import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth
from app.api import semantic as api
from app.semantic.model import Dimension, MetricVersion

ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
ANALYST = {"id": "00000000-0000-0000-0000-000000000003", "username": "ana",
           "role": "business_analyst"}
KEY = dict(ADMIN, auth_method="service", permissions=["catalog:read", "governance:write"])
COLS = {"sales.orders": ["amount", "status", "channel", "ordered_at", "customer_id"],
        "sales.customers": ["id", "region"]}


class FakeStore:
    def __init__(self):
        self.metrics, self.versions, self.joins = {}, {}, []

    async def get_metric(self, pool, name):
        return self.metrics.get(name)

    async def list_metrics(self, pool):
        out = []
        for m in self.metrics.values():
            vs = self.versions.get(m["id"], {})
            cur = vs.get(m["current_version"]) or (vs[max(vs)] if vs else None)
            out.append(dict(m, catalog=cur.catalog if cur else None))
        return out

    async def get_version(self, pool, mid, name, version):
        return self.versions.get(mid, {}).get(version)

    async def list_versions(self, pool, mid):
        return [{"version": v.version, "approved_at": v.approved_at, "change_note": ""}
                for v in sorted(self.versions.get(mid, {}).values(), key=lambda v: -v.version)]

    async def create_metric(self, pool, *, name, label, description, synonyms, owner_id, owner_name):
        mid = len(self.metrics) + 1
        self.metrics[name] = {"id": mid, "name": name, "label": label, "description": description,
                              "synonyms": synonyms, "owner_name": owner_name, "status": "draft",
                              "current_version": None, "updated_at": None}
        return mid

    async def insert_version(self, pool, *, metric_id, fields, created_by, created_by_name, change_note):
        from app.semantic.store import row_to_version
        n = 1 + max(self.versions.get(metric_id, {}) or [0])
        name = next(m["name"] for m in self.metrics.values() if m["id"] == metric_id)
        row = dict(fields, version=n, filters=fields.get("filters"),
                   time_column=fields.get("time_column"), grains=fields.get("grains") or [],
                   max_period_days=fields.get("max_period_days") or 366,
                   approved_by_name=None, approved_at=None, created_by=created_by)
        self.versions.setdefault(metric_id, {})[n] = row_to_version(name, row)
        return n

    async def approve_version(self, pool, *, metric_id, version, approver_id, approver_name):
        import dataclasses
        v = self.versions[metric_id][version]
        self.versions[metric_id][version] = dataclasses.replace(
            v, approved_by=approver_name, approved_at="2026-10-15T00:00:00+00:00")
        m = next(m for m in self.metrics.values() if m["id"] == metric_id)
        m.update(status="approved", current_version=version)

    async def retire_metric(self, pool, mid):
        next(m for m in self.metrics.values() if m["id"] == mid)["status"] = "retired"

    async def list_joins(self, pool, catalog=None):
        return list(self.joins)

    async def get_join(self, pool, jid):
        return next((j for j in self.joins if j["id"] == jid), None)

    async def insert_join(self, pool, **kw):
        self.joins.append(dict(kw, id=len(self.joins) + 1,
                               on_columns=kw["on_columns"], approved_by_name=kw["approver_name"]))
        return len(self.joins)


@pytest.fixture
def client(monkeypatch):
    fs = FakeStore()
    for name in ("get_metric", "list_metrics", "get_version", "list_versions", "create_metric",
                 "insert_version", "approve_version", "retire_metric", "list_joins", "get_join",
                 "insert_join"):
        monkeypatch.setattr(api.store, name, getattr(fs, name))
    state = {"user": ADMIN, "unique": True, "audited": []}

    async def pool():
        return None
    monkeypatch.setattr(api, "_pool", pool)
    monkeypatch.setattr(api.service, "_pool", pool)
    monkeypatch.setattr(api, "_columns", lambda entry, table: COLS.get(table))

    async def target_unique(user, entry, to_table, columns):
        return (True, 0) if state["unique"] else (False, 3)
    monkeypatch.setattr(api, "_target_unique", target_unique)

    async def recent(name):
        return 0
    monkeypatch.setattr(api, "_recent_queries", recent)

    async def record(**kw):
        state["audited"].append(kw)
    monkeypatch.setattr(api.security_audit, "record", record)

    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    app.dependency_overrides[auth.require_user] = lambda: state["user"]
    c = TestClient(app)
    c.state, c.fs = state, fs
    return c


BODY = {"name": "revenue", "label": "매출", "synonyms": ["sales"],
        "version": {"catalog": "glue", "base_table": "sales.orders", "measure": "SUM(amount)",
                    "filters": "status = 'paid'", "time_column": "ordered_at", "grains": ["month"],
                    "dimensions": [{"name": "channel", "column": "channel"}],
                    "change_note": "first"}}


@pytest.fixture(autouse=True)
def _glue_catalog(monkeypatch):
    from app import catalog_registry as reg
    entry = reg.CatalogEntry(name="glue", kind="glue", engine_catalog="AwsDataCatalog",
                             config={}, is_default=True, enabled=True)
    reg.set_entries([entry])
    yield
    reg.reset()


def test_create_then_approve_then_listed(client):
    assert client.post("/api/semantic/metrics", json=BODY).status_code == 201
    assert client.post("/api/semantic/metrics/revenue/versions/1/approve").status_code == 200
    body = client.get("/api/semantic/metrics").json()
    assert [m["name"] for m in body["metrics"]] == ["revenue"]
    assert body["viewer"] == {"can_author": True, "can_approve": True}


def test_invalid_measure_is_422_with_field(client):
    bad = {**BODY, "version": {**BODY["version"], "measure": "SUM((SELECT 1))"}}
    r = client.post("/api/semantic/metrics", json=bad)
    assert r.status_code == 422 and r.json()["detail"]["field"] == "measure"


def test_unknown_column_is_422(client):
    bad = {**BODY, "version": {**BODY["version"], "time_column": "nope"}}
    assert client.post("/api/semantic/metrics", json=bad).status_code == 422


def test_dimension_join_must_be_an_approved_join(client):
    dims = [{"name": "region", "column": "region", "join_id": 99}]
    bad = {**BODY, "version": {**BODY["version"], "dimensions": dims}}
    r = client.post("/api/semantic/metrics", json=bad)
    assert r.status_code == 422 and r.json()["detail"]["field"] == "dimensions"


def test_join_is_copied_by_value_into_the_version(client):
    client.post("/api/semantic/joins", json={"catalog": "glue", "from_table": "sales.orders",
                                             "to_table": "sales.customers",
                                             "on_columns": [["customer_id", "id"]], "source": "manual"})
    dims = [{"name": "region", "column": "region", "join_id": 1}]
    client.post("/api/semantic/metrics", json={**BODY, "version": {**BODY["version"], "dimensions": dims}})
    v = client.fs.versions[1][1]
    assert v.dimensions[0].join.to_table == "sales.customers"
    assert v.dimensions[0].join.on == (("customer_id", "id"),)


def test_non_unique_join_target_is_422(client):
    client.state["unique"] = False
    r = client.post("/api/semantic/joins", json={"catalog": "glue", "from_table": "sales.orders",
                                                 "to_table": "sales.customers",
                                                 "on_columns": [["customer_id", "id"]], "source": "history"})
    assert r.status_code == 422 and r.json()["detail"]["duplicates"] == 3


def test_a_role_without_governance_write_cannot_author(client):
    client.state["user"] = ANALYST
    assert client.post("/api/semantic/metrics", json=BODY).status_code == 403
    assert client.get("/api/semantic/metrics").json()["viewer"] == {"can_author": False,
                                                                     "can_approve": False}


def test_a_key_cannot_author_even_with_governance_write(client):
    client.state["user"] = KEY
    assert client.post("/api/semantic/metrics", json=BODY).status_code == 403


def test_query_route_runs_the_approved_version_and_audits_metric_query(client, monkeypatch):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    rows, audit = [], []

    async def execute(sql, user):
        rows.append(sql)
        return {"columns": ["revenue"], "rows": [[1]], "row_count": 1, "truncated": False,
                "pii_masked": 0}

    async def record(**kw):
        audit.append(kw)
    from datetime import date
    monkeypatch.setattr(api.service, "_execute", execute)
    monkeypatch.setattr(api.service.tool_call_log, "record", record)
    monkeypatch.setattr(api.service, "today_local", lambda: date(2026, 10, 15))
    monkeypatch.setattr(api.service, "_dialect", lambda: "athena")
    r = client.post("/api/semantic/metrics/revenue/query", json={"period": "last_month"})
    assert r.status_code == 200 and r.json()["citation"]["version"] == 1
    assert audit[0]["tool"] == "metric.query" and len(rows) == 1
    r = client.post("/api/semantic/metrics/revenue/query",
                    json={"period": "last_month", "order_by": [{"field": "revenue", "desc": True}],
                          "limit": 3})
    assert r.status_code == 200 and rows[-1].endswith("ORDER BY 1 DESC LIMIT 3")


def test_a_key_cannot_approve_even_on_an_admin_account(client):
    client.post("/api/semantic/metrics", json=BODY)
    client.state["user"] = KEY
    assert client.post("/api/semantic/metrics/revenue/versions/1/approve").status_code in (401, 403)


def test_approving_twice_is_409(client):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    assert client.post("/api/semantic/metrics/revenue/versions/1/approve").status_code == 409


def test_definition_changes_are_audited(client):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    reasons = [a["reason"] for a in client.state["audited"]]
    assert any("revenue v1 created" in r for r in reasons)
    assert any("revenue v1 approved" in r for r in reasons)


def test_describe_reports_broken_when_column_missing(client, monkeypatch):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    monkeypatch.setattr(api, "_columns", lambda entry, table: ["status", "ordered_at"])
    body = client.get("/api/semantic/metrics/revenue").json()
    assert body["broken"] is True and "amount" in body["broken_reason"]


def test_hidden_catalog_metric_is_404_on_describe(client, monkeypatch):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    from app import catalog_access

    class Hidden:
        def allows(self, e):
            return False

        def resolve(self, name=None):
            raise AssertionError("not reached")

    async def for_caller(user):
        return Hidden()
    monkeypatch.setattr(catalog_access, "for_caller", for_caller)
    assert client.get("/api/semantic/metrics/revenue").status_code == 404
    assert client.get("/api/semantic/metrics").json()["metrics"] == []


def test_two_dimensions_with_different_joins_to_one_table_are_422(client):
    for to_cols in ([["customer_id", "id"]], [["channel", "id"]]):
        client.post("/api/semantic/joins", json={"catalog": "glue", "from_table": "sales.orders",
                                                 "to_table": "sales.customers",
                                                 "on_columns": to_cols, "source": "manual"})
    dims = [{"name": "region", "column": "region", "join_id": 1},
            {"name": "region2", "column": "region", "join_id": 2}]
    r = client.post("/api/semantic/metrics", json={**BODY, "version": {**BODY["version"], "dimensions": dims}})
    assert r.status_code == 422 and r.json()["detail"]["field"] == "dimensions"


def test_two_dimensions_sharing_one_join_are_allowed(client):
    client.post("/api/semantic/joins", json={"catalog": "glue", "from_table": "sales.orders",
                                             "to_table": "sales.customers",
                                             "on_columns": [["customer_id", "id"]], "source": "manual"})
    dims = [{"name": "region", "column": "region", "join_id": 1},
            {"name": "cust", "column": "id", "join_id": 1}]
    r = client.post("/api/semantic/metrics", json={**BODY, "version": {**BODY["version"], "dimensions": dims}})
    assert r.status_code == 201


def test_dimension_named_like_the_metric_is_422(client):
    dims = [{"name": "revenue", "column": "channel"}]
    r = client.post("/api/semantic/metrics", json={**BODY, "version": {**BODY["version"], "dimensions": dims}})
    assert r.status_code == 422 and r.json()["detail"]["field"] == "dimensions"


V2 = dict(BODY["version"], measure="SUM(amount * 2)", change_note="double")


def test_approving_an_older_draft_is_409_and_keeps_the_current_version(client):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions", json=V2)
    client.post("/api/semantic/metrics/revenue/versions", json=V2)
    assert client.post("/api/semantic/metrics/revenue/versions/3/approve").status_code == 200
    r = client.post("/api/semantic/metrics/revenue/versions/2/approve")
    assert r.status_code == 409
    assert client.fs.metrics["revenue"]["current_version"] == 3


def test_a_lost_approval_race_is_409(client, monkeypatch):
    client.post("/api/semantic/metrics", json=BODY)

    async def lost(pool, **kw):
        raise api.store.NotApprovable("raced")
    monkeypatch.setattr(api.store, "approve_version", lost)
    assert client.post("/api/semantic/metrics/revenue/versions/1/approve").status_code == 409


def test_describe_shows_the_pending_version_beside_the_approved_one(client, monkeypatch):
    monkeypatch.setattr(api.service, "today_local", lambda: __import__("datetime").date(2026, 10, 15))
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    client.post("/api/semantic/metrics/revenue/versions", json=V2)
    body = client.get("/api/semantic/metrics/revenue").json()
    assert body["metric"]["version"] == 1 and body["metric"]["measure"] == "SUM(amount)"
    p = body["pending"]
    assert p["version"] == 2 and p["measure"] == "SUM(amount * 2)"
    assert p["base_table"] == "sales.orders" and p["filters"] == "status = 'paid'"
    assert '"amount" * 2' in p["example_sql"]
    assert '"amount" * 2' not in body["example_sql"]


def test_no_pending_when_the_newest_version_is_approved(client):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    assert client.get("/api/semantic/metrics/revenue").json()["pending"] is None


def test_drafts_and_pending_are_hidden_from_viewers_who_cannot_author(client):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    client.post("/api/semantic/metrics/revenue/versions", json=V2)
    client.state["user"] = ANALYST
    body = client.get("/api/semantic/metrics/revenue").json()
    assert [v["version"] for v in body["versions"]] == [1]
    assert body["pending"] is None


def test_join_uniqueness_is_checked_on_the_catalogs_column_spelling(client, monkeypatch):
    seen = []

    async def target_unique(user, entry, to_table, columns):
        seen.append(columns)
        return True, 0
    monkeypatch.setattr(api, "_target_unique", target_unique)
    r = client.post("/api/semantic/joins", json={
        "catalog": "glue", "from_table": "sales.orders", "to_table": "sales.customers",
        "on_columns": [["CUSTOMER_ID", "ID"]], "source": "manual"})
    assert r.status_code == 201 and seen == [["id"]]


def test_uniqueness_probe_runs_as_internal_not_as_a_metric(monkeypatch):
    import asyncio
    calls = []

    async def execute(sql, user, origin="metric"):
        calls.append((sql, origin))
        return {"columns": ["c"], "rows": [[0]], "row_count": 1, "truncated": False,
                "pii_masked": 0}

    class _Eng:
        rls_dialect = "athena"

    class _Entry:
        engine_catalog = "AwsDataCatalog"
    monkeypatch.setattr(api.service, "_execute", execute)
    monkeypatch.setattr("app.api.query_engine.get_engine", lambda: _Eng())
    assert asyncio.run(api._target_unique(ADMIN, _Entry(), "sales.customers", ["id"])) == (True, 0)
    (sql, origin), = calls
    assert origin == "internal" and '"AwsDataCatalog"."sales"."customers"' in sql
