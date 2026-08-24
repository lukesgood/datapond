"""Join relationships mined from query history.

`docs/ONTOLOGY_FEASIBILITY_REPORT.md` found the relationship layer to be the weakest
result across every domain tested — LLMs infer relations badly. Query history avoids
the problem rather than trying to solve it: a join that appears in `query_history`
is not an inferred relationship, it is a recorded one. Frequency is real evidence of
which paths through the catalog people actually use.

Pure functions over SQL strings — no database access, no engine calls.
"""
import logging
from typing import Iterable, List

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)


def _table_name(t: exp.Table) -> str:
    parts = [p for p in (t.db, t.name) if p]
    return ".".join(parts).lower()


def _alias_map(stmt) -> dict:
    """alias (and bare name) -> qualified table name, for resolving column prefixes."""
    out = {}
    for t in stmt.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            continue
        full = _table_name(t)
        if not full:
            continue
        if t.alias:
            out[t.alias.lower()] = full
        out.setdefault(t.name.lower(), full)
        out.setdefault(full, full)
    return out


def _resolve(col: exp.Column, aliases: dict):
    """(qualified table, column) for a column reference, or None when unqualified."""
    prefix = (col.table or "").lower()
    if not prefix:
        return None
    table = aliases.get(prefix)
    if not table:
        return None
    return table, col.name.lower()


def _equalities(stmt) -> Iterable[exp.EQ]:
    """Equality predicates that can express a join: ON clauses and WHERE clauses.

    WHERE is included because `FROM a, b WHERE a.id = b.id` is the same relationship
    written the older way, and it still shows up in hand-written history.
    """
    for join in stmt.find_all(exp.Join):
        on = join.args.get("on")
        if on is not None:
            yield from on.find_all(exp.EQ)
    where = stmt.args.get("where") if isinstance(stmt, exp.Select) else None
    if where is not None:
        yield from where.find_all(exp.EQ)


def extract_joins(sql: str, dialect: str = "trino") -> List[dict]:
    """Table-to-table equalities in `sql`.

    Each entry is ordered so that the same relationship written either way produces
    the same `key` — a join is undirected. Self-joins are dropped: a table related to
    itself is a hierarchy inside one table, not a relationship between two.

    Never raises. History contains whatever people typed, including things that do
    not parse.
    """
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except Exception:
        return []

    seen, out = set(), []
    for stmt in statements:
        aliases = _alias_map(stmt)
        for eq in _equalities(stmt):
            left, right = eq.this, eq.expression
            if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
                continue
            lr, rr = _resolve(left, aliases), _resolve(right, aliases)
            if not lr or not rr:
                continue
            (lt, lc), (rt, rc) = lr, rr
            if lt == rt:
                continue
            # Orient by table name so both spellings collapse to one relationship.
            if lt > rt:
                (lt, lc), (rt, rc) = (rt, rc), (lt, lc)
            key = f"{lt}.{lc}={rt}.{rc}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"left_table": lt, "right_table": rt,
                        "left_column": lc, "right_column": rc, "key": key})
    return out


def _tables_in(sql: str, dialect: str = "trino") -> List[str]:
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except Exception:
        return []
    names = []
    for stmt in statements:
        ctes = {c.alias.lower() for c in stmt.find_all(exp.CTE) if c.alias}
        for t in stmt.find_all(exp.Table):
            if not isinstance(t.this, exp.Identifier):
                continue
            if t.name.lower() in ctes:
                continue
            full = _table_name(t)
            if full and "." in full and full not in names:
                names.append(full)
    return names


def build_graph(statements: Iterable[str], dialect: str = "trino") -> dict:
    """Aggregate a history of statements into {nodes, edges}.

    Node `query_count` is how many statements touched the table; edge `count` is how
    many used that relationship. Both are usage evidence, so the diagram can weight
    the paths people actually take.
    """
    nodes: dict = {}
    edges: dict = {}

    for sql in statements:
        for name in _tables_in(sql, dialect):
            nodes.setdefault(name, 0)
            nodes[name] += 1
        for j in extract_joins(sql, dialect):
            pair = (j["left_table"], j["right_table"])
            e = edges.setdefault(pair, {"count": 0, "joins": {}})
            e["count"] += 1
            ck = (j["left_column"], j["right_column"])
            e["joins"][ck] = e["joins"].get(ck, 0) + 1
            for t in pair:
                nodes.setdefault(t, 0)

    return {
        "nodes": [{"id": name, "query_count": n}
                  for name, n in sorted(nodes.items(), key=lambda kv: (-kv[1], kv[0]))],
        "edges": [{
            "source": src, "target": dst, "count": e["count"],
            "joins": [{"left_column": lc, "right_column": rc, "count": c}
                      for (lc, rc), c in sorted(e["joins"].items(), key=lambda kv: -kv[1])],
        } for (src, dst), e in sorted(edges.items(), key=lambda kv: -kv[1]["count"])],
    }
