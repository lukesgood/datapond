"""Redshift and BigQuery (preview) sources: Trino catalogs like the other database types."""
import base64
import json

import pytest

from app.connectors import probe
from app.connectors import trino_source as ts
from app.connectors.base import ConnectorType as T

KEY = {"type": "service_account", "project_id": "acme-data-123", "client_email": "dp@acme-data-123.iam.gserviceaccount.com",
       "private_key": "-----BEGIN PRIVATE KEY-----\nMIIBVQIBADANBg\n-----END PRIVATE KEY-----\n", "private_key_id": "k1"}


def test_redshift_renders_a_jdbc_catalog_without_the_password():
    text = ts.render_catalog_properties(T.REDSHIFT, "src_wh", {
        "host": "wh.abc123.ap-northeast-2.redshift.amazonaws.com", "port": 5439, "database": "dev",
        "username": "reader", "password": "s3cret!", "ssl": True})
    assert text.splitlines() == [
        "connector.name=redshift",
        "connection-url=jdbc:redshift://wh.abc123.ap-northeast-2.redshift.amazonaws.com:5439/dev",
        "connection-user=reader",
        "connection-password=${ENV:SRC_WH_PASSWORD}"]
    assert "s3cret" not in text
    off = ts.render_catalog_properties(T.REDSHIFT, "src_wh", {
        "host": "h", "port": 5439, "database": "dev", "username": "u", "ssl": False})
    assert "jdbc:redshift://h:5439/dev;SSL=FALSE" in off
    with pytest.raises(ValueError):
        ts.render_catalog_properties(T.REDSHIFT, "src_wh", {"host": "h", "port": 5439, "username": "u"})


def test_redshift_is_a_trino_type_probed_like_postgres():
    assert ts.engine_of(T.REDSHIFT) == "trino" and probe.DRIVERS[T.REDSHIFT] == "psycopg2"
    cfg = ts.TrinoSourceConfig(name="x", connector_type=T.REDSHIFT, host="h", port=5439,
                               database="dev", username="u", password="p")
    assert probe.split_table(T.REDSHIFT, cfg, "orders") == ("public", "orders")


def test_bigquery_renders_project_and_a_base64_key_from_env():
    cfg = {"project_id": "acme-data-123", "credentials_key": json.dumps(KEY)}
    text = ts.render_catalog_properties(T.BIGQUERY, "src_bq", cfg)
    assert text.splitlines() == ["connector.name=bigquery", "bigquery.project-id=acme-data-123",
                                 "bigquery.credentials-key=${ENV:SRC_BQ_PASSWORD}"]
    assert "PRIVATE KEY" not in text
    value = ts.credential_value(T.BIGQUERY, cfg)
    assert json.loads(base64.b64decode(value)) == KEY
    billed = ts.render_catalog_properties(T.BIGQUERY, "src_bq", {**cfg, "parent_project_id": "acme-billing"})
    assert billed.splitlines()[-1] == "bigquery.parent-project-id=acme-billing"
    # The project may come from the key itself.
    assert "bigquery.project-id=acme-data-123" in ts.render_catalog_properties(
        T.BIGQUERY, "src_bq", {"credentials_key": json.dumps(KEY)})


@pytest.mark.parametrize("bad", [
    {"project_id": "acme-data-123", "credentials_key": "not json"},
    {"project_id": "acme-data-123", "credentials_key": json.dumps({"type": "authorized_user"})},
    {"project_id": "Bad Project;x=1", "credentials_key": json.dumps(KEY)},
    {"project_id": "acme-data-123", "parent_project_id": "x\nconnector.name=evil", "credentials_key": json.dumps(KEY)},
])
def test_bigquery_refuses_bad_keys_and_project_ids(bad):
    with pytest.raises(ValueError):
        ts.render_catalog_properties(T.BIGQUERY, "src_bq", bad)


def test_bigquery_probe_lists_datasets_and_tables_and_maps_types(monkeypatch):
    cfg = ts.TrinoSourceConfig(name="x", connector_type=T.BIGQUERY, credentials_key=json.dumps(KEY))
    calls = []

    def fake_get(c, path, timeout, params=None):
        calls.append(path)
        if path.endswith("/datasets"):
            return {"datasets": [{"datasetReference": {"datasetId": "sales"}}]}
        if path.endswith("/datasets/sales/tables"):
            return {"tables": [{"tableReference": {"tableId": "orders"}, "type": "TABLE"}]}
        if path.endswith("/tables/orders"):
            return {"schema": {"fields": [{"name": "id", "type": "INTEGER", "mode": "REQUIRED"},
                                          {"name": "paid_at", "type": "TIMESTAMP"},
                                          {"name": "tags", "type": "STRING", "mode": "REPEATED"}]}}
        raise AssertionError(path)

    monkeypatch.setattr(probe, "_bq_get", fake_get)
    r = probe.test(T.BIGQUERY, cfg)
    assert r.success and "acme-data-123" in r.message and r.metadata["preview"] is True
    assert probe.list_tables(T.BIGQUERY, cfg) == ["sales.orders"]
    cols = probe.columns(T.BIGQUERY, cfg, "sales.orders")
    assert [(c.name, c.type, c.nullable) for c in cols] == [
        ("id", "bigint", False), ("paid_at", "timestamp(6) with time zone", True), ("tags", "array", True)]
    assert calls[0] == "/projects/acme-data-123/datasets"


def test_bigquery_probe_failure_never_carries_the_private_key(monkeypatch):
    cfg = ts.TrinoSourceConfig(name="x", connector_type=T.BIGQUERY, credentials_key=json.dumps(KEY))

    def boom(c, path, timeout, params=None):
        raise RuntimeError(f"bad key {KEY['private_key']}")
    monkeypatch.setattr(probe, "_bq_get", boom)
    r = probe.test(T.BIGQUERY, cfg)
    assert r.success is False and "PRIVATE KEY" not in r.message
    bad = probe.test(T.BIGQUERY, cfg.model_copy(update={"credentials_key": "{}"}))
    assert bad.success is False and "service-account" in bad.message


def test_removed_types_are_gone_and_the_catalog_lists_the_new_ones():
    assert {"kafka", "kinesis", "gcs", "azure_blob"}.isdisjoint(t.value for t in T)
    import asyncio
    from app.api.connectors import list_available_connectors
    got = {c["id"]: c for c in asyncio.run(list_available_connectors())}
    assert "kafka" not in got
    assert got["redshift"]["engine"] == "trino" and got["redshift"]["supported"]
    assert got["bigquery"]["tier"] == "preview"
    assert got["bigquery"]["config_schema"]["credentials_key"]["type"] == "password"
