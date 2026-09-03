"""Executors are thin adapters onto code the product already has.

The value here is that they reuse the paths the UI uses, so a permission check, an
RLS rewrite, or a catalog quirk cannot behave one way through a button and another
through the assistant.
"""
import asyncio

import pytest

from app.chat import executors
from app.chat.analysis import catalog, knowledge, query


def _run(c):
    return asyncio.run(c) if asyncio.iscoroutine(c) else c


USER = {"id": "u1", "username": "ada", "role": "admin"}


def test_every_registered_action_has_an_executor():
    """A registry entry with nothing behind it is a promise the panel cannot keep."""
    from app.chat.actions import REGISTRY
    missing = [a for a in REGISTRY if a not in executors.EXECUTORS]
    assert not missing, f"no executor for: {missing}"


def test_every_non_read_action_has_a_previewer():
    from app.chat.actions import REGISTRY, ActionKind
    missing = [a for a, action in REGISTRY.items()
               if action.kind is not ActionKind.READ and a not in executors.PREVIEWERS]
    assert not missing, f"no previewer for: {missing}"


def test_describe_table_reads_through_the_catalog_reader(monkeypatch):
    class _Reader:
        def get_columns(self, ns, table):
            return [{"name": "id", "type": "int"}, {"name": "amt", "type": "double"}]

    monkeypatch.setattr(catalog, "get_catalog_reader", lambda: _Reader())
    out = _run(executors.EXECUTORS["catalog.describe_table"](
        {"namespace": "sales", "table": "orders"}, USER))
    assert out["table"] == "sales.orders"
    assert [c["name"] for c in out["columns"]] == ["id", "amt"]


def test_describe_table_reports_a_missing_table_as_a_result_not_a_crash(monkeypatch):
    class _Reader:
        def get_columns(self, ns, table):
            raise RuntimeError("NoSuchTable")

    monkeypatch.setattr(catalog, "get_catalog_reader", lambda: _Reader())
    with pytest.raises(Exception):
        _run(executors.EXECUTORS["catalog.describe_table"](
            {"namespace": "sales", "table": "nope"}, USER))


def test_find_tables_matches_on_name_and_namespace(monkeypatch):
    class _Reader:
        def list_namespaces(self):
            return ["sales", "ops"]
        def list_tables(self, ns):
            return {"sales": ["orders", "customers"], "ops": ["orders_archive"]}[ns]

    monkeypatch.setattr(catalog, "get_catalog_reader", lambda: _Reader())
    out = _run(executors.EXECUTORS["catalog.find_tables"]({"query": "order"}, USER))
    assert set(out["tables"]) == {"sales.orders", "ops.orders_archive"}


def test_find_tables_returns_nothing_rather_than_everything_for_no_match(monkeypatch):
    class _Reader:
        def list_namespaces(self):
            return ["sales"]
        def list_tables(self, ns):
            return ["orders"]

    monkeypatch.setattr(catalog, "get_catalog_reader", lambda: _Reader())
    assert _run(executors.EXECUTORS["catalog.find_tables"](
        {"query": "zzzz"}, USER))["tables"] == []


# ── the preview is what the user approves ─────────────────────────────────────

def test_running_a_query_previews_what_it_will_read(monkeypatch):
    monkeypatch.setattr(query, "explain_statement",
                        lambda sql, kind="TYPE IO, FORMAT JSON": (
                            True, None,
                            '{"inputTableColumnInfos":[{"table":{"schemaTable":'
                            '{"schema":"sales","table":"orders"}},"constraint":'
                            '{"columnConstraints":[]},"estimate":{"outputRowCount":"NaN"}}]}'))
    preview = _run(executors.PREVIEWERS["query.run"]({"sql": "SELECT 1"}, USER))
    assert preview["reads"] == ["sales.orders"]
    assert preview["validated"] is True


def test_an_invalid_query_previews_as_invalid_rather_than_raising(monkeypatch):
    """The card should say the statement will not run, not blow up before showing."""
    monkeypatch.setattr(query, "explain_statement",
                        lambda sql, kind="TYPE IO, FORMAT JSON": (
                            False, "COLUMN_NOT_FOUND: nope", ""))
    preview = _run(executors.PREVIEWERS["query.run"]({"sql": "SELECT nope"}, USER))
    assert preview["validated"] is False
    assert "COLUMN_NOT_FOUND" in preview["error"]


def test_creating_a_collection_previews_the_name_and_whether_it_exists(monkeypatch):
    async def _existing(user):
        return ["support"]
    monkeypatch.setattr(knowledge, "_existing_collections", _existing)
    preview = _run(executors.PREVIEWERS["knowledge.create_collection"](
        {"name": "support"}, USER))
    assert preview["name"] == "support"
    assert preview["already_exists"] is True


# ── find_tables must survive what a model actually sends ──────────────────────

class _Catalog:
    def __init__(self, tables):
        self._t = tables
    def list_namespaces(self):
        return list(self._t)
    def list_tables(self, ns):
        return self._t[ns]


CATALOG = {"planlab": ["customers", "orders", "shipments"],
           "sales": ["orders", "returns"]}


def _find(monkeypatch, query):
    monkeypatch.setattr(catalog, "get_catalog_reader", lambda: _Catalog(CATALOG))
    return _run(executors.EXECUTORS["catalog.find_tables"]({"query": query}, USER))["tables"]


def test_an_invented_search_syntax_still_finds_the_tables(monkeypatch):
    """Observed live: asked "what tables are in planlab?", the model sent
    `namespace:planlab` — a query DSL it made up — and a whole-string substring match
    returned nothing. The tool has to survive what models actually send."""
    assert set(_find(monkeypatch, "namespace:planlab")) == {
        "planlab.customers", "planlab.orders", "planlab.shipments"}


def test_a_plain_name_still_works(monkeypatch):
    assert set(_find(monkeypatch, "planlab")) == {
        "planlab.customers", "planlab.orders", "planlab.shipments"}


def test_a_table_name_matches_across_namespaces(monkeypatch):
    assert set(_find(monkeypatch, "orders")) == {"planlab.orders", "sales.orders"}


def test_a_phrase_matches_on_its_meaningful_words(monkeypatch):
    assert "planlab.orders" in _find(monkeypatch, "the orders table in planlab")


def test_more_specific_matches_rank_first(monkeypatch):
    assert _find(monkeypatch, "planlab orders")[0] == "planlab.orders"


def test_nothing_matching_returns_nothing(monkeypatch):
    assert _find(monkeypatch, "zzzz") == []


def test_a_query_of_only_short_words_returns_nothing_rather_than_everything(monkeypatch):
    """Otherwise "in the" would list the entire catalog."""
    assert _find(monkeypatch, "in the of a") == []


# ── the preview describes the statement that will actually run ──────────────

def test_the_preview_explains_the_same_sql_the_execution_will_run(monkeypatch):
    """`run_query` goes through execute_query, which rewrites bare table names against
    the catalog before running them. The preview used to EXPLAIN the raw string.

    For `SELECT * FROM orders` where `orders` lives in `sales`, that meant the preview
    failed to resolve and showed the approver nothing — no tables read, no filters —
    while approving it ran `sales.orders`. A preview that describes a different
    statement than the one that runs is worse than no preview: it is a wrong answer
    with the authority of a real one.
    """
    seen = []

    monkeypatch.setattr(query, "qualify_for_preview",
                        lambda sql: (True, "sales.orders_qualified", None))

    def fake_explain(sql, mode):
        seen.append(sql)
        return False, "engine unavailable", ""

    monkeypatch.setattr(query, "explain_statement", fake_explain)

    _run(query.preview_query_run({"sql": "SELECT * FROM orders"}, USER))
    _run(query.explain_plan({"sql": "SELECT * FROM orders"}, USER))

    assert seen == ["sales.orders_qualified", "sales.orders_qualified"], (
        "the preview explained the unqualified SQL")


def test_a_preview_that_cannot_resolve_the_tables_says_so_rather_than_guessing(monkeypatch):
    """execute_query fails closed when the catalog cannot resolve a bare name. The
    preview cannot raise — it is what the approval card renders — so it reports
    validated: false with the reason instead of quietly explaining SQL that will be
    rewritten into something else."""
    monkeypatch.setattr(query, "qualify_for_preview",
                        lambda sql: (False, sql, "no table named 'orders'"))

    def must_not_explain(sql, mode):
        raise AssertionError("explained SQL that could not be resolved")

    monkeypatch.setattr(query, "explain_statement", must_not_explain)

    out = _run(query.preview_query_run({"sql": "SELECT * FROM orders"}, USER))
    assert out["validated"] is False
    assert "orders" in out["error"]
    assert out["reads"] == []
