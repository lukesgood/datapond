"""Audit and PII reach the model as counts, never as records.

The forbidden strings are asserted by name. A future field added to the aggregate that
happens to carry one fails here rather than in someone's conversation.
"""
import asyncio
from datetime import date

from app.chat.analysis import audit as audit_mod
from app.chat.analysis import governance as gov_mod

FORBIDDEN = ("alice@example.com", "10.1.2.3", "b7c1f2e0-0000-0000-0000-000000000001",
             "/api/connectors/42/quality", "denied because the token had expired")


def _run(c):
    return asyncio.run(c)


class _Conn:
    def __init__(self, rows, tool_rows=None):
        self._rows = rows
        self._tool_rows = tool_rows if tool_rows is not None else []
        self.queries = []

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        if "tool_call_log" in sql:
            return self._tool_rows
        return self._rows


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False

        return _Ctx()


def _install_pool(monkeypatch, rows, tool_rows=None):
    conn = _Conn(rows, tool_rows)

    async def _pool():
        return _Pool(conn)

    monkeypatch.setattr("app.api.auth._get_pool", _pool)
    return conn


def test_the_summary_is_counts_and_nothing_else(monkeypatch):
    _install_pool(monkeypatch, [
        {"permission": "query:run", "outcome": "denied", "day": "2026-09-01", "n": 4},
        {"permission": "query:run", "outcome": "allowed", "day": "2026-09-01", "n": 91},
    ])
    out = _run(audit_mod.activity_summary({"days": 7}, {"id": "u1"}))
    assert out["totals"] == {"allowed": 91, "denied": 4}
    assert out["by_permission"][0]["permission"] == "query:run"


def test_the_query_never_selects_an_identifying_column(monkeypatch):
    """Read the SQL, not just the output. A column selected and then dropped in Python
    is one line away from being returned. Covers both queries the action runs —
    _SUMMARY_SQL (security_audit_log) and _TOOL_SUMMARY_SQL (tool_call_log)."""
    conn = _install_pool(monkeypatch, [])
    _run(audit_mod.activity_summary({"days": 7}, {"id": "u1"}))
    assert len(conn.queries) == 2
    for sql in conn.queries:
        lowered = sql.lower()
        for column in ("actor_id", "actor_username", "client_address", "reason",
                       "route", "request_text", "resource"):
            assert column not in lowered, f"{column} must not appear in the aggregate query"


def test_tool_summary_sql_selects_only_categories_and_counts():
    """_TOOL_SUMMARY_SQL, read statically rather than through a mocked pool: only
    tool, outcome, day and count(*) AS n may be selected. Same constraint as
    _SUMMARY_SQL above, enforced directly on the constant's text."""
    sql = audit_mod._TOOL_SUMMARY_SQL
    lowered = sql.lower()
    select_clause = lowered.split("from")[0]
    for column in ("tool", "outcome", "day", "count(*)"):
        assert column in select_clause
    for column in ("actor_id", "actor_username", "client_address", "reason",
                   "route", "request_text", "resource", "collection", "table"):
        assert column not in lowered, f"{column} must not appear in _TOOL_SUMMARY_SQL"


def test_activity_summary_includes_tool_call_aggregate(monkeypatch):
    _install_pool(monkeypatch, [], tool_rows=[
        {"tool": "ai.search", "outcome": "ok", "day": date(2026, 9, 1), "n": 5},
        {"tool": "ai.sql", "outcome": "error", "day": date(2026, 9, 1), "n": 2},
    ])
    out = _run(audit_mod.activity_summary({"days": 7}, {"id": "u1"}))
    assert out["tool_calls"]["totals"] == {"ok": 5, "degraded": 0, "error": 2}
    by_tool = out["tool_calls"]["by_tool"]
    assert {"tool": "ai.search", "outcome": "ok", "day": "2026-09-01", "n": 5} in by_tool
    assert {"tool": "ai.sql", "outcome": "error", "day": "2026-09-01", "n": 2} in by_tool


def test_no_forbidden_string_survives_into_the_result(monkeypatch):
    _install_pool(monkeypatch, [
        {"permission": "query:run", "outcome": "denied", "day": "2026-09-01", "n": 1,
         # Fields a careless future change might add to the SELECT.
         "actor_username": "alice@example.com", "client_address": "10.1.2.3",
         "actor_id": "b7c1f2e0-0000-0000-0000-000000000001",
         "route": "/api/connectors/42/quality",
         "reason": "denied because the token had expired"},
    ])
    out = _run(audit_mod.activity_summary({"days": 7}, {"id": "u1"}))
    rendered = repr(out)
    for secret in FORBIDDEN:
        assert secret not in rendered


def test_pii_summary_reports_not_scanned_rather_than_clean(monkeypatch):
    """None from the scanner means the scan could not run. Reporting that as zero
    findings is the one answer that would be actively misleading — and a count field
    set to 0 reads exactly like a clean scan to anything that drops the prose, which
    is what a summary does. So the not-scanned response must not carry the count
    keys at all, not even as 0 or null."""
    monkeypatch.setattr("app.api.governance._scan_pii_tables", lambda: None)
    out = _run(gov_mod.pii_summary({}, {"id": "u1"}))
    assert out["scanned"] is False
    assert out["not_checked"]
    for absent in ("tables_with_pii", "columns_with_pii", "by_type", "by_table"):
        assert absent not in out, f"{absent} must not appear when no scan ran"


def test_pii_summary_counts_tables_and_columns_without_naming_columns(monkeypatch):
    monkeypatch.setattr(
        "app.api.governance._scan_pii_tables",
        lambda: [type("E", (), {"table": "crm.customers",
                                "pii_columns": [type("C", (), {"column": "ssn",
                                                               "type": "national_id"})()]})()])
    out = _run(gov_mod.pii_summary({}, {"id": "u1"}))
    assert out["scanned"] is True
    assert out["tables_with_pii"] == 1
    assert out["by_type"] == {"national_id": 1}
    assert "ssn" not in repr(out)


def test_scanned_and_not_scanned_are_distinguishable_by_shape_alone(monkeypatch):
    """A reader who never inspects a value — only the key set — must still be able to
    tell the two branches apart. If the shapes ever converged, "not scanned" would be
    one dropped word away from reading as "clean"."""
    monkeypatch.setattr("app.api.governance._scan_pii_tables", lambda: None)
    not_scanned = _run(gov_mod.pii_summary({}, {"id": "u1"}))

    monkeypatch.setattr(
        "app.api.governance._scan_pii_tables",
        lambda: [type("E", (), {"table": "crm.customers",
                                "pii_columns": [type("C", (), {"column": "ssn",
                                                               "type": "national_id"})()]})()])
    scanned = _run(gov_mod.pii_summary({}, {"id": "u1"}))

    assert set(not_scanned.keys()) != set(scanned.keys())
    for count_key in ("tables_with_pii", "columns_with_pii", "by_type", "by_table"):
        assert count_key in scanned and count_key not in not_scanned
