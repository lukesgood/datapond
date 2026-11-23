"""Approved concept bindings as /ai/sql prompt context and as read actions.

A question that says "플래티넘 고객의 지난달 주문" names two concepts. Their approved
bindings tell the model which columns those words are (주문 → orders.id, 고객 →
customers.id and orders.customer_id) and which condition a segment is (플래티넘 고객 →
customers WHERE tier = 'platinum'), instead of leaving it to guess from column names.

What goes in the prompt is reported as `concepts_provided` — given, not used: nothing
here can tell whether the model followed it. Matching is a substring test on the
concept's name and terms, so Korean particles ("고객의", "주문은") do not matter; it is
reproducible and cannot be argued with. Only bindings on catalogs the caller may use
are given, and the SQL still runs through RLS and masking.
"""
from typing import Dict, List, Tuple

RULE = ("When the question uses one of these business words, use the bound columns: join "
        "tables on keys of the same concept, and apply a segment's condition exactly.")


def _terms(c: dict) -> List[str]:
    return [t for t in [c["name"], *(c.get("terms") or [])] if t and len(t.strip()) >= 2]


def _score(c: dict, q: str) -> int:
    """Length of the longest of the concept's words found in the question; 0 if none."""
    return max((len(t) for t in _terms(c) if t.lower() in q), default=0)


def binding_text(b: dict) -> str:
    """One binding as the prompt and the answer chips show it."""
    where = f"{b['catalog']}.{b['namespace']}.{b['table']}"
    if b["role"] == "filter":
        return f"{where} WHERE {b['filter_sql']}"
    return f"{where}.{b['column']}"


def matched(concepts: List[dict], question: str, limit: int = 8) -> List[dict]:
    """Concepts the question names that have at least one approved binding, longest
    match first ("플래티넘 고객" before "고객")."""
    q = (question or "").lower()
    hits = [(s, c) for c in concepts if c.get("bindings") and (s := _score(c, q))]
    return [c for _, c in sorted(hits, key=lambda x: (-x[0], x[1]["name"]))[:limit]]


def concept_lines(concepts: List[dict], question: str) -> Tuple[str, List[dict]]:
    """(prompt block, provided) for the concepts the question names. `provided` is
    [{name, uses: [binding text, ...]}], for the answer and the audit row."""
    hits = matched(concepts, question)
    if not hits:
        return "", []
    lines, provided = [], []
    for c in hits:
        keys = [binding_text(b) for b in c["bindings"] if b["role"] == "key"]
        attrs = [binding_text(b) for b in c["bindings"] if b["role"] == "attribute"]
        segs = [binding_text(b) for b in c["bindings"] if b["role"] == "filter"]
        parts = []
        if keys:
            parts.append("key " + ", ".join(keys))
        if attrs:
            parts.append("attribute " + ", ".join(attrs))
        if segs:
            parts.append("segment " + "; ".join(segs))
        aka = [t for t in c.get("terms") or [] if t != c["name"]]
        lines.append(f"- {c['name']}" + (f" ({', '.join(aka)})" if aka else "") + ": " + " | ".join(parts))
        provided.append({"name": c["name"], "uses": keys + attrs + segs})
    return "Business concepts in the question (approved bindings):\n" + "\n".join(lines) + "\n" + RULE, provided


async def for_caller(user: dict) -> List[dict]:
    """Concepts with their approved bindings on catalogs this caller may use. Empty when
    the ontology capability is off or the tables are missing."""
    from app import catalog_access
    from app.api.ontology import load_concepts, ontology_enabled
    from app.semantic import concept_store
    if not ontology_enabled():
        return []
    from app.api.connectors import get_db_pool
    pool = await get_db_pool()
    access = await catalog_access.for_caller(user)
    by: Dict[str, List[dict]] = {}
    for b in await concept_store.list_bindings(pool, ("approved",)):
        if access.allows_sql_catalog(b["catalog"]):
            by.setdefault(b["concept"], []).append(
                {k: b[k] for k in ("catalog", "namespace", "table", "column", "role", "filter_sql")})
    return [dict(c, bindings=by.get(c["name"], [])) for c in await load_concepts(pool)]


async def list_visible(user: dict) -> List[dict]:
    """concept.list: every concept, its words and how many approved bindings it has."""
    return [{"name": c["name"], "terms": c["terms"], "parent": c["parent"], "pii": c["pii"],
             "bindings": len(c["bindings"])} for c in await for_caller(user)]


async def describe_visible(user: dict, name: str) -> dict:
    """concept.describe: one concept with its approved bindings and its narrower concepts."""
    from fastapi import HTTPException
    concepts = await for_caller(user)
    c = next((x for x in concepts if x["name"] == name), None)
    if c is None:
        c = next((x for x in concepts if name.lower() in [t.lower() for t in _terms(x)]), None)
    if c is None:
        raise HTTPException(404, f"Unknown concept {name!r}. concept_list shows the names.")
    return {"name": c["name"], "description": c.get("description"), "terms": c["terms"],
            "parent": c["parent"], "pii": c["pii"],
            "narrower": [x["name"] for x in concepts if x["parent"] == c["name"]],
            "bindings": [dict(b, text=binding_text(b)) for b in c["bindings"]]}


def for_table(concepts: List[dict], catalog: str, namespace: str, table: str) -> Dict[str, List[dict]]:
    """{column: [{concept, role, filter_sql}]} for one table, for the Catalog's column chips."""
    out: Dict[str, List[dict]] = {}
    key = (catalog.lower(), namespace.lower(), table.lower())
    for c in concepts:
        for b in c["bindings"]:
            if (b["catalog"], b["namespace"], b["table"]) == key:
                out.setdefault(b["column"], []).append(
                    {"concept": c["name"], "role": b["role"], "filter_sql": b["filter_sql"], "pii": c["pii"]})
    return out



def join_conflicts(sql: str, concepts: List[dict], dialect: str = "trino",
                   default_catalog: str = "") -> List[str]:
    """Joins in `sql` that equate key columns of two different concepts.

    Live 2026-11-23: asked for "활성 고객별 반품 건수", the model joined customers.id =
    product_returns.product_id — a 고객 key to a 상품 key — with both bindings in its
    prompt. The statement was valid, so the catalog check passed it. A key column bound
    to 고객 equated with one bound only to 상품 is never right; this finds those. A
    concept counts as its ancestors too, so a narrower concept's key may meet its
    parent's. Columns with no key binding are not judged.
    """
    from app.api.catalog_graph import extract_joins
    parent = {c["name"]: c.get("parent") for c in concepts}

    def lineage(name: str) -> set:
        out, cur = set(), name
        while cur and cur not in out:
            out.add(cur)
            cur = parent.get(cur)
        return out

    keys: Dict[Tuple[str, str], set] = {}
    for c in concepts:
        for b in c.get("bindings") or []:
            if b["role"] == "key":
                k = (f"{b['catalog']}.{b['namespace']}.{b['table']}".lower(), b["column"].lower())
                keys.setdefault(k, set()).update(lineage(c["name"]))
    if not keys:
        return []
    out = []
    for j in extract_joins(sql, dialect, default_catalog or None):
        a = keys.get((j["left_table"], j["left_column"].lower()))
        b = keys.get((j["right_table"], j["right_column"].lower()))
        if a and b and not (a & b):
            short = lambda t: t.split(".")[-1]
            out.append(f"{short(j['left_table'])}.{j['left_column']} is {'/'.join(sorted(a))} but "
                       f"{short(j['right_table'])}.{j['right_column']} is {'/'.join(sorted(b))}")
    return out
