"""Before a connection exists as a Trino catalog, the wizard still has to test it and
list its tables: that goes through the source's own driver (Phase 2 plan, Task 5)."""
import pytest

from app.connectors import probe
from app.connectors.base import ConnectorType as T
from app.connectors.trino_source import TrinoSourceConfig

CFG = TrinoSourceConfig(name="x", connector_type=T.POSTGRESQL, host="127.0.0.1", port=1,
                        database="d", username="u", password="hunter2")


def test_every_trino_type_has_a_driver_and_the_drivers_are_importable():
    assert set(probe.DRIVERS) == {T.POSTGRESQL, T.MYSQL, T.SQLSERVER, T.ORACLE, T.MONGODB}
    for mod in probe.DRIVERS.values():
        __import__(mod)


@pytest.mark.parametrize("t", list(probe.DRIVERS))
def test_a_refused_connection_is_a_result_not_an_exception_and_never_names_the_password(t):
    r = probe.test(t, CFG.model_copy(update={"connector_type": t}), timeout=2)
    assert r.success is False and r.message
    assert "hunter2" not in r.message


def test_a_missing_driver_is_reported_not_raised(monkeypatch):
    monkeypatch.setitem(probe.DRIVERS, T.ORACLE, "no_such_driver_xyz")
    r = probe.test(T.ORACLE, CFG, timeout=1)
    assert r.success is False and "not installed" in r.message


def test_the_password_is_scrubbed_even_when_url_encoded():
    cfg = CFG.model_copy(update={"password": "p@ss w"})
    assert "p%40ss+w" not in probe.scrub("auth failed for p%40ss+w and p@ss w", cfg)
    assert "p@ss w" not in probe.scrub("auth failed for p%40ss+w and p@ss w", cfg)


def test_table_names_are_split_into_schema_and_table_with_a_per_engine_default():
    assert probe.split_table(T.POSTGRESQL, CFG, "sales.orders") == ("sales", "orders")
    assert probe.split_table(T.POSTGRESQL, CFG, "orders") == ("public", "orders")
    assert probe.split_table(T.SQLSERVER, CFG, "orders") == ("dbo", "orders")
    assert probe.split_table(T.MYSQL, CFG, "orders") == ("d", "orders")
    assert probe.split_table(T.ORACLE, CFG, "orders") == ("U", "orders")
    assert probe.split_table(T.MONGODB, CFG, "orders") == ("d", "orders")


def test_mongo_column_types_follow_the_sampled_values():
    import datetime
    doc = {"_id": "x", "n": 1, "f": 1.5, "ok": True, "at": datetime.datetime(2026, 1, 1),
           "nested": {"a": 1}, "tags": ["a"], "none": None}
    cols = {c.name: c.type for c in probe.mongo_columns(doc)}
    assert cols == {"_id": "varchar", "n": "bigint", "f": "double", "ok": "boolean",
                    "at": "timestamp(3)", "nested": "json", "tags": "json", "none": "varchar"}
