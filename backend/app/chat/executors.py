"""What each registered action actually does.

Thin adapters onto code the product already has, deliberately: a permission check, an
RLS rewrite, or a catalog quirk must not behave one way through a button and another
through the assistant. Where an executor reimplements rather than reuses, the two
paths will drift, and the assistant will be the one that is wrong.

Kept separate from `actions.py` (the vocabulary) and `gate.py` (the control) so
neither depends on every subsystem an action happens to touch.
"""
import logging
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


async def find_tables(params: dict, user: dict) -> dict:
    """Substring match over qualified names. Deliberately not fuzzy: a diagram of
    near-misses is worse than an empty result the user can refine."""
    needle = params["query"].strip().lower()
    reader = get_catalog_reader()
    hits: List[str] = []
    for namespace in reader.list_namespaces():
        try:
            tables = reader.list_tables(namespace)
        except Exception:
            continue
        for table in tables:
            qualified = f"{namespace}.{table}"
            if needle in qualified.lower():
                hits.append(qualified)
    return {"tables": hits, "query": params["query"]}


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


async def explain_plan(params: dict, user: dict) -> dict:
    from app.api.plan_review import review
    ok, error, io_text = explain_statement(params["sql"], "TYPE IO, FORMAT JSON")
    if not ok:
        return {"validated": False, "error": error, "accessed": [], "problems": []}
    out = review(io_text, None)
    out["validated"] = True
    return out


async def preview_query_run(params: dict, user: dict) -> dict:
    """What this statement will read, before the user approves running it."""
    ok, error, io_text = explain_statement(params["sql"], "TYPE IO, FORMAT JSON")
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


async def save_dashboard(params: dict, user: dict) -> dict:
    from app.api.dashboards import DashboardCreate, create_dashboard
    from app.database.connection import SessionLocal
    db = SessionLocal()
    try:
        created = await create_dashboard(
            DashboardCreate(name=params["name"], query=params["sql"],
                            chart_type=params.get("chart_type", "table")),
            db=db, user=user)
    finally:
        db.close()
    return {"id": str(getattr(created, "id", "")), "name": params["name"]}


# ── knowledge ─────────────────────────────────────────────────────────────────

async def _existing_collections(user: dict) -> List[str]:
    from app.api.ai_vectors import list_collections
    collections = await list_collections(user=user)
    return [c.get("name") for c in (collections or []) if isinstance(c, dict)]


async def search_knowledge(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import SearchRequest, search
    result = await search(SearchRequest(query=params["query"],
                                        collection=params.get("collection")), user=user)
    return {"matches": result}


async def answer_with_citations(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import RagRequest, rag_answer
    result = await rag_answer(RagRequest(question=params["query"],
                                         collection=params.get("collection")), user=user)
    return {"answer": result}


async def preview_create_collection(params: dict, user: dict) -> dict:
    try:
        existing = await _existing_collections(user)
    except Exception as e:
        logger.warning(f"[chat] could not list collections for preview: {e}")
        existing = []
    return {"name": params["name"], "description": params.get("description"),
            "already_exists": params["name"] in existing}


async def create_collection(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import CollectionCreate, create_collection as _create
    created = await _create(CollectionCreate(name=params["name"],
                                             description=params.get("description")),
                            user=user)
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
    from app.api.ai_backends import get_spend
    return {"spend": await get_spend(user=user)}


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

# Only non-read actions need one; the gate skips previewing a read.
PREVIEWERS: Dict[str, Callable] = {
    "query.run": preview_query_run,
    "dashboard.save": preview_dashboard_save,
    "knowledge.create_collection": preview_create_collection,
}
