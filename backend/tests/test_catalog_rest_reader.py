"""An Iceberg REST catalog is read by one reader: Polaris, Unity Catalog, Snowflake Open
Catalog, S3 Tables — and Glue, through its own REST endpoint.

Measured before this was built (docs/superpowers/specs/2026-09-29-multi-catalog-design.md
§5): Glue's REST endpoint lists a resource-link namespace's tables under the *target*
namespace, so the reader keys what it returns by the namespace it asked for. None of
these tests touch the network: `RestCatalog` is replaced at the one seam that builds it.
"""
import types

import pytest

from app import catalog_registry as reg
from app.api import catalog_backend as cb
from app.catalog_registry import CatalogEntry

SECRET = "client-id:super-secret-value"


class _Field:
    def __init__(self, name, ftype, required):
        self.name, self.field_type, self.required = name, ftype, required


class _Arrow:
    def __init__(self, cols, rows):
        self.column_names, self._rows = cols, rows

    def to_pylist(self):
        return [dict(zip(self.column_names, r)) for r in self._rows]


class _Table:
    def __init__(self):
        self.metadata = types.SimpleNamespace(location="s3://bucket/sales/orders")
        self.scan_limit = None

    def schema(self):
        return types.SimpleNamespace(fields=[_Field("id", "long", True),
                                             _Field("note", "string", False)])

    def current_snapshot(self):
        return types.SimpleNamespace(summary={"total-records": "7"})

    def scan(self, limit=None):
        self.scan_limit = limit
        return types.SimpleNamespace(to_arrow=lambda: _Arrow(["id", "note"], [[1, "a"]]))


class _FakeRest:
    """What pyiceberg's RestCatalog answers. A resource link (`link_ns`) returns its
    tables under the namespace it points at, exactly as Glue's REST endpoint does."""

    def __init__(self, props):
        self.props = props
        self.table = _Table()
        self.loaded = []

    def list_namespaces(self, *a):
        return [("sales",), ("link_ns",)]

    def list_tables(self, ns):
        if ns in ("link_ns", ("link_ns",)):
            return [("target_db", "orders"), ("target_db", "items")]
        return [("sales", "orders")]

    def load_table(self, ident):
        self.loaded.append(ident)
        return self.table


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reg.reset()
    cb.reset_rest_cache()
    built = []

    def _new(props):
        cat = _FakeRest(props)
        built.append(cat)
        return cat
    monkeypatch.setattr(cb, "_new_rest_catalog", _new)
    monkeypatch.setattr(reg, "secret_for", lambda entry: None)
    yield built
    reg.reset()
    cb.reset_rest_cache()


def _rest(name="lake", **config):
    cfg = {"uri": "https://catalog.example.com/api/catalog", "warehouse": "wh"}
    cfg.update(config)
    return CatalogEntry(name=name, kind="iceberg_rest", engine_catalog=name, config=cfg)


def _install(*extra):
    default = CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg",
                           config={"warehouse": "iceberg"}, is_default=True)
    reg.set_entries([default, *extra])


# ── reading ──────────────────────────────────────────────────────────────────

def test_iceberg_rest_entries_get_the_rest_reader():
    _install(_rest())
    assert isinstance(cb.get_catalog_reader("lake"), cb.IcebergRestReader)


def test_tables_of_a_resource_link_are_keyed_by_the_namespace_asked_for():
    """The endpoint names the link's tables under `target_db`; a caller that asked for
    `link_ns` must get them as link_ns's, or the resolver and the schema tree file
    them under a namespace the caller never listed."""
    _install(_rest())
    reader = cb.get_catalog_reader("lake")
    assert reader.list_namespaces() == ["sales", "link_ns"]
    assert reader.list_tables("link_ns") == ["orders", "items"]
    from app.api.table_resolver import build_catalog_index
    index = build_catalog_index(reader)
    assert index.tables["items"] == ("link_ns",)
    assert set(index.tables["orders"]) == {"sales", "link_ns"}


def test_details_load_the_table_by_the_namespace_asked_for(_clean):
    _install(_rest())
    reader = cb.get_catalog_reader("lake")
    assert reader.get_columns("link_ns", "orders") == [
        {"name": "id", "type": "long", "nullable": False},
        {"name": "note", "type": "string", "nullable": True}]
    assert reader.get_location("sales", "orders") == "s3://bucket/sales/orders"
    assert reader.row_count("sales", "orders") == 7
    assert _clean[0].loaded[0] == ("link_ns", "orders")


def test_preview_is_capped_at_500_rows(_clean):
    _install(_rest())
    out = cb.get_catalog_reader("lake").preview("sales", "orders", 10_000)
    assert _clean[0].table.scan_limit == 500
    assert out == {"columns": ["id", "note"], "rows": [[1, "a"]]}


def test_properties_carry_sigv4_and_never_a_secret_in_config():
    entry = _rest(sigv4=True, signing_name="s3tables", signing_region="us-east-1",
                  scope="PRINCIPAL_ROLE:ALL", prefix="p")
    props = cb.rest_properties(entry, None)
    assert props["uri"] == "https://catalog.example.com/api/catalog"
    assert props["warehouse"] == "wh"
    assert props["rest.sigv4-enabled"] == "true"
    assert props["rest.signing-name"] == "s3tables"
    assert props["rest.signing-region"] == "us-east-1"
    assert props["scope"] == "PRINCIPAL_ROLE:ALL" and props["prefix"] == "p"
    assert "credential" not in props and "token" not in props


def test_a_client_credential_secret_is_oauth_and_anything_else_a_bearer_token():
    assert cb.rest_properties(_rest(), SECRET)["credential"] == SECRET
    props = cb.rest_properties(_rest(), "eyJhbGciOi.tok")
    assert props["token"] == "eyJhbGciOi.tok" and "credential" not in props


def test_glue_via_rest_reads_glue_through_its_iceberg_endpoint():
    entry = CatalogEntry(name="partner", kind="glue", engine_catalog="partner",
                         config={"via_rest": True, "region": "ap-northeast-2",
                                 "catalog_id": "123456789012"})
    _install(entry)
    assert isinstance(cb.get_catalog_reader("partner"), cb.IcebergRestReader)
    props = cb.rest_properties(entry, None)
    assert props["uri"] == "https://glue.ap-northeast-2.amazonaws.com/iceberg"
    assert props["warehouse"] == "123456789012"
    assert props["rest.sigv4-enabled"] == "true"
    assert props["rest.signing-name"] == "glue"
    assert props["rest.signing-region"] == "ap-northeast-2"


def test_the_default_glue_entry_stays_on_the_glue_api(monkeypatch):
    default = CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="AwsDataCatalog",
                           config={"warehouse": "s3://b/w", "via_rest": True}, is_default=True)
    reg.set_entries([default])
    assert isinstance(cb.get_catalog_reader(), cb.GlueCatalogReader)


# ── the cache ────────────────────────────────────────────────────────────────

def test_one_rest_catalog_per_entry_until_its_config_changes(_clean):
    _install(_rest())
    cb.get_catalog_reader("lake").list_namespaces()
    cb.get_catalog_reader("lake").list_namespaces()
    assert len(_clean) == 1
    _install(_rest(warehouse="other"))
    cb.get_catalog_reader("lake").list_namespaces()
    assert len(_clean) == 2


def test_the_cache_expires(_clean, monkeypatch):
    _install(_rest())
    cb.get_catalog_reader("lake").list_namespaces()
    now = cb.time.monotonic()
    monkeypatch.setattr(cb.time, "monotonic", lambda: now + cb.REST_CACHE_TTL_SECONDS + 1)
    cb.get_catalog_reader("lake").list_namespaces()
    assert len(_clean) == 2


# ── a catalog that does not answer ───────────────────────────────────────────

def test_a_dead_catalog_is_not_retried_on_every_listing(monkeypatch):
    calls = []

    def _dead(props):
        calls.append(props)
        raise ConnectionError("connect timeout to https://catalog.example.com")
    monkeypatch.setattr(cb, "_new_rest_catalog", _dead)
    _install(_rest())
    for _ in range(3):
        with pytest.raises(Exception):
            cb.get_catalog_reader("lake").list_namespaces()
    assert len(calls) == 1


def test_a_failing_catalog_is_skipped_in_listings_and_the_others_answer(monkeypatch):
    def _new(props):
        if "dead" in props["uri"]:
            raise TimeoutError("read timed out")
        return _FakeRest(props)
    monkeypatch.setattr(cb, "_new_rest_catalog", _new)
    _install(_rest("good"), _rest("bad", uri="https://dead.example.com/cat"))
    from app.api import table_resolver
    monkeypatch.setattr(cb.PolarisCatalogReader, "list_namespaces", lambda self: ["public"])
    monkeypatch.setattr(cb.PolarisCatalogReader, "list_tables", lambda self, ns: ["t"])
    index = table_resolver.build_multi_catalog_index(table_resolver._registry_readers())
    assert "orders" in index.tables and ("good", "sales") in index.tables["orders"]
    assert not any(isinstance(loc, tuple) and loc[0] == "bad"
                   for locs in index.tables.values() for loc in locs)


def test_sessions_carry_a_default_timeout():
    """requests has no default timeout; without one a catalog that accepts the
    connection and never answers holds a listing thread forever."""
    seen = {}

    class _Session:
        def request(self, method, url, **kw):
            seen.update(kw)
            return "ok"

        def get(self, url, **kw):
            return self.request("GET", url, **kw)
    s = _Session()
    cb._bound_session(s, 7)
    assert s.get("https://x") == "ok"
    assert seen["timeout"] == 7
    s.request("GET", "https://x", timeout=2)
    assert seen["timeout"] == 2
    assert cb.REST_TIMEOUT_SECONDS <= 10


# ── secrets ──────────────────────────────────────────────────────────────────

def test_the_secret_reaches_the_catalog_and_nothing_else(_clean, monkeypatch, caplog):
    monkeypatch.setattr(reg, "secret_for", lambda entry: SECRET)
    _install(_rest())
    cb.get_catalog_reader("lake").list_namespaces()
    assert _clean[0].props["credential"] == SECRET
    assert SECRET not in repr(cb.get_catalog_reader("lake"))
    assert SECRET not in caplog.text


def test_errors_are_sanitised_before_they_are_logged_or_returned(monkeypatch, caplog):
    monkeypatch.setattr(reg, "secret_for", lambda entry: SECRET)

    def _leaky(props):
        raise RuntimeError(
            f"401 for https://user:pw@catalog.example.com/v1/oauth/tokens?token=abc123 "
            f"credential={props['credential']} Authorization: Bearer eyJraw.tok.sig")
    monkeypatch.setattr(cb, "_new_rest_catalog", _leaky)
    _install(_rest())
    with pytest.raises(Exception) as exc:
        cb.get_catalog_reader("lake").list_namespaces()
    text = str(exc.value) + caplog.text
    for leaked in (SECRET, "super-secret-value", "user:pw@", "abc123", "eyJraw.tok.sig"):
        assert leaked not in text, leaked


def test_sanitise_error_keeps_the_useful_part():
    msg = cb.sanitize_error("Unauthorized for https://a:b@h.example.com/v1/config", ["zzz"])
    assert "h.example.com" in msg and "a:b@" not in msg


# ── config validation ────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,config", [
    ("iceberg_rest", {"uri": "https://c.example.com/api/catalog"}),
    ("iceberg_rest", {"uri": "https://s3tables.us-east-1.amazonaws.com/iceberg",
                      "warehouse": "arn:aws:s3tables:us-east-1:123456789012:bucket/b",
                      "sigv4": True, "signing_name": "s3tables", "signing_region": "us-east-1"}),
    ("iceberg_rest", {"uri": "http://polaris.datapond.svc.cluster.local:8181/api/catalog"}),
    ("iceberg_rest", {"uri": "http://polaris.datapond.svc:8181/api/catalog"}),
    ("iceberg_rest", {"uri": "http://localhost:8181/api/catalog"}),
    ("glue", {"region": "us-east-1", "catalog_id": "123456789012", "via_rest": True}),
    ("glue", {"region": "us-east-1", "warehouse": "s3://b/warehouse"}),
    ("polaris", {"warehouse": "lake"}),
])
def test_valid_configs_pass(kind, config):
    assert reg.validate_config(kind, config) == config


@pytest.mark.parametrize("kind,config,why", [
    ("iceberg_rest", {}, "uri"),
    ("iceberg_rest", {"uri": "http://catalog.example.com/api"}, "https"),
    ("iceberg_rest", {"uri": "https://u:p@catalog.example.com/api"}, "credentials"),
    ("iceberg_rest", {"uri": "ftp://catalog.example.com"}, "https"),
    ("iceberg_rest", {"uri": "https://c.example.com", "credential": "a:b"}, "credential"),
    ("iceberg_rest", {"uri": "https://c.example.com", "header.Authorization": "x"}, "header"),
    ("iceberg_rest", {"uri": "https://c.example.com", "sigv4": True}, "signing"),
    ("iceberg_rest", {"uri": "https://c.example.com", "sigv4": "yes"}, "sigv4"),
    ("glue", {"via_rest": True, "region": "us-east-1"}, "catalog_id"),
    ("glue", {"region": "not a region"}, "region"),
    ("glue", {"catalog_id": "12"}, "catalog_id"),
    ("polaris", {"uri": "https://x", "token": "t"}, "token"),
    ("nope", {}, "kind"),
])
def test_invalid_configs_are_refused(kind, config, why):
    with pytest.raises(ValueError) as exc:
        reg.validate_config(kind, config)
    assert why in str(exc.value)
