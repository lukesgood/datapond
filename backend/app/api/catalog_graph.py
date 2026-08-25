"""Join relationships mined from query history.

`docs/ONTOLOGY_FEASIBILITY_REPORT.md` found the relationship layer to be the weakest
result across every domain tested — LLMs infer relations badly. Query history avoids
the problem rather than trying to solve it: a join that appears in `query_history`
is not an inferred relationship, it is a recorded one. Frequency is real evidence of
which paths through the catalog people actually use.

Pure functions over SQL strings — no database access, no engine calls.
"""
import logging
import re
from typing import Dict, Iterable, List, Optional

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




# ── Candidate relationships from catalog metadata ─────────────────────────────
# History alone leaves a new catalog blank — the person who needs the diagram has no
# query history, and the person who has history already knows the joins. Candidates
# fill day zero. They are guesses from column naming and are labelled as such; an
# observed join always supersedes one.

# A key-ish suffix. `region` matching `region` across two tables is a coincidence;
# `cust_id` matching `cust_id` is a convention.
_KEYISH = re.compile(r"(^|_)(id|key|code|no|num|uuid|sk|fk)$", re.I)

# Names so common that matching them would connect the entire catalog to itself.
_GENERIC = {"id", "name", "status", "type", "value", "date", "code", "key",
            "created_at", "updated_at", "deleted_at", "created", "updated"}

_NUMERIC = ("int", "long", "bigint", "smallint", "tinyint", "decimal", "double",
            "float", "real", "numeric")
_STRINGY = ("varchar", "char", "string", "text", "uuid")


def _type_bucket(t: str) -> str:
    t = (t or "").strip().lower()
    if t.startswith(_NUMERIC):
        return "number"
    if t.startswith(_STRINGY):
        return "string"
    return t or "unknown"


def _bare_table(qualified: str) -> str:
    return qualified.split(".")[-1].lower()


def _singularish(word: str) -> str:
    w = word.lower()
    for suffix in ("ies", "es", "s"):
        if len(w) > 3 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def candidate_joins(schema: Dict[str, List[dict]]) -> List[dict]:
    """Guess relationships from column names and types.

    Two conventions, both deliberately narrow — a wide net here produces a hairball
    that is worse than an empty diagram:
      1. the same key-ish column name on two tables (`cust_id` = `cust_id`)
      2. `<thing>_id` on one table against `id` on a table named after `<thing>`
    """
    out: List[dict] = []
    seen = set()
    names = sorted(schema)

    def _emit(t_a, c_a, t_b, c_b, reason):
        left, lc, right, rc = (t_a, c_a, t_b, c_b) if t_a < t_b else (t_b, c_b, t_a, c_a)
        key = f"{left}.{lc}={right}.{rc}"
        if key in seen:
            return
        seen.add(key)
        out.append({
            "source": left, "target": right, "count": 0, "evidence": "candidate",
            "reason": reason,
            "joins": [{"left_column": lc, "right_column": rc, "count": 0}],
        })

    for i, ta in enumerate(names):
        for tb in names[i + 1:]:
            cols_a = {c["name"].lower(): _type_bucket(c.get("type", "")) for c in schema[ta]}
            cols_b = {c["name"].lower(): _type_bucket(c.get("type", "")) for c in schema[tb]}

            for col, type_a in cols_a.items():
                if col in _GENERIC or not _KEYISH.search(col):
                    continue
                if cols_b.get(col) == type_a:
                    _emit(ta, col, tb, col, "같은 이름의 키 컬럼")

            # <thing>_id against the id of a table named <thing>
            for a, b in ((ta, tb), (tb, ta)):
                a_cols = cols_a if a == ta else cols_b
                b_cols = cols_b if a == ta else cols_a
                if "id" not in b_cols:
                    continue
                stem = _singularish(_bare_table(b))
                for col, type_a in a_cols.items():
                    if not col.endswith("_id") or col == "id":
                        continue
                    prefix = col[:-3]
                    if type_a != b_cols["id"]:
                        continue
                    if stem.startswith(prefix) or prefix.startswith(stem):
                        _emit(a, col, b, "id", f"{prefix}_id → {_bare_table(b)}.id 명명 규칙")
    return out

def build_graph(statements: Iterable[str], dialect: str = "trino",
                schema: Optional[Dict[str, List[dict]]] = None) -> dict:
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

    observed = [{
        "source": src, "target": dst, "count": e["count"], "evidence": "observed",
        "joins": [{"left_column": lc, "right_column": rc, "count": c}
                  for (lc, rc), c in sorted(e["joins"].items(), key=lambda kv: -kv[1])],
    } for (src, dst), e in sorted(edges.items(), key=lambda kv: -kv[1]["count"])]

    # A guess about a pair people have actually joined adds nothing but noise.
    observed_pairs = {(e["source"], e["target"]) for e in observed}
    candidates = [c for c in candidate_joins(schema or {})
                  if (c["source"], c["target"]) not in observed_pairs]
    for c in candidates:
        for t in (c["source"], c["target"]):
            nodes.setdefault(t, 0)

    schema = schema or {}
    return {
        "nodes": [{
            "id": name,
            "query_count": n,
            # Carried so selecting a table can show its shape without another
            # round-trip; empty when the catalog was not read.
            "columns": [{"name": c.get("name", ""), "type": c.get("type", "")}
                        for c in schema.get(name, [])],
        } for name, n in sorted(nodes.items(), key=lambda kv: (-kv[1], kv[0]))],
        "edges": [dict(e, join_sql=_join_sql(e)) for e in observed + candidates],
    }


def _join_sql(edge: dict) -> str:
    """A statement to start from, rebuilt from the parsed keys.

    Never echoed from history. A stored statement can carry literals in its WHERE
    clause — an id, an account number — that the person reading a diagram has no
    reason to see, and reconstructing gives the useful half without the risk.
    """
    src, dst = edge["source"], edge["target"]
    joins = edge.get("joins") or []
    if not joins:
        return ""
    on = " AND ".join(f"a.{j['left_column']} = b.{j['right_column']}" for j in joins[:1])
    return (f"SELECT *\nFROM {src} a\nJOIN {dst} b ON {on}\nLIMIT 100")
