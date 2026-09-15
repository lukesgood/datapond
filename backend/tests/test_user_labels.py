"""Audit and spend views show a readable name next to a user id, and never lose a row for want of one."""
import asyncio
from types import SimpleNamespace

import app.api.ai_backends as ai
import app.api.governance as gov
from app.user_labels import labels_async, labels_sync


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _LabelDB:
    """Answers the users lookup; records what it was asked."""
    def __init__(self, rows=(), fail=False):
        self.rows, self.fail, self.calls, self.rolled_back = list(rows), fail, [], 0

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))
        if self.fail:
            raise RuntimeError("users table missing")
        return _Rows(self.rows)

    def rollback(self):
        self.rolled_back += 1


class _NoDB:
    def execute(self, *a, **k):
        raise AssertionError("no lookup should run without ids")


def test_no_ids_means_no_query():
    assert labels_sync(_NoDB(), [None, ""]) == {}


def test_ids_are_deduplicated_and_labels_returned():
    db = _LabelDB([SimpleNamespace(id="u1", label="alice"), SimpleNamespace(id="u2", label=None)])
    assert labels_sync(db, ["u1", "u1", None, "u2"]) == {"u1": "alice"}
    assert db.calls[0][1] == {"ids": ["u1", "u2"]}


def test_a_service_account_is_named_by_username():
    db = _LabelDB()
    labels_sync(db, ["u1"])
    assert "auth_method::text = 'service' THEN username" in db.calls[0][0]


def test_a_failed_lookup_yields_no_names_and_rolls_back():
    db = _LabelDB(fail=True)
    assert labels_sync(db, ["u1"]) == {}
    assert db.rolled_back == 1


class _Conn:
    def __init__(self, rows=(), fail=False):
        self.rows, self.fail, self.args = list(rows), fail, None

    async def fetch(self, sql, *args):
        self.args = args
        if self.fail:
            raise RuntimeError("down")
        return self.rows


def test_async_lookup_matches_sync():
    conn = _Conn([{"id": "u1", "label": "svc-bot"}])
    assert _run(labels_async(conn, ["u1", "u1"])) == {"u1": "svc-bot"}
    assert conn.args == (["u1"],)
    assert _run(labels_async(_Conn(fail=True), ["u1"])) == {}


# ── /governance/audit-log ─────────────────────────────────────────────────────

class _Query:
    def __init__(self, items):
        self.items = items

    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def offset(self, *a, **k): return self
    def count(self): return len(self.items)
    def all(self): return self.items


class _AuditDB(_LabelDB):
    def __init__(self, items, rows):
        super().__init__(rows)
        self.items = items

    def query(self, *a, **k):
        return _Query(self.items)


def _history(user_id):
    return SimpleNamespace(id=1, status="success", query_text="SELECT 1", user_id=user_id,
                           execution_time_ms=3, rows_returned=1, catalog="c", schema="s",
                           created_at=None)


def test_audit_log_rows_carry_the_user_name():
    db = _AuditDB([_history("u1"), _history("u9")], [SimpleNamespace(id="u1", label="alice")])
    res = gov.get_audit_log(event_type=None, limit=50, offset=0, db=db)
    res = _run(res) if asyncio.iscoroutine(res) else res
    assert [(i.user_id, i.user_name) for i in res.items] == [("u1", "alice"), ("u9", None)]


# ── /settings/ai/usage by-user rows ───────────────────────────────────────────

def test_spend_rows_gain_names_and_unattributed_is_left_alone(monkeypatch):
    class _Pool:
        def acquire(self):
            conn = _Conn([{"id": "u1", "label": "alice"}])

            class _Ctx:
                async def __aenter__(self): return conn
                async def __aexit__(self, *a): return False
            return _Ctx()

    async def _pool():
        return _Pool()

    import app.api.connectors as connectors
    monkeypatch.setattr(connectors, "get_db_pool", _pool)
    rows = _run(ai._with_user_names([{"user": "u1"}, {"user": "unattributed"}, {"user": "tagcheck"}]))
    assert [(r["user"], r["name"]) for r in rows] == [("u1", "alice"), ("unattributed", None), ("tagcheck", None)]


def test_spend_rows_survive_a_database_outage(monkeypatch):
    async def _down():
        raise RuntimeError("no pool")

    import app.api.connectors as connectors
    monkeypatch.setattr(connectors, "get_db_pool", _down)
    rows = _run(ai._with_user_names([{"user": "u1", "spend": 1.0}]))
    assert rows == [{"user": "u1", "spend": 1.0, "name": None}]


# ── /governance/audit-stream ──────────────────────────────────────────────────

class _StreamDB(_LabelDB):
    def __init__(self, query_rows, auth_rows, label_rows):
        super().__init__(label_rows)
        self.query_rows, self.auth_rows = query_rows, auth_rows

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "FROM users" in sql:
            return super().execute(stmt, params)
        if "query_history" in sql:
            return _Rows(self.query_rows)
        if "auth_audit_log" in sql:
            return _Rows(self.auth_rows)
        return _Rows([])


def test_stream_names_bare_user_ids_but_keeps_emails():
    from datetime import datetime, timezone
    t = datetime(2026, 9, 1, tzinfo=timezone.utc)
    q = [SimpleNamespace(id="q1", status="success", user_id="u1", catalog="c", schema="s",
                         query_text="SELECT 1", created_at=t)]
    a = [SimpleNamespace(id="a1", event_type="login", user_email="ops@x", user_id="u2", resource=None,
                         action="login", result="success", failure_reason=None, created_at=t)]
    db = _StreamDB(q, a, [SimpleNamespace(id="u1", label="alice")])
    res = _run(gov.get_audit_stream(source=None, limit=10, db=db))
    by_source = {i.source: i for i in res.items}
    assert (by_source["query"].actor, by_source["query"].actor_name) == ("u1", "alice")
    assert (by_source["auth"].actor, by_source["auth"].actor_name) == ("ops@x", None)
    label_calls = [c for c in db.calls if "FROM users" in c[0]]
    assert label_calls and label_calls[0][1] == {"ids": ["u1"]}
