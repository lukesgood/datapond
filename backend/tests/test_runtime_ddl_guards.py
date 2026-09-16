"""The two DDL paths the backend still runs at request time must not issue DDL on a
migrated database.

0001_baseline.sql defines every table these paths create, so on a real deployment they
have nothing to do. That only became load-bearing with the least-privilege runtime role
(externalDatabase.appUser, migration 0012): PostgreSQL checks CREATE on the schema
*before* it checks whether the object exists, so `CREATE TABLE IF NOT EXISTS` and
`ADD COLUMN IF NOT EXISTS` both fail for a DML-only role — verified against the live
database, which answered `permission denied for schema public` and `must be owner of
table`. Unguarded, those statements would 500 the settings endpoints and log a failure
on every pool creation.
"""
import asyncio


class _SettingsConn:
    def __init__(self, exists):
        self.exists, self.calls = exists, []

    async def fetchval(self, sql, *a):
        self.calls.append(("fetchval", sql))
        return "public.system_settings" if self.exists else None

    async def execute(self, sql, *a):
        self.calls.append(("execute", sql))


def _ddl(conn):
    return [sql for kind, sql in conn.calls if kind == "execute"]


def test_settings_table_issues_no_ddl_when_it_exists():
    from app.api.system_settings import _ensure_table
    conn = _SettingsConn(exists=True)
    asyncio.run(_ensure_table(conn))
    assert _ddl(conn) == [], "a migrated DB must see no DDL from the settings endpoints"


def test_settings_table_is_still_created_when_absent():
    from app.api.system_settings import _ensure_table
    conn = _SettingsConn(exists=False)
    asyncio.run(_ensure_table(conn))
    assert any("CREATE TABLE" in sql for sql in _ddl(conn))


class _PoolConn:
    def __init__(self, columns):
        self.columns, self.executed = columns, []

    async def fetch(self, sql, *a):
        return [{"column_name": c} for c in self.columns]

    async def execute(self, sql, *a):
        self.executed.append(sql)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Pool:
    _closed = False

    def __init__(self, columns):
        self.conn = _PoolConn(columns)

    def acquire(self):
        return self.conn


def _make_pool(monkeypatch, columns):
    import app.api.connectors as c
    pool = _Pool(columns)

    async def fake_create_pool(**kw):
        return pool

    monkeypatch.setattr(c, "_db_pool", None)
    monkeypatch.setattr(c, "_pool_kwargs", lambda: {})
    monkeypatch.setattr(c.asyncpg, "create_pool", fake_create_pool)
    asyncio.run(c.get_db_pool())
    monkeypatch.setattr(c, "_db_pool", None)  # don't leak the fake into other tests
    return pool


ALL_COLUMNS = ["id", "partition_spec", "key_columns", "pii_columns"]


def test_pool_creation_issues_no_alter_when_columns_exist(monkeypatch):
    pool = _make_pool(monkeypatch, ALL_COLUMNS)
    assert pool.conn.executed == []


def test_pool_creation_adds_only_the_missing_column(monkeypatch):
    pool = _make_pool(monkeypatch, ["id", "partition_spec", "key_columns"])
    assert len(pool.conn.executed) == 1
    assert "pii_columns" in pool.conn.executed[0]
