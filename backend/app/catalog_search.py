"""Find data by a column name or a business word (Data Map step 2).

The Catalog's search box matched table names only, and so did the agent tool
(`catalog.find_tables`). Two questions it could not answer:

- "Which tables have an email column?" — a column name.
- "Where is 고객?" — a business word. The tables are called customers, orders and
  support_tickets; none of them says 고객. The concept 고객 does, through its name and
  aliases, and its approved bindings say which columns hold it.

So a word is matched against four things, and each hit says why it is there:
table names, column names, concepts (name and aliases) and metrics (name, label,
synonyms). A matched concept brings the columns bound to it (key and attribute roles)
and its segments (filter role); a matched metric brings its base table.

Governance: only catalogs the caller may use are indexed for them — a binding or a
metric over a hidden catalog is dropped with it. Names are not values, so masked and
PII columns are found like any other; nothing here reads a row.

`search()` is pure (index, concepts, bindings, metrics in; groups out) so it is tested
without an engine. `column_index()` reads `information_schema.columns` once per
catalog through the engine and is cached for a few minutes.
"""
import logging
import re
import threading
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

INDEX_TTL_S = 300
MAX_TABLES = 20
MAX_COLUMNS = 50
_HANGUL = re.compile(r"[가-힣]")

# (catalog, namespace, table) → [{"name", "type"}]
Index = Dict[Tuple[str, str, str], List[dict]]


def tokens(q: str) -> List[str]:
    """Words of the query, lowercased. A Korean word counts from one syllable (고객 is
    two, 키 is one); a Latin word from two letters, so "a" does not match everything."""
    out = []
    for t in re.split(r"[\s,]+", (q or "").strip().lower()):
        t = t.strip("\"'`.")
        if not t:
            continue
        if _HANGUL.search(t) or len(t) >= 2:
            out.append(t)
    return list(dict.fromkeys(out))[:6]


def _hit(word: str, text: str) -> bool:
    return bool(text) and word in text.lower()


def _concept_hits(words: List[str], concepts: Iterable[dict]) -> Dict[str, List[str]]:
    """{concept name: [words it matched]} — by name or alias."""
    out: Dict[str, List[str]] = {}
    for c in concepts:
        names = [c["name"]] + list(c.get("terms") or [])
        got = [w for w in words if any(_hit(w, n) for n in names)]
        if got:
            out[c["name"]] = got
    return out


def search(q: str, index: Index, concepts: Iterable[dict] = (), bindings: Iterable[dict] = (),
           metrics: Iterable[dict] = (), allowed: Callable[[str], bool] = lambda _c: True) -> dict:
    """Groups for the query `q`:

    - tables: [{catalog, namespace, table, score, why: [...], columns: [names]}]
    - columns: [{catalog, namespace, table, column, type, why}]
    - concepts: [{name, description, pii, terms, parent, matched, keys, attributes, segments}]
    - segments: [{concept, catalog, namespace, table, column, filter_sql}]
    - metrics: [{name, label, base_table, matched}]

    `allowed(catalog)` says whether the caller may use a catalog as SQL names it;
    `index` is assumed already narrowed to those catalogs, bindings and metrics are
    narrowed here.
    """
    words = tokens(q)
    empty = {"query": q, "words": words, "tables": [], "columns": [], "concepts": [],
             "segments": [], "metrics": []}
    if not words:
        return empty
    concepts = list(concepts)
    by_name = {c["name"]: c for c in concepts}
    matched_concepts = _concept_hits(words, concepts)

    # table key → {"words": set, "why": [...], "columns": {name: why}}
    tables: Dict[Tuple[str, str, str], dict] = {}
    columns: Dict[Tuple[str, str, str, str], dict] = {}

    def table(key):
        return tables.setdefault(key, {"words": set(), "why": [], "columns": {}})

    def add_column(key, col, typ, why, ws):
        ck = key + (col.lower(),)
        if ck not in columns:
            columns[ck] = {"catalog": key[0], "namespace": key[1], "table": key[2],
                           "column": col, "type": typ, "why": why}
        t = table(key)
        t["words"] |= set(ws)
        t["columns"].setdefault(col, why)

    types = {k: {c["name"].lower(): c.get("type") for c in cols} for k, cols in index.items()}
    for key, cols in index.items():
        cat, ns, tbl = key
        name_words = [w for w in words if _hit(w, tbl) or _hit(w, ns)]
        if name_words:
            t = table(key)
            t["words"] |= set(name_words)
            t["why"].append("name")
        for c in cols:
            ws = [w for w in words if _hit(w, c["name"])]
            if ws:
                add_column(key, c["name"], c.get("type"), "name", ws)

    concept_out = {n: {"name": n, "description": by_name[n].get("description"),
                       "pii": bool(by_name[n].get("pii")), "terms": list(by_name[n].get("terms") or []),
                       "parent": by_name[n].get("parent"), "matched": ws,
                       "keys": [], "attributes": [], "segments": 0}
                   for n, ws in matched_concepts.items()}
    segments = []
    for b in bindings:
        n = b.get("concept")
        if n not in concept_out or not allowed(b["catalog"]):
            continue
        key = (b["catalog"].lower(), b["namespace"].lower(), b["table"].lower())
        ref = f"{key[1]}.{key[2]}.{b['column']}"
        if b.get("role") == "filter":
            concept_out[n]["segments"] += 1
            segments.append({"concept": n, "catalog": key[0], "namespace": key[1],
                             "table": key[2], "column": b["column"],
                             "filter_sql": b.get("filter_sql")})
            t = table(key)
            t["words"] |= set(matched_concepts[n])
            if f"segment {n}" not in t["why"]:
                t["why"].append(f"segment {n}")
            continue
        concept_out[n]["keys" if b.get("role") == "key" else "attributes"].append(ref)
        add_column(key, b["column"], types.get(key, {}).get(b["column"].lower()),
                   f"concept {n}", matched_concepts[n])
        why = f"concept {n}"
        if why not in tables[key]["why"]:
            tables[key]["why"].append(why)

    metric_out = []
    for m in metrics:
        names = [m.get("name") or "", m.get("label") or ""] + list(m.get("synonyms") or [])
        ws = [w for w in words if any(_hit(w, x) for x in names)]
        base = (m.get("base_table") or "").lower()
        parts = base.split(".")
        if not ws or len(parts) != 3 or not allowed(parts[0]):
            continue
        metric_out.append({"name": m["name"], "label": m.get("label"),
                           "base_table": base, "matched": ws})
        key = tuple(parts)
        if key in index or key in tables:
            t = table(key)
            t["words"] |= set(ws)
            t["why"].append(f"metric {m['name']}")

    ranked = sorted(
        ({"catalog": k[0], "namespace": k[1], "table": k[2],
          "score": len(v["words"]) * 10 + len(v["columns"]) + (5 if "name" in v["why"] else 0),
          "why": v["why"] + ([f"{len(v['columns'])} column{'s' if len(v['columns']) != 1 else ''}"]
                             if v["columns"] else []),
          "columns": sorted(v["columns"])}
         for k, v in tables.items()),
        key=lambda t: (-t["score"], t["catalog"], t["namespace"], t["table"]))
    col_list = sorted(columns.values(),
                      key=lambda c: (c["why"] == "name", c["catalog"], c["namespace"],
                                     c["table"], c["column"]))
    return {"query": q, "words": words,
            "tables": ranked[:MAX_TABLES], "columns": col_list[:MAX_COLUMNS],
            "column_total": len(col_list), "table_total": len(ranked),
            "concepts": sorted(concept_out.values(), key=lambda c: c["name"]),
            "segments": segments, "metrics": metric_out}


# ── The column index ────────────────────────────────────────────────────────────

_lock = threading.Lock()
_cache: Dict[str, Tuple[float, Index]] = {}


def _read_catalog(engine_catalog: str) -> Index:
    """Every column of one catalog in one statement."""
    from app.api.catalog_backend import SOURCE_SYSTEM_SCHEMAS, safe_identifier
    from app.api.trino_util import trino_conn
    safe_identifier(engine_catalog)
    skip = ", ".join(f"'{s}'" for s in sorted(SOURCE_SYSTEM_SCHEMAS))
    cur = trino_conn(catalog=engine_catalog, timeout=30).cursor()
    cur.execute(
        f"SELECT table_schema, table_name, column_name, data_type "
        f"FROM {engine_catalog}.information_schema.columns "
        f"WHERE table_schema NOT IN ({skip}) ORDER BY table_schema, table_name, ordinal_position")
    out: Index = {}
    for ns, tbl, col, typ in cur.fetchall():
        out.setdefault((engine_catalog.lower(), ns.lower(), tbl.lower()), []).append(
            {"name": col, "type": typ})
    return out


def column_index(engine_catalogs: Iterable[str], read: Callable[[str], Index] = _read_catalog,
                 now: Callable[[], float] = time.monotonic) -> Index:
    """The merged index of `engine_catalogs`, each cached for INDEX_TTL_S. A catalog
    that cannot be read is skipped (and not cached), so one source being down does not
    empty the search."""
    out: Index = {}
    for cat in engine_catalogs:
        key = cat.lower()
        with _lock:
            hit = _cache.get(key)
        if hit and now() - hit[0] < INDEX_TTL_S:
            out.update(hit[1])
            continue
        try:
            part = read(cat)
        except Exception as e:
            logger.warning("[catalog_search] columns of %s unreadable: %s", cat, e)
            if hit:                       # stale beats nothing
                out.update(hit[1])
            continue
        with _lock:
            _cache[key] = (now(), part)
        out.update(part)
    return out


def reset_cache() -> None:
    with _lock:
        _cache.clear()
