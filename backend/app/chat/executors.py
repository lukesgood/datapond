"""What each registered action actually does.

Thin adapters onto code the product already has, deliberately: a permission check, an
RLS rewrite, or a catalog quirk must not behave one way through a button and another
through the assistant. Where an executor reimplements rather than reuses, the two
paths will drift, and the assistant will be the one that is wrong.

Kept separate from `actions.py` (the vocabulary) and `gate.py` (the control) so
neither depends on every subsystem an action happens to touch.
"""
import logging
import re
from typing import Callable, Dict, List

from app.api.catalog_backend import get_catalog_reader
from app.api.plan_review import parse_io_plan
from app.api.query_engine import explain_statement

logger = logging.getLogger(__name__)


# ── catalog ───────────────────────────────────────────────────────────────────

async def describe_table(params: dict, user: dict) -> dict:
    reader = get_catalog_reader()
    columns = reader.get_columns(params["namespace"], params["table"])
    return {
        "table": f"{params['namespace']}.{params['table']}",
        "columns": [{"name": c.get("name"), "type": c.get("type")} for c in columns],
    }


# Tokens shorter than this are dropped: "in", "of", "a" match almost anything, and a
# query made only of them would return the entire catalog.
_MIN_TOKEN = 3
_TOKEN = re.compile(r"[a-z0-9_]+")


async def find_tables(params: dict, user: dict) -> dict:
    """Find tables by any meaningful word in the query, most matches first.

    Not a whole-string substring match. Observed live: asked "what tables are in
    planlab?", the model sent `namespace:planlab` — a query syntax it invented — and a
    substring match found nothing though the namespace has three tables. Models will
    keep inventing; the tool has to survive what they actually send, which is the same
    premise the whole design rests on.

    Still returns nothing when nothing matches: an empty result the user can refine
    beats a list of everything.
    """
    tokens = {t for t in _TOKEN.findall(params["query"].lower()) if len(t) >= _MIN_TOKEN}
    if not tokens:
        return {"tables": [], "query": params["query"]}

    reader = get_catalog_reader()
    scored = []
    for namespace in reader.list_namespaces():
        try:
            tables = reader.list_tables(namespace)
        except Exception:
            continue
        for table in tables:
            qualified = f"{namespace}.{table}"
            hits = sum(1 for t in tokens if t in qualified.lower())
            if hits:
                scored.append((hits, qualified))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return {"tables": [name for _hits, name in scored], "query": params["query"]}


async def explain_relationships(params: dict, user: dict) -> dict:
    from app.api.catalog_graph import build_graph
    from app.api.queries import _catalog_schema_for_graph
    schema = _catalog_schema_for_graph()
    graph = build_graph([], schema=schema)
    edges = graph["edges"]
    if params.get("table"):
        wanted = params["table"].lower()
        edges = [e for e in edges if wanted in (e["source"], e["target"])]
    return {"relationships": edges[:25]}


# ── query ─────────────────────────────────────────────────────────────────────

async def generate_sql(params: dict, user: dict) -> dict:
    from app.api.ai_sql import AskRequest, generate_sql as _generate
    result = await _generate(AskRequest(question=params["question"]), user=user)
    return {"sql": result.sql, "explanation": result.explanation,
            "validated": result.validated, "needs_input": result.needs_input}


def qualify_for_preview(sql: str):
    """(ok, sql, error) — the statement as `execute_query` will actually run it.

    `run_query` below goes through execute_query, which rewrites bare table names
    against the catalog before running them (app/api/table_resolver.py). EXPLAINing the
    raw string instead describes a different statement: `SELECT * FROM orders` fails to
    resolve here and shows the approver no tables and no filters, while approving it
    runs `sales.orders`. The preview is the whole basis on which someone approves, so it
    has to be the same text.

    Failure is reported, not raised: execute_query answers a bad resolution with a 400,
    but this is the content of an approval card and there is no request to fail. Saying
    "could not resolve" is the honest version of the same refusal.
    """
    from app.api.query_engine import get_engine
    from app.api.table_resolver import (TableResolutionError, get_catalog_index,
                                        qualify_tables)
    try:
        return True, qualify_tables(sql, dialect=get_engine().rls_dialect,
                                    load_index=get_catalog_index), None
    except TableResolutionError as e:
        return False, sql, str(e)
    except Exception as e:                      # catalog unreachable, engine unknown
        logger.warning("[chat] preview could not resolve table names: %s", e)
        return False, sql, "Could not resolve table names against the catalog."


async def explain_plan(params: dict, user: dict) -> dict:
    from app.api.plan_review import review
    resolved, sql, resolution_error = qualify_for_preview(params["sql"])
    if not resolved:
        return {"validated": False, "error": resolution_error,
                "accessed": [], "problems": []}
    ok, error, io_text = explain_statement(sql, "TYPE IO, FORMAT JSON")
    if not ok:
        return {"validated": False, "error": error, "accessed": [], "problems": []}
    out = review(io_text, None)
    out["validated"] = True
    return out


async def preview_query_run(params: dict, user: dict) -> dict:
    """What this statement will read, before the user approves running it."""
    resolved, sql, resolution_error = qualify_for_preview(params["sql"])
    if not resolved:
        return {"validated": False, "error": resolution_error, "reads": []}
    ok, error, io_text = explain_statement(sql, "TYPE IO, FORMAT JSON")
    if not ok:
        return {"validated": False, "error": error, "reads": []}
    plan = parse_io_plan(io_text)
    return {
        "validated": True,
        "reads": [f"{t['schema']}.{t['table']}" for t in plan["tables"]],
        "filters": {f"{t['schema']}.{t['table']}":
                    [f"{f['column']} {f['summary']}" for f in t["filters"]]
                    for t in plan["tables"]},
        # Athena bills by bytes scanned and these tables carry no statistics, so an
        # estimate here would be invented. Saying so beats a number.
        "cost_estimate_available": plan["estimates_available"],
    }


async def run_query(params: dict, user: dict) -> dict:
    from app.api.queries import QueryExecuteRequest, execute_query
    from app.database.connection import SessionLocal
    db = SessionLocal()
    try:
        result = await execute_query(
            QueryExecuteRequest(query=params["sql"], save_history=True, origin="ai_sql"),
            db=db, user=user)
    finally:
        db.close()
    return {"columns": result.columns, "rows": result.rows[:50],
            "row_count": result.row_count, "truncated": result.truncated}


# ── dashboards ────────────────────────────────────────────────────────────────

async def preview_dashboard_save(params: dict, user: dict) -> dict:
    return {"name": params["name"], "chart_type": params.get("chart_type", "table"),
            "sql": params["sql"]}


def build_dashboard_create(params: dict):
    """The schema is `query_text` and a ChartConfig object, not `query` and a string."""
    from app.schemas.dashboard import ChartConfig, DashboardCreate
    return DashboardCreate(
        name=params["name"],
        query_text=params["sql"],
        chart_config=ChartConfig(chartType=params.get("chart_type") or "table"),
    )


async def save_dashboard(params: dict, user: dict) -> dict:
    from app.api.dashboards import create_dashboard
    from app.database.connection import SessionLocal
    db = SessionLocal()
    try:
        created = await create_dashboard(build_dashboard_create(params), db=db, user=user)
    finally:
        db.close()
    return {"id": str(getattr(created, "id", "")), "name": params["name"]}


# ── knowledge ─────────────────────────────────────────────────────────────────

async def _existing_collections(user: dict) -> List[str]:
    from app.api.ai_vectors import list_collections
    collections = await list_collections(user=user)
    return [c.get("name") for c in (collections or []) if isinstance(c, dict)]


def build_search_request(params: dict):
    from app.api.ai_vectors import SearchRequest
    return SearchRequest(collection=params["collection"], query=params["query"])


async def search_knowledge(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import search
    return {"matches": await search(build_search_request(params), user=user)}


def build_rag_request(params: dict):
    from app.api.ai_vectors import RagRequest
    # `question`, not `query` — the two request models do not use the same name.
    return RagRequest(collection=params["collection"], question=params["query"])


async def answer_with_citations(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import rag
    return {"answer": await rag(build_rag_request(params), user=user)}


async def preview_create_collection(params: dict, user: dict) -> dict:
    try:
        existing = await _existing_collections(user)
    except Exception as e:
        logger.warning(f"[chat] could not list collections for preview: {e}")
        existing = []
    return {"name": params["name"], "description": params.get("description"),
            "already_exists": params["name"] in existing}


def build_collection_create(params: dict):
    from app.api.ai_vectors import CollectionCreate
    return CollectionCreate(name=params["name"], description=params.get("description"))


async def create_collection(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import create_collection as _create
    created = await _create(build_collection_create(params), user=user)
    return {"name": params["name"], "created": bool(created)}


# ── governance and spend ──────────────────────────────────────────────────────

async def explain_policy(params: dict, user: dict) -> dict:
    from app.rls import loader as rls_loader
    policies = await rls_loader.load_policies()
    masks = await rls_loader.load_masks()
    if params.get("table"):
        wanted = params["table"].lower()
        policies = [p for p in policies if wanted in f"{p.schema}.{p.table}".lower()]
        masks = [m for m in masks if wanted in f"{m.schema}.{m.table}".lower()]
    return {
        "row_filters": [{"table": f"{p.schema}.{p.table}", "filter": p.filter_expression,
                         "roles": sorted(p.role_map)} for p in policies[:25]],
        "column_masks": [{"table": f"{m.schema}.{m.table}", "column": m.column,
                          "type": m.masking_type} for m in masks[:25]],
    }


async def summarize_spend(params: dict, user: dict) -> dict:
    from app.api.ai_backends import spend_summary
    return {"spend": await spend_summary()}


EXECUTORS: Dict[str, Callable] = {
    "catalog.describe_table": describe_table,
    "catalog.find_tables": find_tables,
    "catalog.explain_relationships": explain_relationships,
    "query.generate_sql": generate_sql,
    "query.explain_plan": explain_plan,
    "query.run": run_query,
    "dashboard.save": save_dashboard,
    "knowledge.search": search_knowledge,
    "knowledge.answer_with_citations": answer_with_citations,
    "knowledge.create_collection": create_collection,
    "governance.explain_policy": explain_policy,
    "spend.summarize": summarize_spend,
}

# What each executor reaches for, resolved on demand.
#
# `test_every_executor_resolves_its_target_function` calls each of these, so a renamed
# or moved function fails a test instead of a user's request. Four of these were wrong
# when first written — `rag_answer` for `rag`, `get_spend` for `spend_summary`, plus
# two request models with different field names — and every one of them would have
# surfaced in production, through the assistant, mid-conversation.
def _r(module: str, name: str):
    def _resolve():
        import importlib
        return getattr(importlib.import_module(module), name)
    return _resolve


RESOLVERS: Dict[str, Callable] = {
    "catalog.describe_table": _r("app.api.catalog_backend", "get_catalog_reader"),
    "catalog.find_tables": _r("app.api.catalog_backend", "get_catalog_reader"),
    "catalog.explain_relationships": _r("app.api.catalog_graph", "build_graph"),
    "query.generate_sql": _r("app.api.ai_sql", "generate_sql"),
    "query.explain_plan": _r("app.api.plan_review", "review"),
    "query.run": _r("app.api.queries", "execute_query"),
    "dashboard.save": _r("app.api.dashboards", "create_dashboard"),
    "knowledge.search": _r("app.api.ai_vectors", "search"),
    "knowledge.answer_with_citations": _r("app.api.ai_vectors", "rag"),
    "knowledge.create_collection": _r("app.api.ai_vectors", "create_collection"),
    "governance.explain_policy": _r("app.rls.loader", "load_policies"),
    "spend.summarize": _r("app.api.ai_backends", "spend_summary"),
}

# Only non-read actions need one; the gate skips previewing a read.
PREVIEWERS: Dict[str, Callable] = {
    "query.run": preview_query_run,
    "dashboard.save": preview_dashboard_save,
    "knowledge.create_collection": preview_create_collection,
}
