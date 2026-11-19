"""The data flow map is drawn only from what runs, keyed namespace.table."""
from datetime import datetime, timedelta, timezone

from app import flow_map as fm

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)


def _flow(**kw):
    conns = [{"id": "c1", "name": "Orders DB", "connector_type": "postgresql"}]
    jobs = [
        {"connection_id": "c1", "source_table": "public.orders", "target_table": "datapond.raw.public.orders",
         "last_run_status": "success", "last_run_at": NOW - timedelta(hours=2)},
        {"connection_id": "c1", "source_table": "customers", "target_table": "datapond.raw.customers",
         "last_run_status": "success", "last_run_at": NOW - timedelta(days=3)},
        {"connection_id": "hidden", "source_table": "secret", "target_table": "datapond.raw.secret",
         "last_run_status": "success", "last_run_at": NOW},
    ]
    transforms = [
        {"id": "t1", "name": "customer_clean", "schedule": "@hourly", "target_namespace": "refined",
         "target_table": "customers", "reads": ["iceberg.raw.customers"], "last_run_state": "failed",
         "last_run_at": (NOW - timedelta(minutes=40)).isoformat()},
        {"id": "t2", "name": "daily_revenue", "schedule": "0 3 * * *", "target_namespace": "serving",
         "target_table": "daily_revenue", "reads": ["iceberg.refined.customers", "iceberg.raw.orders"],
         "last_run_state": "success", "last_run_at": (NOW - timedelta(hours=1)).isoformat()},
    ]
    sinks = [{"name": "shop_cdc_payments_sink", "source_connector": "postgres-cdc",
              "definition": "CREATE SINK shop_cdc_payments_sink FROM shop_cdc_payments_mv WITH (connector = 'iceberg', database.name = 'raw', table.name = 'payments')"}]
    return fm.build_flow(kw.get("conns", conns), kw.get("jobs", jobs), kw.get("transforms", transforms),
                         kw.get("sinks", sinks), now=NOW)


def test_nodes_edges_and_columns():
    out = _flow()
    nodes = {n["id"]: n for n in out["nodes"]}
    assert {"source:c1", "raw.orders", "raw.customers", "refined.customers", "serving.daily_revenue",
            "stream:shop_cdc_payments", "raw.payments"} <= set(nodes)
    assert "raw.secret" not in nodes, "a job of a source the caller cannot see is left out"
    assert nodes["source:c1"]["column"] == 0 and nodes["raw.orders"]["column"] == 1
    assert nodes["refined.customers"]["column"] == 2 and nodes["serving.daily_revenue"]["column"] == 3
    kinds = {(e["from"], e["to"]): e["kind"] for e in out["edges"]}
    assert kinds[("source:c1", "raw.orders")] == "sync"
    assert kinds[("raw.customers", "refined.customers")] == "transform"
    assert kinds[("stream:shop_cdc_payments", "raw.payments")] == "stream"


def test_states_and_stale_input_propagate():
    nodes = {n["id"]: n for n in _flow()["nodes"]}
    assert nodes["raw.orders"]["state"] == "ok"
    assert nodes["raw.customers"]["state"] == "stale"
    assert nodes["refined.customers"]["state"] == "failed"
    assert nodes["refined.customers"]["stale_input"] == ["raw.customers"]
    assert nodes["serving.daily_revenue"]["state"] == "ok"
    assert nodes["serving.daily_revenue"]["stale_input"] == ["refined.customers"]
    assert nodes["raw.payments"]["state"] == "live"


def test_manual_transform_is_not_stale_and_unknown_inputs_are_external():
    t = [{"id": "t", "name": "adhoc", "schedule": None, "target_namespace": "serving", "target_table": "x",
          "reads": ["refined.unmanaged"], "last_run_state": "success",
          "last_run_at": (NOW - timedelta(days=10)).isoformat()}]
    nodes = {n["id"]: n for n in _flow(conns=[], jobs=[], transforms=t, sinks=[])["nodes"]}
    assert nodes["serving.x"]["state"] == "ok"
    assert nodes["refined.unmanaged"]["state"] == "external" and nodes["refined.unmanaged"]["column"] == 1


def test_keys():
    assert fm.table_key("iceberg.Raw.Orders") == "raw.orders"
    assert fm.table_key("orders") == "default.orders"
    assert fm.sync_target_key("public.orders", "datapond.default.public.orders") == "default.orders"
    assert fm.sink_target("... database.name = 'raw', table.name = 'o''x'") == "raw.o_x"


def test_flow_route_is_matched_before_the_id_route():
    import app.database.connection as _dbc
    _dbc.Base.metadata.create_all = lambda *a, **k: None  # type: ignore[assignment]
    from app.api import transforms
    paths = [getattr(r, "path", "") for r in transforms.router.routes]
    assert paths.index("/transforms/flow") < paths.index("/transforms/{transform_id}")
