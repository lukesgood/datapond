"""Which tables a sync runs (app/sync_plan.py) and the sync's PII columns masked when a
source catalog is read directly (rls loader.load_source_masks)."""
import asyncio
import json

from app import sync_plan
from app.rls import loader
from app.rls.engine import UserContext, enforce


def test_a_bare_job_name_heals_to_its_one_qualified_table():
    discovered = ["public.customers", "public.orders", "a.items", "b.items"]
    assert sync_plan.legacy_renames(discovered, ["customers", "public.orders", "items", "gone"]) == {
        "customers": "public.customers"}                       # items is ambiguous, gone matches nothing
    # a qualified job already there wins: the bare one is not renamed onto it
    assert sync_plan.legacy_renames(discovered, ["customers", "public.customers"]) == {}


def test_new_tables_wait_after_the_first_sync_and_orphans_never_run():
    discovered = ["public.customers", "public.orders", "public.new_table"]
    first = sync_plan.plan(discovered, {})
    assert first["first_run"] and first["sync"] == discovered and first["new"] == []
    later = sync_plan.plan(discovered, {"public.customers": True, "public.orders": False,
                                        "information_schema.sql_parts": True})
    assert later["sync"] == ["public.customers"]
    assert later["skipped"] == ["public.orders"]
    assert later["new"] == ["public.new_table"]                # not synced unmasked on its own
    assert later["orphaned"] == ["information_schema.sql_parts"]


def test_the_live_case_customers_keeps_its_masks():
    """2026-11-23: job 'customers' carries the PII columns; the source lists
    'public.customers'. After healing, the sync plan runs it with its own settings."""
    renames = sync_plan.legacy_renames(["public.customers", "public.orders"], ["customers", "public.orders"])
    jobs = {renames.get(n, n): True for n in ["customers", "public.orders"]}
    assert sync_plan.plan(["public.customers", "public.orders"], jobs)["new"] == []


class _Conn:
    def __init__(self, rows, roles):
        self.rows, self.roles = rows, roles
    async def fetch(self, sql, *a):
        return self.roles if "FROM roles" in sql else self.rows


class _Acq:
    def __init__(self, c): self.c = c
    async def __aenter__(self): return self.c
    async def __aexit__(self, *a): return False


class _Pool:
    def __init__(self, c): self.c = c
    def acquire(self): return _Acq(self.c)


def test_sync_pii_columns_mask_direct_source_reads(monkeypatch):
    rows = [{"id": "j1", "engine_catalog": "src_shop", "source_table": "public.customers",
             "pii_columns": json.dumps(["email", "full_name"])},
            {"id": "j2", "engine_catalog": "src_shop", "source_table": "legacy",
             "pii_columns": json.dumps(["*"])}]
    conn = _Conn(rows, [("viewer",), ("admin",)])
    async def pool():
        return _Pool(conn)
    monkeypatch.setattr(loader, "_get_pool", pool)
    monkeypatch.setitem(loader._SOURCE_MASKS, "at", 0.0)
    masks = asyncio.run(loader.load_source_masks())
    assert [(m.catalog, m.schema, m.table, m.column) for m in masks] == [
        ("src_shop", "public", "customers", "email"), ("src_shop", "public", "customers", "full_name")]
    viewer = UserContext(user_id="u", username="v", roles=["viewer"])
    cols = {"src_shop.public.customers": ["id", "email", "full_name", "country"]}
    out = enforce("SELECT full_name, country FROM src_shop.public.customers", viewer, [], masks, columns=cols)
    assert "'***' AS \"full_name\"" in out.sql and "EXCEPT" not in out.sql and out.applied_mask_ids
    admin = UserContext(user_id="a", username="a", roles=["admin"])
    assert enforce("SELECT full_name FROM src_shop.public.customers", admin, [], masks, columns=cols).applied_mask_ids


def test_an_orphaned_job_can_be_deleted_but_a_listed_one_cannot(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.api import connectors as c
    class Conn:
        async def get_tables(self):
            return ["public.customers"]
    async def instance(cid):
        return Conn()
    async def ok(*a, **k):
        return None
    deleted = []
    class DB:
        async def execute(self, sql, *a):
            deleted.append(a[1]); return "DELETE 1"
    class Acq:
        async def __aenter__(self): return DB()
        async def __aexit__(self, *a): return False
    class Pool:
        def acquire(self): return Acq()
    async def pool():
        return Pool()
    monkeypatch.setattr(c, "_get_connector_instance", instance)
    monkeypatch.setattr(c, "require_access", ok)
    monkeypatch.setattr(c, "get_db_pool", pool)
    from app import security_audit
    monkeypatch.setattr(security_audit, "record", ok)
    cid = "00000000-0000-0000-0000-000000000009"
    with pytest.raises(HTTPException) as e:
        asyncio.run(c.delete_orphaned_job(cid, "public.customers", user={"id": "u"}))
    assert e.value.status_code == 409
    assert asyncio.run(c.delete_orphaned_job(cid, "information_schema.sql_parts", user={"id": "u"})) == {
        "deleted": "information_schema.sql_parts"}
    assert deleted == ["information_schema.sql_parts"]


def test_batch_conflicts():
    from app.sync_plan import batch_conflicts
    rows = [{"source_table": "customers", "target_table": "datapond.default.customers", "enabled": True}]
    # the qualified spelling lands where the bare job already lands
    assert batch_conflicts(rows, [{"table": "public.customers", "enabled": True}])
    # turning the old one off in the same batch clears it
    assert batch_conflicts(rows, [{"table": "public.customers", "enabled": True},
                                  {"table": "customers", "enabled": False}]) == []
    # two schemas of one table inside one batch
    assert batch_conflicts([], [{"table": "a.orders"}, {"table": "b.orders"}])
    assert batch_conflicts([], [{"table": "a.orders"}, {"table": "b.orders", "enabled": False}]) == []


def test_default_target_drops_the_schema():
    from app import sync_targets
    assert sync_targets.default_target("public.orders") == "datapond.default.orders"
    assert sync_targets.lake_table("public.orders", sync_targets.default_target("public.orders")) == ("default", "orders")


def test_rag_invalidation_reads_old_four_part_targets():
    from app.api.connectors import _synced_namespace_table_pairs
    res = [("public.orders", "datapond.default.public.orders", True, 1, None),
           ("public.items", "datapond.default.items", True, 1, None),
           ("public.x", "datapond.default.x", False, 0, None)]
    assert _synced_namespace_table_pairs(res) == [("default", "items"), ("default", "orders")]
