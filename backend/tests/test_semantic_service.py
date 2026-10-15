"""metric.query: visibility, compile, governed execution, one audit row."""
import asyncio
from datetime import date

import pytest
from fastapi import HTTPException

from app.semantic import service
from app.semantic.model import Dimension, MetricVersion

ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
ANA = {"id": "00000000-0000-0000-0000-000000000002", "username": "ana", "role": "business_analyst"}
KEY_ON_ADMIN = dict(ADMIN, auth_method="service", permissions=["query:run", "catalog:read"])

V3 = MetricVersion(metric="revenue", version=3, catalog="glue", base_table="sales.orders",
                   measure="SUM(amount)", time_column="ordered_at", grains=("month",),
                   dimensions=(Dimension("channel", "channel"),), approved_by="root",
                   approved_at="2026-10-15T00:00:00+00:00", created_by=ADMIN["id"])
V4_DRAFT = MetricVersion(metric="revenue", version=4, catalog="glue", base_table="sales.orders",
                         measure="SUM(amount)", time_column="ordered_at",
                         created_by=ADMIN["id"])
META = {"id": 7, "name": "revenue", "label": "매출", "description": "", "synonyms": ["sales"],
        "owner_name": "root", "status": "approved", "current_version": 3}


class _Entry:
    name = "glue"
    engine_catalog = "AwsDataCatalog"


class _Access:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def allows(self, e):
        return self.allowed

    def resolve(self, name=None):
        return _Entry()


@pytest.fixture
def env(monkeypatch):
    state = {"audit": [], "executed": [], "allowed": True, "meta": dict(META), "rls": []}

    async def get_metric(pool, name):
        return state["meta"] if name == "revenue" else None

    async def get_version(pool, metric_id, metric_name, version):
        return {3: V3, 4: V4_DRAFT}.get(version)

    async def for_caller(user):
        return _Access(state["allowed"])

    async def record(**kw):
        service.tool_call_log.build_row(**kw)    # a value the log rejects fails the test
        state["audit"].append(kw)

    async def execute(sql, user):
        from app.api import queries
        queries._note_rls(state["rls"], [])
        state["executed"].append(sql)
        return {"columns": ["revenue"], "rows": [[10]], "row_count": 1, "truncated": False,
                "pii_masked": 0}

    async def pool():
        return None

    monkeypatch.setattr(service.store, "get_metric", get_metric)
    monkeypatch.setattr(service.store, "get_version", get_version)
    monkeypatch.setattr(service.catalog_access, "for_caller", for_caller)
    monkeypatch.setattr(service.tool_call_log, "record", record)
    monkeypatch.setattr(service, "_execute", execute)
    monkeypatch.setattr(service, "_pool", pool)
    monkeypatch.setattr(service, "today_local", lambda: date(2026, 10, 15))
    monkeypatch.setattr(service, "_dialect", lambda: "athena")
    return state


def _run(coro):
    return asyncio.run(coro)


def test_query_returns_rows_and_a_citation(env):
    out = _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    assert out["rows"] == [[10]]
    c = out["citation"]
    assert (c["metric"], c["version"], c["approved_by"]) == ("revenue", 3, "root")
    assert c["rls_applied"] is False and c["sql"] == env["executed"][0]


def test_one_audit_row_with_the_citation(env):
    _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    (row,) = env["audit"]
    assert row["tool"] == "metric.query" and row["resource_kind"] == "metric"
    assert row["resource"] == ["revenue"]
    assert row["citation_sources"] == ["metric:revenue@v3"]
    assert row["outcome"] == "ok" and row["response_text"] == env["executed"][0]


def test_rls_applied_is_reported(env):
    env["rls"] = ["p1"]
    out = _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    assert out["citation"]["rls_applied"] is True


def test_hidden_catalog_is_the_same_404_as_missing(env):
    env["allowed"] = False
    with pytest.raises(HTTPException) as hidden:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    env["allowed"] = True
    with pytest.raises(HTTPException) as missing:
        _run(service.run_metric_query(ANA, metric="nope", period="last_month"))
    assert hidden.value.status_code == missing.value.status_code == 404
    assert hidden.value.detail.replace("revenue", "X") == missing.value.detail.replace("nope", "X")
    assert [r["outcome"] for r in env["audit"]] == ["refused", "refused"]
    assert env["executed"] == []


def test_retired_or_unapproved_metric_is_404(env):
    env["meta"] = dict(META, status="retired")
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    assert e.value.status_code == 404
    env["meta"] = dict(META, status="draft", current_version=None)
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    assert e.value.status_code == 404


def test_bad_input_is_400_with_allowed_values_and_audited(env):
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", by=["country"], period="last_month"))
    assert e.value.status_code == 400 and "channel" in e.value.detail
    assert env["audit"][0]["outcome"] == "refused" and env["executed"] == []


def test_author_or_signed_in_admin_can_preview_a_draft(env):
    out = _run(service.run_metric_query(ADMIN, metric="revenue", period="last_month", version=4))
    assert out["citation"]["version"] == 4 and out["citation"]["approved_by"] is None


def test_others_cannot_preview_a_draft(env):
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month", version=4))
    assert e.value.status_code == 404


def test_delegated_admin_key_cannot_preview_draft(env):
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(KEY_ON_ADMIN, metric="revenue", period="last_month", version=4))
    assert e.value.status_code == 404


def test_an_engine_failure_is_audited_as_error_and_reraised(env, monkeypatch):
    async def boom(sql, user):
        raise HTTPException(status_code=400, detail="Table not found: sales.orders")
    monkeypatch.setattr(service, "_execute", boom)
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    assert "re-validat" in e.value.detail
    assert env["audit"][0]["outcome"] == "error"


def test_an_execution_refusal_is_audited_as_refused(env, monkeypatch):
    async def denied(sql, user):
        raise HTTPException(status_code=403, detail="RLS 차단: x")
    monkeypatch.setattr(service, "_execute", denied)
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    assert e.value.status_code == 403
    assert env["audit"][0]["outcome"] == "refused"


def test_unexpected_resolve_failure_is_audited_as_error(env, monkeypatch):
    async def boom(pool, name):
        raise RuntimeError("pool down")
    monkeypatch.setattr(service.store, "get_metric", boom)
    with pytest.raises(RuntimeError):
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    (row,) = env["audit"]
    assert row["outcome"] == "error"


def test_overflowing_period_is_a_400_refusal(env):
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="9999-12-31..9999-12-31"))
    assert e.value.status_code == 400
    (row,) = env["audit"]
    assert row["outcome"] == "refused"


def test_superseded_approved_version_needs_author_or_admin(env, monkeypatch):
    v2 = MetricVersion(metric="revenue", version=2, catalog="glue", base_table="sales.orders",
                       measure="SUM(amount)", time_column="ordered_at", approved_by="root",
                       approved_at="2026-09-01T00:00:00+00:00", created_by=ADMIN["id"])

    async def get_version(pool, metric_id, metric_name, version):
        return {2: v2, 3: V3}.get(version)
    monkeypatch.setattr(service.store, "get_version", get_version)
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month", version=2))
    assert e.value.status_code == 404
    assert [r["outcome"] for r in env["audit"]] == ["refused"]
    out = _run(service.run_metric_query(ADMIN, metric="revenue", period="last_month", version=2))
    assert out["citation"]["version"] == 2
    # asking for the current version by number is the ordinary approved path
    out = _run(service.run_metric_query(ANA, metric="revenue", period="last_month", version=3))
    assert out["citation"]["version"] == 3


def test_a_stored_definition_off_the_allow_list_is_audited_as_error(env, monkeypatch):
    import dataclasses
    bad = dataclasses.replace(V3, measure="SUM((SELECT 1))")

    async def get_version(pool, metric_id, metric_name, version):
        return bad
    monkeypatch.setattr(service.store, "get_version", get_version)
    with pytest.raises(ValueError):
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    (row,) = env["audit"]
    assert row["outcome"] == "error" and env["executed"] == []


def test_top_n_runs_and_the_audit_row_records_order_and_limit(env):
    _run(service.run_metric_query(ANA, metric="revenue", by=["channel"], period="last_month",
                                  order_by=[{"field": "revenue", "desc": True}], limit=5))
    assert env["executed"][0].endswith("ORDER BY 2 DESC, 1 LIMIT 5")
    (row,) = env["audit"]
    assert '"limit": 5' in row["request_text"] and '"desc": true' in row["request_text"]


def test_bad_limit_is_a_400_refusal_naming_the_range(env):
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month", limit=0))
    assert e.value.status_code == 400 and "1000" in e.value.detail
    assert env["audit"][0]["outcome"] == "refused" and env["executed"] == []
