"""Catalog actions: what tables exist and how they relate.

Declaration and implementation live together. `actions.py` owns the vocabulary — the
Action type, resolution, validation, the gate — and assembles what these modules
declare.
"""
import re
from typing import Callable, Dict, Optional

from app.api.catalog_backend import get_catalog_reader
from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class TableRef(_Strict):
    # `namespace`, not `schema`: the latter shadows a BaseModel attribute, which
    # quietly drops it from the generated JSON Schema's `required` list — and the
    # product's own API already calls these namespaces.
    namespace: str
    table: str


class TableSearch(_Strict):
    query: str


class RelationshipQuery(_Strict):
    table: Optional[str] = None
    days: int = 30


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


ACTIONS = (
    Action("catalog.describe_table", "Describe table",
           "Columns, types, and relationships for one table.",
           ("/catalog", "/query"), "catalog:read", ActionKind.READ, TableRef,
           capability="catalog"),
    Action("catalog.find_tables", "Find tables",
           "Find tables by name or namespace. Pass plain words only — there is no query syntax, no operators, no field: prefixes.",
           ("*",), "catalog:read", ActionKind.READ, TableSearch,
           capability="catalog"),
    Action("catalog.explain_relationships", "Explain relationships",
           "How tables are joined, from observed query history and column naming.",
           ("/catalog",), "catalog:read", ActionKind.READ, RelationshipQuery,
           capability="catalog"),
)

EXECUTORS: Dict[str, Callable] = {
    "catalog.describe_table": describe_table,
    "catalog.find_tables": find_tables,
    "catalog.explain_relationships": explain_relationships,
}

RESOLVERS: Dict[str, Callable] = {
    "catalog.describe_table": _r("app.api.catalog_backend", "get_catalog_reader"),
    "catalog.find_tables": _r("app.api.catalog_backend", "get_catalog_reader"),
    "catalog.explain_relationships": _r("app.api.catalog_graph", "build_graph"),
}

PREVIEWERS: Dict[str, Callable] = {}
