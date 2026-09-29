"""The sample sources join back into the e-commerce sample, and each one reads through
its own connector.

A sample REST feed that the REST connector cannot parse, or a returns file whose
order ids are not orders, is a demo that fails in front of the person it was meant to
convince. Everything here runs through the connector code a real sync uses, with the
network and the object store replaced — not through a re-derivation of what the
connector probably does.
"""
import asyncio
import datetime as dt
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import sample_data, sample_sources
from app.connectors.base import ConnectorType
from app.connectors.custom import CustomConfig, CustomConnector
from app.connectors.rest import RestConfig, RestConnector
from app.connectors.storage import S3Connector, StorageConfig


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _ecommerce_values(table: str, column: str) -> set:
    return {row[column] for row in sample_data.table(table).rows}


# ── the catalogue of kinds ────────────────────────────────────────────────────

def test_every_kind_is_a_different_connector_type():
    types = [s.connector_type for s in sample_sources.SAMPLE_SOURCES]
    assert len(types) == len(set(types))
    assert {"postgresql", "s3", "rest_api", "custom", "database_url"} <= set(types)


def test_the_postgres_kind_is_the_existing_sample_connector():
    """Found by name. A renamed kind would register a second copy of the e-commerce DB."""
    assert (sample_sources.sample_source("postgresql").name
            == sample_sources.POSTGRES_SAMPLE_NAME == "Sample E-Commerce DB")


def test_no_sample_table_shadows_an_ecommerce_table():
    """Every source syncs into the same catalog namespace, so a shared name would have
    one sync overwrite the other's table."""
    added = [t for s in sample_sources.SAMPLE_SOURCES if s.kind != "postgresql"
             for t in s.tables]
    assert len(added) == len(set(added))
    assert not set(added) & set(sample_data.table_names())


# ── cross-source joins ────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref", sample_sources.CROSS_SOURCE_REFERENCES,
                         ids=lambda r: f"{r.child}.{r.column}")
def test_every_cross_source_reference_resolves_in_the_seed(ref):
    parents = _ecommerce_values(ref.parent, ref.parent_column)
    rows = sample_sources.SOURCE_ROWS[ref.child]
    assert rows, f"{ref.child} has no rows"
    missing = {r[ref.column] for r in rows} - parents
    assert not missing, f"{ref.child}.{ref.column} points at no {ref.parent}: {sorted(missing)[:5]}"


def test_a_return_is_for_the_product_its_order_item_was():
    items = {i["id"]: i for i in sample_data.ORDER_ITEMS}
    for r in sample_sources.PRODUCT_RETURNS:
        item = items[r["order_item_id"]]
        assert (item["order_id"], item["product_id"]) == (r["order_id"], r["product_id"])


def test_payments_point_at_paid_invoices():
    paid = {i["id"] for i in sample_sources.INVOICES if i["status"] == "paid"}
    assert {p["invoice_id"] for p in sample_sources.PAYMENTS} == paid


def test_fx_rates_cover_every_order_date():
    """The REST join is by date: an order on a day with no rate converts to nothing."""
    rated = {r["rate_date"] for r in sample_sources.fx_rates()}
    ordered = {o["ordered_at"].date().isoformat() for o in sample_data.ORDERS}
    assert ordered <= rated


# ── object storage, read through the S3 connector ─────────────────────────────

class _FakeS3:
    """list_objects_v2 with a delimiter, get_object, and a paginator — the calls the
    S3 connector makes — over the files the sample would upload."""

    def __init__(self, files):
        self.objects = {key: body for key, body, _ in files}

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None, **_):
        keys = [k for k in self.objects if k.startswith(Prefix)]
        if Delimiter:
            folders = sorted({Prefix + k[len(Prefix):].split(Delimiter)[0] + Delimiter
                              for k in keys if Delimiter in k[len(Prefix):]})
            return {"CommonPrefixes": [{"Prefix": f} for f in folders]}
        return {"Contents": self._contents(keys)}

    def _contents(self, keys):
        return [{"Key": k, "Size": len(self.objects[k]), "ETag": '"x"',
                 "LastModified": dt.datetime(2026, 9, 1)} for k in keys]

    def get_paginator(self, _name):
        fake = self

        class _P:
            def paginate(self, Bucket, Prefix="", **_):
                return [{"Contents": fake._contents(
                    [k for k in fake.objects if k.startswith(Prefix)])}]
        return _P()

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self.objects[Key])}


@pytest.fixture
def s3_connector():
    connector = S3Connector(StorageConfig(
        name="s", connector_type=ConnectorType.S3, bucket="b",
        prefix=sample_sources.OBJECT_PREFIX))
    connector._s3_client = _FakeS3(sample_sources.object_files())
    return connector


def test_the_s3_connector_sees_one_table_per_folder_and_not_the_docs(s3_connector):
    assert sorted(_run(s3_connector.get_tables())) == sorted(
        sample_sources.sample_source("object_storage").tables)


@pytest.mark.parametrize("table,extension", [
    ("product_returns", "csv"), ("carrier_scans", "jsonl"),
    ("warehouse_sensors", "parquet")])
def test_each_table_reads_back_every_row_in_its_format(s3_connector, table, extension):
    client = s3_connector._s3_client
    files = _run(s3_connector.list_files(prefix=table))
    assert files and all(f["key"].endswith("." + extension) for f in files)
    frames = [s3_connector._read_file_to_df(client, f["key"]) for f in files]
    assert sum(len(f) for f in frames) == len(sample_sources.SOURCE_ROWS[table])


def test_the_policy_documents_are_text_knowledge_can_read():
    docs = [k for k, _, _ in sample_sources.object_files()
            if k.startswith(sample_sources.DOCS_PREFIX)]
    assert docs and all(k.endswith(".md") for k in docs)
    assert not sample_sources.DOCS_PREFIX.startswith(sample_sources.OBJECT_PREFIX)


# ── custom Python, run in the connector's sandbox ─────────────────────────────

def _calendar():
    return CustomConnector(CustomConfig(
        name="c", connector_type=ConnectorType.CUSTOM, **sample_sources.custom_config()))


def test_the_calendar_runs_in_the_sandbox_and_names_its_table():
    connector = _calendar()
    assert _run(connector.get_tables()) == ["business_calendar"]
    rows = connector.run()
    assert len(rows) == 365


def test_the_calendar_agrees_with_the_real_calendar():
    """The sandbox has no datetime, so the weekday is arithmetic. Check it against the
    library that does have one."""
    for row in _calendar().run():
        day = dt.date.fromisoformat(row["cal_date"])
        assert row["weekday"] == day.strftime("%a")
        assert row["is_weekend"] == (day.weekday() >= 5)
        assert row["is_business_day"] == (not row["is_weekend"] and not row["is_holiday"])


def test_an_unnamed_custom_connector_still_calls_its_table_result():
    connector = CustomConnector(CustomConfig(
        name="c", connector_type=ConnectorType.CUSTOM, code="def fetch_data():\n    return []"))
    assert _run(connector.get_tables()) == ["result"]


# ── REST, through the connector and the route ────────────────────────────────

def _fx_connector(api_key="k"):
    return RestConnector(RestConfig(
        name="r", connector_type=ConnectorType.REST_API,
        **sample_sources.rest_config("http://127.0.0.1:8000/api/sample-api/fx-rates", api_key)))


def test_the_rest_connector_extracts_the_rates_by_its_data_path(monkeypatch):
    connector = _fx_connector()
    monkeypatch.setattr(connector, "_get", lambda *a, **k: sample_sources.fx_payload())
    assert _run(connector.get_tables()) == ["fx_rates"]
    assert len(_run(connector.read_data("fx_rates"))) == len(sample_sources.fx_rates())


def test_the_rest_connector_sends_the_sample_key_header():
    headers = _fx_connector("dp_sample_abc")._build_headers()
    assert headers["X-Sample-Key"] == "dp_sample_abc"


def test_the_rest_connector_does_not_block_the_event_loop(monkeypatch):
    """The sample feed is served by the same single-worker backend that syncs it. A
    blocking GET on the event loop waits for a response only that loop can send."""
    connector = _fx_connector()
    seen = []

    def _get(*_a, **_k):
        seen.append(threading.current_thread() is threading.main_thread())
        return sample_sources.fx_payload()

    monkeypatch.setattr(connector, "_get", _get)
    _run(connector.test_connection())
    _run(connector.read_data("fx_rates"))
    _run(connector.get_schema("fx_rates"))
    assert seen == [False, False, False]


def test_an_unnamed_rest_connector_still_calls_its_table_root():
    connector = RestConnector(RestConfig(
        name="r", connector_type=ConnectorType.REST_API, base_url="https://api.example.com"))
    assert _run(connector.get_tables()) == ["root"]


@pytest.fixture
def feed():
    from app.api.sample_api import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_the_feed_refuses_a_caller_without_the_key(feed):
    assert feed.get("/api/sample-api/fx-rates").status_code == 401
    assert feed.get("/api/sample-api/fx-rates",
                    headers={"X-Sample-Key": "dp_sample_wrong"}).status_code == 401


def test_the_feed_answers_the_key_it_derives(feed):
    from app.api.sample_api import sample_api_key
    r = feed.get("/api/sample-api/fx-rates", headers={"X-Sample-Key": sample_api_key()})
    assert r.status_code == 200
    assert r.json()["data"]["rates"][0].keys() == {"rate_date", "currency", "krw_per_unit"}


def test_the_bearer_exemption_is_exactly_the_feed_route():
    """main.py exempts the path from the bearer check; the route then checks its own
    key. If the two paths drift apart the exemption guards nothing and the feed 401s."""
    import main
    from app.api.sample_api import FX_RATES_PATH
    assert "/api" + FX_RATES_PATH in main.AUTH_EXEMPT
    assert any(getattr(r, "path", None) == "/api" + FX_RATES_PATH for r in main.app.routes)


# ── database URL ──────────────────────────────────────────────────────────────

def test_the_finance_url_survives_a_password_with_url_characters():
    from sqlalchemy.engine import make_url
    url = make_url(sample_sources.database_url("pg", 5432, "datapond", "p@ss:w/rd#1"))
    assert (url.password, url.database, url.host) == ("p@ss:w/rd#1", "samplefinance", "pg")


def test_the_finance_tables_only_constrain_within_their_own_database():
    """invoices.order_id is a cross-source reference, so it must not become a
    REFERENCES clause — Postgres cannot reference a table in another database."""
    from app.sample_data import ddl_statement
    ddl = " ".join(ddl_statement(t) for t in sample_sources.FINANCE_DATASET)
    assert "REFERENCES orders" not in ddl
    assert "REFERENCES invoices" in ddl


# ── the route: one kind failing does not take the others with it ──────────────

def test_one_failing_kind_is_reported_and_the_rest_still_run(monkeypatch):
    from app.api import connectors

    async def ok(source):
        return {"id": "x", "action": "created", "status": "active"}

    async def boom(source):
        raise RuntimeError("bucket said no")

    builders = {k: ok for k in sample_sources.kinds()}
    builders["object_storage"] = boom
    monkeypatch.setattr(connectors, "_SAMPLE_BUILDERS", builders)
    out = _run(connectors.add_sample_sources(None))["results"]
    by_kind = {r["kind"]: r for r in out}
    assert set(by_kind) == set(sample_sources.kinds())
    assert by_kind["object_storage"]["status"] == "failed"
    assert "bucket said no" in by_kind["object_storage"]["detail"]
    assert all(r["status"] == "active" for k, r in by_kind.items() if k != "object_storage")


def test_an_unknown_kind_is_refused_before_anything_is_written(monkeypatch):
    from fastapi import HTTPException
    from app.api import connectors

    called = []

    async def record(source):
        called.append(source.kind)
        return {}

    monkeypatch.setattr(connectors, "_SAMPLE_BUILDERS",
                        {k: record for k in sample_sources.kinds()})
    with pytest.raises(HTTPException) as e:
        _run(connectors.add_sample_sources(
            connectors.SampleSourcesRequest(kinds=["rest_api", "mongodb"])))
    assert e.value.status_code == 400 and called == []
