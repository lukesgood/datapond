"""OpenMetadata glossary → concepts, and glossary tags on columns → proposed bindings.

OpenMetadata is an optional add-on, never the required path: a team that curates its
business words in an OpenMetadata glossary brings them in here instead of typing them
again, and a team without it loses nothing. Two inputs:

- the glossary itself, pulled from the add-on's API when it runs on this deployment,
  or uploaded as the JSON the API returns or the CSV its Glossary › Export writes;
- glossary terms tagged on table columns (pull only) — each becomes a *proposed*
  binding with source `openmetadata`. Nothing is approved here: OpenMetadata says a
  column was tagged, an administrator says it is right (Metrics › Concepts).

Concepts already in DataPond keep their parent, PII flag and description; an import only
adds the words they lack. A binding that already exists in any status — including one
rejected or retired — is not proposed again.
"""
import csv
import io
import logging
import os
import re
from typing import Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MAX_PAGES = 50          # 50 × 100 tables, 50 × 200 terms: a glossary, not a warehouse
SOURCE = "openmetadata"


def enabled() -> bool:
    return os.getenv("FEATURE_OPENMETADATA", "").strip().lower() in ("1", "true", "yes", "on")


def _fqn_parts(fqn: str) -> List[str]:
    """`Glossary."a.b".c` → ["Glossary", "a.b", "c"]: OpenMetadata quotes a name that
    contains a dot."""
    return [p.strip('"') for p in re.findall(r'"[^"]*"|[^.]+', fqn or "")]


def _concept_name(t: dict) -> str:
    return str(t.get("displayName") or t.get("name") or "").strip()


def _synonyms(v) -> List[str]:
    if isinstance(v, str):
        v = v.split(";")
    return [str(s).strip() for s in (v or []) if str(s).strip()]


def _is_pii(t: dict) -> bool:
    tags = t.get("tags") or []
    if isinstance(tags, str):
        tags = [{"tagFQN": x} for x in tags.split(";")]
    return any(str(x.get("tagFQN") or "").strip().lower().startswith("pii.")
               for x in tags if isinstance(x, dict))


def parse_terms(payload) -> List[dict]:
    """Glossary terms from the API's JSON (a list, or {"data": [...]}) or the Export
    CSV text. Each: {name, display, fqn, parent_fqn, description, synonyms, pii}."""
    if isinstance(payload, str):
        rows = list(csv.DictReader(io.StringIO(payload.lstrip("﻿"))))
        out = []
        for r in rows:
            r = {(k or "").strip().rstrip("*").lower(): (v or "").strip() for k, v in r.items()}
            name = r.get("name", "")
            if not name:
                continue
            parent = r.get("parent", "")
            out.append({"name": name, "display": r.get("displayname") or name,
                        "fqn": f"{parent}.{name}" if parent else name,
                        "parent_fqn": parent or None, "description": r.get("description") or None,
                        "synonyms": _synonyms(r.get("synonyms")), "pii": _is_pii(r)})
        return out
    items = payload.get("data", []) if isinstance(payload, dict) else payload
    out = []
    for t in items or []:
        if not isinstance(t, dict) or not (t.get("name") or t.get("displayName")):
            continue
        parent = t.get("parent") or {}
        out.append({"name": str(t.get("name") or _concept_name(t)), "display": _concept_name(t),
                    "fqn": str(t.get("fullyQualifiedName") or t.get("name")),
                    "parent_fqn": (parent.get("fullyQualifiedName") or parent.get("name"))
                    if isinstance(parent, dict) else None,
                    "description": t.get("description") or None,
                    "synonyms": _synonyms(t.get("synonyms")), "pii": _is_pii(t)})
    return out


def to_concepts(terms: List[dict]) -> List[dict]:
    """Concepts in the store's shape: the display name is the concept, the term's own
    name (when it differs) and its synonyms are its words, the parent term is the parent.
    A parent is matched by FQN, or by its last part when the CSV names it short."""
    by_fqn = {t["fqn"].lower(): t["display"] for t in terms}
    by_last = {_fqn_parts(t["fqn"])[-1].lower(): t["display"] for t in terms if t["fqn"]}
    out: Dict[str, dict] = {}
    for t in terms:
        name = t["display"]
        if not name:
            continue
        parent = None
        if t["parent_fqn"]:
            pf = t["parent_fqn"].lower()
            parent = by_fqn.get(pf) or by_last.get(_fqn_parts(t["parent_fqn"])[-1].lower())
        words = [w for w in [t["name"], *t["synonyms"]] if w and w != name]
        c = out.setdefault(name, {"name": name, "description": t["description"],
                                  "parent": parent if parent != name else None,
                                  "pii": t["pii"], "terms": []})
        c["terms"] += [w for w in words if w not in c["terms"]]
    return list(out.values())


def term_index(terms: List[dict]) -> Dict[str, str]:
    """Tag FQN (lowercase) → concept name, for matching column tags."""
    return {t["fqn"].lower(): t["display"] for t in terms if t["fqn"] and t["display"]}


def proposals_from_tables(tables: Iterable[dict], index: Dict[str, str],
                          engine_name: Callable[[str], Optional[str]]) -> List[dict]:
    """Columns tagged with a glossary term → binding proposals. A table FQN is
    service.database.schema.table and the database is the Trino catalog the add-on
    crawled (`datapond-trino.iceberg…`); `engine_name` returns the engine's name for it,
    or None for a database DataPond does not know, whose columns are skipped."""
    out, seen = [], set()
    for tbl in tables:
        parts = _fqn_parts(str(tbl.get("fullyQualifiedName") or ""))
        if len(parts) < 4:
            continue
        catalog = engine_name(parts[-3])
        if not catalog:
            continue
        ns, table = parts[-2].lower(), parts[-1].lower()
        for col in tbl.get("columns") or []:
            for tag in col.get("tags") or []:
                if str(tag.get("source") or "").lower() != "glossary":
                    continue
                concept = index.get(str(tag.get("tagFQN") or "").lower())
                column = str(col.get("name") or "").lower()
                if not concept or not column:
                    continue
                key = (concept, catalog.lower(), ns, table, column)
                if key in seen:
                    continue
                seen.add(key)
                role = "key" if column == "id" or column.endswith("_id") else "attribute"
                out.append({"concept": concept, "catalog": catalog.lower(), "namespace": ns,
                            "table": table, "column": column, "role": role,
                            "evidence": f"tagged {tag.get('tagFQN')} in OpenMetadata"})
    return out


def new_proposals(proposals: List[dict], bindings: Iterable[dict]) -> List[dict]:
    """Proposals with no binding of the same concept, column and role in any status."""
    have = {(b["concept"], b["catalog"].lower(), b["namespace"].lower(), b["table"].lower(),
             b["column"].lower(), b["role"]) for b in bindings}
    return [p for p in proposals if (p["concept"], p["catalog"], p["namespace"], p["table"],
                                     p["column"], p["role"]) not in have]


# ── The add-on's API (only when it runs here) ───────────────────────────────────

async def _pages(client, url: str, headers: dict, params: dict) -> List[dict]:
    out, after = [], None
    for _ in range(_MAX_PAGES):
        q = dict(params, **({"after": after} if after else {}))
        r = await client.get(url, headers=headers, params=q)
        r.raise_for_status()
        body = r.json()
        out += body.get("data") or []
        after = (body.get("paging") or {}).get("after")
        if not after:
            break
    return out


async def pull() -> Tuple[List[dict], List[dict]]:
    """(glossary terms, tables with column tags) from the add-on."""
    import httpx
    from app.api.om_util import OPENMETADATA_URL, om_headers, om_token
    token = await om_token()
    if not token:
        raise RuntimeError("Could not sign in to OpenMetadata.")
    headers = om_headers(token)
    async with httpx.AsyncClient(timeout=20) as c:
        terms = await _pages(c, f"{OPENMETADATA_URL}/api/v1/glossaryTerms", headers,
                             {"fields": "tags,parent", "limit": 200})
        tables = await _pages(c, f"{OPENMETADATA_URL}/api/v1/tables", headers,
                              {"fields": "columns,tags", "limit": 100})
    return terms, tables


# ── Store ────────────────────────────────────────────────────────────────────────

async def save_concepts(pool, concepts: List[dict]) -> dict:
    """Create concepts that do not exist; add missing words to those that do. An existing
    concept's parent, PII flag and description are DataPond's and stay as they are."""
    created, words, kept = [], 0, []
    async with pool.acquire() as c:
        async with c.transaction():
            for item in concepts:
                row = await c.fetchrow(
                    "SELECT id, pii FROM ontology_concepts WHERE name = $1", item["name"])
                if row is None:
                    cid = await c.fetchval(
                        "INSERT INTO ontology_concepts (name, description, parent, pii) "
                        "VALUES ($1, $2, $3, $4) RETURNING id",
                        item["name"], item["description"], item["parent"], item["pii"])
                    created.append(item["name"])
                else:
                    cid = row["id"]
                    if bool(row["pii"]) != bool(item["pii"]):
                        kept.append(item["name"])
                for t in item["terms"]:
                    tag = await c.execute(
                        "INSERT INTO concept_terms (concept_id, term) VALUES ($1, $2) "
                        "ON CONFLICT DO NOTHING", cid, t)
                    words += tag.endswith(" 1")
    return {"created": created, "terms_added": words, "pii_differs": kept}
