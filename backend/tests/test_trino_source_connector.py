"""Once a connection is a Trino catalog, every read of it goes through Trino; before
that, through the driver probe (Phase 2 plan, Task 5)."""
import asyncio

import pytest

from app.connectors.base import ConnectorType as T
from app.connectors.trino_source import TrinoSourceConfig, TrinoSourceConnector


class FakeCursor:
    def __init__(self, answers):
        self.answers, self.executed, self._rows = answers, [], []
        self.description = [("id",), ("email",)]

    def execute(self, sql, params=None):
        self.executed.append(sql)
        key = sql.split(" FROM ")[-1].split(" ")[0]
        self._rows = self.answers.get(key, [])

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class FakeConn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def close(self):
        pass


def _connector(answers, **overrides):
    cfg = dict(name="crm", connector_type=T.POSTGRESQL, host="h", port=5432, database="d",
               username="u", password="p", catalog="src_crm")
    cfg.update(overrides)
    c = TrinoSourceConnector(TrinoSourceConfig(**cfg))
    c._cursors = []

    def connect(**kw):
        cur = FakeCursor(answers)
        c._cursors.append((kw, cur))
        return FakeConn(cur)
    c._connect = connect
    return c


def test_tables_come_from_trino_as_schema_dot_table_without_system_schemas():
    c = _connector({"src_crm": [("public",), ("pg_catalog",), ("information_schema",), ("sales",)],
                    "src_crm.public": [("orders",), ("users",)],
                    "src_crm.sales": [("leads",)]})
    assert asyncio.run(c.get_tables()) == ["public.orders", "public.users", "sales.leads"]
    assert all(kw.get("catalog") == "src_crm" for kw, _ in c._cursors)


def test_schema_comes_from_information_schema_columns():
    c = _connector({"src_crm.information_schema.columns": [("id", "integer", "NO"),
                                                           ("email", "varchar(255)", "YES")]})
    s = asyncio.run(c.get_schema("public.users"))
    assert s.table_name == "public.users"
    assert [(col.name, col.type, col.nullable) for col in s.columns] == [
        ("id", "integer", False), ("email", "varchar(255)", True)]
    sql = c._cursors[-1][1].executed[-1]
    assert "table_schema='public'" in sql and "table_name='users'" in sql


def test_read_data_selects_from_the_catalog_with_limit_and_offset():
    c = _connector({"src_crm.public.users": [(1, "a@x"), (2, "b@x")]})
    rows = asyncio.run(c.read_data("public.users", limit=2, offset=5))
    assert rows == [{"id": 1, "email": "a@x"}, {"id": 2, "email": "b@x"}]
    assert c._cursors[-1][1].executed[-1] == "SELECT * FROM src_crm.public.users ORDER BY 1 OFFSET 5 LIMIT 2", \
        "pages are only pages under one order (deferred minor #12: OFFSET without ORDER BY)"


def test_a_table_name_that_is_not_an_identifier_is_refused():
    c = _connector({})
    with pytest.raises(ValueError):
        asyncio.run(c.get_schema("public.users; DROP TABLE x"))
    with pytest.raises(ValueError):
        asyncio.run(c.read_data("a.b.c.d"))


def test_without_a_catalog_yet_tables_and_columns_come_from_the_driver_probe(monkeypatch):
    from app.connectors import probe
    from app.connectors.base import ColumnSchema
    monkeypatch.setattr(probe, "list_tables", lambda t, cfg, timeout=10.0: ["public.orders"])
    monkeypatch.setattr(probe, "columns", lambda t, cfg, table, timeout=10.0: [
        ColumnSchema(name="id", type="integer", nullable=False)])
    c = TrinoSourceConnector(TrinoSourceConfig(name="crm", connector_type=T.POSTGRESQL, host="h",
                                               port=5432, database="d", username="u", password="p"))
    assert asyncio.run(c.get_tables()) == ["public.orders"]
    assert asyncio.run(c.get_schema("public.orders")).columns[0].name == "id"


def test_test_connection_always_uses_the_driver(monkeypatch):
    from app.connectors import probe
    from app.connectors.base import ConnectionTestResult
    seen = []

    def fake_test(t, cfg, timeout=10.0):
        seen.append((t, cfg.host))
        return ConnectionTestResult(success=True, message="ok")
    monkeypatch.setattr(probe, "test", fake_test)
    c = _connector({})
    assert asyncio.run(c.test_connection()).success is True
    assert seen == [(T.POSTGRESQL, "h")]
