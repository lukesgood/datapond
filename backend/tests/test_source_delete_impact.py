"""GET /connectors/{id}/delete-impact: what the delete confirmation tells the person."""
import asyncio
import uuid

from app.api import connectors as C

CID = "11111111-1111-1111-1111-111111111111"
ADMIN = {"id": "00000000-0000-0000-0000-0000000000a1", "role": "admin"}


class _Conn:
    async def fetch(self, sql, *a):
        return [{"source_table": "public.orders", "target_table": None, "target_catalog": None},
                {"source_table": "public.items", "target_table": "datapond.raw.items", "target_catalog": "polaris_lake"}]

    async def fetchrow(self, sql, *a):
        return {"schedule": "0 8 * * 1-5"}

    async def fetchval(self, sql, *a):
        return "src_shop"


class _Pool:
    def acquire(self):
        class Ctx:
            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *e):
                return False
        return Ctx()


def _afn(v):
    async def f(*a, **k):
        return v
    return f


def test_delete_impact_names_tables_catalog_schedule_and_dependents(monkeypatch):
    monkeypatch.setattr(C, "require_access", _afn(None))
    monkeypatch.setattr(C, "get_db_pool", _afn(_Pool()))
    monkeypatch.setattr(C, "_default_lake", lambda: "iceberg")
    asked = {}

    async def impact(table, user):
        asked.setdefault("calls", []).append(table)
        if table[0].startswith("src_shop."):
            return {"tables": {"src_shop.public.orders": {"metrics": [{"name": "live_orders", "label": "Live orders"}],
                                                          "concepts": [], "dashboards": [], "queries": {"calls": 2}}}}
        return {"tables": {
            "iceberg.default.orders": {"metrics": [{"name": "revenue", "label": "Revenue"}],
                                       "concepts": [{"concept": "주문", "column": "id"}, {"concept": "주문", "column": "x"}],
                                       "dashboards": [{"id": "d1", "name": "Sales"}], "queries": {"calls": 4}},
            "polaris_lake.raw.items": {"metrics": [], "concepts": [], "dashboards": [{"id": "d1", "name": "Sales"}],
                                       "queries": {"calls": 1}}}}
    from app.api import catalog as catalog_api
    monkeypatch.setattr(catalog_api, "table_impact", impact)
    out = asyncio.run(C.delete_impact(CID, ADMIN))
    assert out["lake_tables"] == ["iceberg.default.orders", "polaris_lake.raw.items"]
    assert asked["calls"][0] == out["lake_tables"]
    # The live catalog's own tables are checked too, and reported as breaking.
    assert asked["calls"][1] == ["src_shop.public.items", "src_shop.public.orders"]
    assert out["catalog"] == "src_shop" and out["scheduled"] is True
    assert out["impact_checked"] == 2
    assert out["built_on"] == {"metrics": ["Revenue"], "concepts": ["주문"], "dashboards": ["Sales"], "queries": 5}
    assert out["breaks"] == {"metrics": ["Live orders"], "concepts": [], "dashboards": [], "queries": 2}


def test_without_catalog_read_the_dependents_are_not_checked(monkeypatch):
    monkeypatch.setattr(C, "require_access", _afn(None))
    monkeypatch.setattr(C, "get_db_pool", _afn(_Pool()))
    monkeypatch.setattr(C, "_default_lake", lambda: "iceberg")
    out = asyncio.run(C.delete_impact(CID, {"id": "u", "role": "x", "permissions": ["connector:write"]}))
    assert out["impact_checked"] == 0 and out["built_on"]["metrics"] == []
    assert len(out["lake_tables"]) == 2


def test_every_table_is_checked_twelve_at_a_time(monkeypatch):
    class Many(_Conn):
        async def fetch(self, sql, *a):
            return [{"source_table": f"public.t{i:02d}", "target_table": None, "target_catalog": None} for i in range(16)]

    class P(_Pool):
        def acquire(self):
            class Ctx:
                async def __aenter__(self):
                    return Many()

                async def __aexit__(self, *e):
                    return False
            return Ctx()
    monkeypatch.setattr(C, "require_access", _afn(None))
    monkeypatch.setattr(C, "get_db_pool", _afn(P()))
    monkeypatch.setattr(C, "_default_lake", lambda: "iceberg")
    calls = []

    async def impact(table, user):
        calls.append(len(table))
        return {"tables": {t: {"metrics": [{"name": t, "label": t}], "concepts": [], "dashboards": [],
                               "queries": {"calls": 1}} for t in table}}
    from app.api import catalog as catalog_api
    monkeypatch.setattr(catalog_api, "table_impact", impact)
    out = asyncio.run(C.delete_impact(CID, ADMIN))
    assert calls[:2] == [12, 4] and out["impact_checked"] == 16
    assert len(out["built_on"]["metrics"]) == 16 and out["built_on"]["queries"] == 16


def test_the_sync_stream_needs_connector_write():
    route = next(r for r in C.router.routes if getattr(r, "path", "") == "/connectors/{connection_id}/sync/stream")
    assert "connector:write" in [getattr(d.call, "__datapond_authorization__", None) for d in route.dependant.dependencies]
