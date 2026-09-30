import asyncio
from datetime import datetime, timedelta, timezone


def test_is_due():
    import app.rag_scheduler as s
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    assert s._is_due(None, 60, now) is True                          # never run
    assert s._is_due(now - timedelta(minutes=61), 60, now) is True   # overdue
    assert s._is_due(now - timedelta(minutes=10), 60, now) is False  # not yet


class _Conn:
    def __init__(self, lock=True, rows=None, sink=None):
        self._lock = lock
        self._rows = rows or []
        self.sink = sink if sink is not None else []
    async def fetchval(self, sql, *a):
        if "pg_try_advisory_lock" in sql:
            return self._lock
        return None
    async def fetch(self, sql, *a):
        if "FROM ai_collections" in sql:
            return self._rows
        return []
    async def execute(self, sql, *a):
        self.sink.append((sql, a))
    async def __aenter__(self): return self
    async def __aexit__(self, *e): return False


class _Pool:
    def __init__(self, conn): self._c = conn
    def acquire(self): return self._c


def test_tick_skips_when_lock_not_acquired():
    import app.rag_scheduler as s
    conn = _Conn(lock=False, rows=[{"id": "c1", "name": "kb", "refresh_source": "{}",
                                    "refresh_interval_minutes": 60, "last_refreshed_at": None}])
    n = asyncio.run(s.tick(_Pool(conn)))
    assert n == 0


def test_tick_refreshes_due_and_records_status(monkeypatch):
    import app.rag_scheduler as s
    import app.api.ai_vectors as v
    calls = []
    async def fake_refresh(pool, coll_id, src):
        calls.append((coll_id, src.type))
        return {"documents": 1, "chunks": 2, "pii_masked": 0}
    monkeypatch.setattr(v, "_refresh_from_source", fake_refresh)
    row = {"id": "c1", "name": "kb",
           "refresh_source": '{"type": "s3", "bucket": "b", "prefix": "p/"}',
           "refresh_interval_minutes": 60, "last_refreshed_at": None}
    conn = _Conn(lock=True, rows=[row])
    n = asyncio.run(s.tick(_Pool(conn)))
    assert n == 1 and calls == [("c1", "s3")]
    statuses = [a for (sql, a) in conn.sink if "last_refresh_status" in sql]
    assert statuses and "ok" in str(statuses[0])


# ── catalog access is re-checked when the schedule runs (multi-catalog P3) ──────
#
# A schedule is saved by someone who could use its catalog then. It runs as the
# collection's owner, re-checked on every run: a grant revoked since must stop it.

import pytest

OWNER = "11111111-1111-1111-1111-111111111111"


class _UserConn(_Conn):
    def __init__(self, users=None, **kw):
        super().__init__(**kw)
        self.users = users or {}

    async def fetchrow(self, sql, *a):
        if "FROM users" in sql:
            return self.users.get(str(a[0]))
        return None


@pytest.fixture
def two_catalogs():
    from app import catalog_access
    from app import catalog_registry as reg
    from app.catalog_registry import CatalogEntry
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
    ])
    catalog_access.set_grants({"finance": [("role", "business_analyst")]})
    yield
    reg.reset()
    catalog_access.reset()


def _iceberg_row(catalog, owner=OWNER):
    import json
    src = {"type": "iceberg", "schema": "gl", "table": "entries", "text_column": "memo"}
    if catalog:
        src["catalog"] = catalog
    return {"id": "c1", "name": "kb", "owner_id": owner, "refresh_source": json.dumps(src),
            "refresh_interval_minutes": 60, "last_refreshed_at": None}


def _wire(monkeypatch):
    import app.api.ai_vectors as v
    import app.rag_scheduler as s
    calls, audited = [], []

    async def fake_refresh(pool, coll_id, src):
        calls.append((coll_id, src.catalog))
        return {"documents": 1, "chunks": 2}

    async def fake_audit(**kw):
        audited.append(kw)
    monkeypatch.setattr(v, "_refresh_from_source", fake_refresh)
    monkeypatch.setattr(s.security_audit, "record", fake_audit)
    return calls, audited


def _user(role, active=True, name="alice"):
    return {OWNER: {"id": OWNER, "username": name, "role": role, "is_active": active}}


def test_a_revoked_grant_stops_the_schedule_and_is_audited(monkeypatch, two_catalogs):
    import app.rag_scheduler as s
    calls, audited = _wire(monkeypatch)
    # The owner's role no longer holds the grant (it was business_analyst when saved).
    conn = _UserConn(rows=[_iceberg_row("finance")], users=_user("viewer"))
    n = asyncio.run(s.tick(_Pool(conn)))
    assert n == 0 and calls == []
    statuses = [a for (sql, a) in conn.sink if "last_refresh_status" in sql]
    assert statuses and str(statuses[0][1]).startswith("skipped")
    assert [(a["permission"], a["outcome"]) for a in audited] == [("catalog:use", "denied")]
    assert audited[0]["actor"]["username"] == "alice"
    assert "finance" in audited[0]["reason"]          # the auditor sees which catalog


def test_a_granted_owner_still_runs(monkeypatch, two_catalogs):
    import app.rag_scheduler as s
    calls, audited = _wire(monkeypatch)
    conn = _UserConn(rows=[_iceberg_row("finance")], users=_user("business_analyst"))
    assert asyncio.run(s.tick(_Pool(conn))) == 1
    assert calls == [("c1", "finance")] and audited == []


def test_an_open_catalog_runs_as_before(monkeypatch, two_catalogs):
    import app.rag_scheduler as s
    calls, audited = _wire(monkeypatch)
    conn = _UserConn(rows=[_iceberg_row(None)], users=_user("viewer"))
    assert asyncio.run(s.tick(_Pool(conn))) == 1
    assert calls == [("c1", None)] and audited == []


def test_a_global_collection_may_only_read_an_open_catalog(monkeypatch, two_catalogs):
    """Every knowledge reader can search a collection with no owner, so only a
    catalog open to every caller may feed it on a schedule."""
    import app.rag_scheduler as s
    calls, audited = _wire(monkeypatch)
    conn = _UserConn(rows=[_iceberg_row("finance", owner=None)])
    assert asyncio.run(s.tick(_Pool(conn))) == 0
    assert calls == [] and len(audited) == 1
    conn = _UserConn(rows=[_iceberg_row(None, owner=None)])
    assert asyncio.run(s.tick(_Pool(conn))) == 1


def test_a_disabled_owner_holds_no_grant(monkeypatch, two_catalogs):
    import app.rag_scheduler as s
    calls, audited = _wire(monkeypatch)
    conn = _UserConn(rows=[_iceberg_row("finance")],
                     users=_user("business_analyst", active=False))
    assert asyncio.run(s.tick(_Pool(conn))) == 0
    assert calls == [] and len(audited) == 1


def test_an_admin_owner_is_exempt(monkeypatch, two_catalogs):
    import app.rag_scheduler as s
    calls, _ = _wire(monkeypatch)
    conn = _UserConn(rows=[_iceberg_row("finance")], users=_user("admin", name="root"))
    assert asyncio.run(s.tick(_Pool(conn))) == 1


def test_unreadable_grants_stop_the_schedule(monkeypatch, two_catalogs):
    import app.rag_scheduler as s
    from app import catalog_access
    calls, audited = _wire(monkeypatch)

    async def boom(**kw):
        raise catalog_access.GrantsUnavailable("db down")
    monkeypatch.setattr(catalog_access, "load_grants", boom)
    conn = _UserConn(rows=[_iceberg_row(None)], users=_user("business_analyst"))
    assert asyncio.run(s.tick(_Pool(conn))) == 0 and calls == []


def test_an_s3_source_is_not_catalog_checked(monkeypatch, two_catalogs):
    import app.rag_scheduler as s
    calls, audited = _wire(monkeypatch)
    row = {"id": "c1", "name": "kb", "owner_id": None,
           "refresh_source": '{"type": "s3", "bucket": "b"}',
           "refresh_interval_minutes": 60, "last_refreshed_at": None}
    assert asyncio.run(s.tick(_Pool(_UserConn(rows=[row])))) == 1 and audited == []
