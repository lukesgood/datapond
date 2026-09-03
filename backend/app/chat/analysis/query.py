"""Query actions: turn a question into SQL, explain a plan, run a statement.

Declaration and implementation live together. `actions.py` owns the vocabulary — the
Action type, resolution, validation, the gate — and assembles what these modules
declare.
"""
import logging
from typing import Callable, Dict

from app.api.plan_review import parse_io_plan
from app.api.query_engine import explain_statement
from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r

logger = logging.getLogger(__name__)


class SqlText(_Strict):
    sql: str


class NaturalQuestion(_Strict):
    question: str


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


ACTIONS = (
    # Offered everywhere, like catalog.find_tables. These were scoped to /query, so
    # the assistant had no SQL tool on any other page — and the panel is on every
    # page. "What does the data say" does not depend on which screen you are looking
    # at, and the permission gate is what decides who may ask.
    Action("query.generate_sql", "Generate SQL",
           "Turn a question into SQL, checked against the catalog. Does not run it.",
           ("*",), "ai:generate", ActionKind.READ, NaturalQuestion,
           capability="query"),
    Action("query.explain_plan", "Explain the plan",
           "What a statement will read, and anything worth knowing before running it.",
           ("*",), "query:run", ActionKind.READ, SqlText,
           capability="query"),
    # Classed CREATE, not READ: Athena bills by bytes scanned, and a query the user
    # did not write can read the wrong table. It gets an approval step.
    Action("query.run", "Run query",
           "Execute a statement and return rows.",
           ("*",), "query:run", ActionKind.CREATE, SqlText,
           capability="query"),
)

EXECUTORS: Dict[str, Callable] = {
    "query.generate_sql": generate_sql,
    "query.explain_plan": explain_plan,
    "query.run": run_query,
}

RESOLVERS: Dict[str, Callable] = {
    "query.generate_sql": _r("app.api.ai_sql", "generate_sql"),
    "query.explain_plan": _r("app.api.plan_review", "review"),
    "query.run": _r("app.api.queries", "execute_query"),
}

# Only non-read actions need one; the gate skips previewing a read.
PREVIEWERS: Dict[str, Callable] = {"query.run": preview_query_run}
