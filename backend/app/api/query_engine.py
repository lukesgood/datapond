"""Query-engine abstraction: one engine, Trino, on every profile (2.4).

Isolates dialect, execution and error mapping so queries.py / ai_sql.py / rls stay
engine-agnostic. The AWS Single-Node Reference runs the same in-cluster Trino over the
Glue catalog; the Athena engine that used to serve it was removed in 2.4 (design:
docs/superpowers/specs/2026-11-09-trino-unified-engine-and-connectors-design.md).
`QUERY_ENGINE` in a release's env is no longer read."""
import re


# What a chart can do with a column, from the type the engine reports. Coarse on
# purpose: the console needs "can this be an axis, a measure, a time line", not the
# engine's full type system.
_QUANTITATIVE = re.compile(r"^(tinyint|smallint|integer|int|bigint|real|double|float|decimal)\b")
_TEMPORAL = re.compile(r"^(date|time|timestamp|interval)\b")
_TEXT = re.compile(r"^(varchar|char|string|json|uuid|ipaddress)\b")


def column_kind(engine_type) -> str:
    """quantitative | temporal | boolean | text | other | unknown."""
    t = str(engine_type or "").strip().lower()
    if not t:
        return "unknown"
    if _QUANTITATIVE.match(t):
        return "quantitative"
    if _TEMPORAL.match(t):
        return "temporal"
    if t == "boolean":
        return "boolean"
    if _TEXT.match(t):
        return "text"
    return "other"


def _kinds(description) -> list:
    return [column_kind(d[1] if len(d) > 1 else None) for d in (description or [])]


def _clean_trino_msg(msg: str) -> str:
    if 'message="' in msg:
        try:
            return msg.split('message="')[1].split('"')[0]
        except Exception:
            return msg
    return msg


class TrinoEngine:
    default_catalog = "iceberg"
    default_schema = "default"
    rls_dialect = "trino"
    ai_dialect_prompt = "The query engine is Trino. Tables are Apache Iceberg format."
    ai_table_prefix = "iceberg"

    def execute(self, sql, user):
        from app.api.queries import get_trino_connection
        conn = get_trino_connection(user)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        # Read by the caller after execute(); the return shape stays (rows, cols) for
        # every other caller of execute().
        self.column_types = _kinds(cur.description)
        cur.close(); conn.close()
        return rows, cols

    def map_error(self, exc):
        msg = str(exc)
        clean = _clean_trino_msg(msg)
        low = msg.lower()
        if "SYNTAX_ERROR" in msg or "syntax error" in low:
            return "error", f"Syntax error: {clean}", 400
        if "TABLE_NOT_FOUND" in msg or ("table" in low and "not found" in low):
            return "error", f"Table not found: {clean}", 400
        if "SCHEMA_NOT_FOUND" in msg or ("schema" in low and "not found" in low):
            return "error", f"Schema not found: {clean}", 400
        if "CATALOG_NOT_FOUND" in msg:
            return "error", f"Catalog not found: {clean}", 400
        if "PERMISSION_DENIED" in msg:
            return "error", f"Permission denied: {clean}", 403
        if "timeout" in low:
            return "timeout", "Query timed out (30s limit). Try adding a LIMIT clause.", 504
        if "connect" in low or "connection" in low:
            return "error", "Cannot connect to query engine. Check if Trino is running.", 400
        return "error", clean if clean != msg else f"Query failed: {clean}", 400


def get_engine() -> TrinoEngine:
    return TrinoEngine()


def explain_statement(sql: str, kind: str = "IO, FORMAT JSON", user: str = "datapond"):
    """Run `EXPLAIN (<kind>) sql` and return (ok, error, text).

    EXPLAIN analyses the statement against the live catalog and scans no data, so it
    both validates and describes. `kind` is interpolated by the caller, never by a
    user — keep it to the fixed set in app/api/plan_review.py's callers.

    Never raises: a reviewer that throws would hide the query behind its own outage.
    """
    engine = get_engine()
    try:
        rows, _cols = engine.execute(f"EXPLAIN ({kind}) {sql}", user)
        text = "\n".join(str(r[0]) for r in rows if r and r[0] is not None)
        return True, None, text
    except Exception as e:
        try:
            _status, detail, _code = engine.map_error(e)
        except Exception:
            detail = str(e)[:300]
        return False, detail, ""


def validate_statement(sql: str, user: str = "datapond"):
    """Check `sql` against the live catalog without running it.

    `EXPLAIN (TYPE VALIDATE)` parses and analyses the statement — resolving every
    table and column — and scans no data, so it is the cheapest way to tell a
    plausible-looking generated query from a runnable one.

    Returns (ok, error_message). Never raises: a validator that fails closed on its
    own outage would block queries that are perfectly fine.
    """
    engine = get_engine()
    try:
        engine.execute(f"EXPLAIN (TYPE VALIDATE) {sql}", user)
        return True, None
    except Exception as e:
        try:
            _status, detail, _code = engine.map_error(e)
        except Exception:
            detail = str(e)[:300]
        return False, detail
