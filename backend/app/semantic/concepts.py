"""Concept bindings: which column a business concept is.

The concept store (app/api/ontology.py) holds words — "고객", its aliases "customer",
"회원" — and nothing about where they live. A binding ties a concept to one column of
one table: a key (customers.id and orders.customer_id are both 고객), an attribute, or a
segment defined by a filter over that table (VIP 고객 = customers.tier = 'VIP').

An administrator approves every binding, as with join paths (app/api/semantic.py). This
module suggests what to approve, from evidence that already exists, and never from a
model: relation extraction was the weakest step in every domain of the feasibility
tests (docs/ONTOLOGY_FEASIBILITY_REPORT.md).

  naming   a column whose name is a concept term (customer_id → customer), or a table's
           `id` when the table's name is the term (customers.id → customer)
  history  the other side of a join people ran, or an approved join, whose first side
           is already an approved key of the concept

Column comments and an OpenMetadata glossary are later inputs; the table accepts their
source names already.

Pure: callers pass rows in, this returns suggestions. No I/O.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

ROLES = ("key", "attribute", "filter")
STATUSES = ("proposed", "approved", "rejected", "retired")
SOURCES = ("naming", "comment", "history", "manual", "openmetadata", "feedback")

Ref = Tuple[str, str, str, str]          # catalog, namespace, table, column (lower case)


def norm(s: str) -> str:
    """Lower case letters, digits and Hangul only: `Customer_ID` → `customerid`."""
    return "".join(re.findall(r"[a-z0-9가-힣]+", (s or "").lower()))


def singular(s: str) -> str:
    """Enough English plural folding for table names: customers, categories, addresses,
    boxes, branches, warehouses."""
    if s.endswith("ies") and len(s) > 4:
        return s[:-3] + "y"
    if s.endswith(("sses", "xes", "zes", "ches", "shes")) and len(s) > 4:
        return s[:-2]
    if s.endswith("s") and not s.endswith("ss") and len(s) > 3:
        return s[:-1]
    return s


def split_table(qualified: str) -> Optional[Tuple[str, str, str]]:
    parts = (qualified or "").lower().split(".")
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else None


def _terms(c: dict) -> List[str]:
    return [t for t in {norm(x) for x in [c["name"], *(c.get("terms") or [])]} if t]


def _ref(b: dict) -> Ref:
    return (b["catalog"].lower(), b["namespace"].lower(), b["table"].lower(), b["column"].lower())


def propose(concepts: Iterable[dict], schema: Dict[str, List[dict]],
            bindings: Iterable[dict], edges: Iterable[dict]) -> List[dict]:
    """Suggested bindings, each {concept, catalog, namespace, table, column, role, source,
    evidence}, sorted for display.

    `concepts`: {name, terms}. `schema`: {catalog.namespace.table: [{name}]}.
    `bindings`: every stored binding {concept, catalog, namespace, table, column, role,
    status} — any status blocks the same suggestion, so a rejected one is not offered
    again. `edges`: joins {source, target, joins: [{left_column, right_column, count}],
    evidence} where source/target are catalog.namespace.table; "observed" and "approved"
    edges count, a naming guess does not.
    """
    concepts = list(concepts)
    bindings = list(bindings)
    taken = {(b["concept"], *_ref(b)) for b in bindings}
    out: Dict[Tuple[str, str, str, str, str], dict] = {}

    def add(concept: str, ref: Ref, source: str, evidence: str, role: Optional[str] = None) -> None:
        k = (concept, *ref)
        if k in taken or k in out:
            return
        cat, ns, table, col = ref
        out[k] = {"concept": concept, "catalog": cat, "namespace": ns, "table": table,
                  "column": col, "role": role or ("key" if _keyish(col) else "attribute"),
                  "source": source, "evidence": evidence}

    # naming
    by_term: Dict[str, List[str]] = {}
    for c in concepts:
        for t in _terms(c):
            by_term.setdefault(t, []).append(c["name"])
    for qualified, cols in schema.items():
        parts = split_table(qualified)
        if not parts:
            continue
        cat, ns, table = parts
        table_term = singular(norm(table))
        for col in cols:
            name = str(col.get("name") or "").lower()
            n = norm(name)
            if n == "id":
                for concept in by_term.get(table_term, []) + by_term.get(norm(table), []):
                    add(concept, (cat, ns, table, name), "naming",
                        f"{table}.id is the key of a table named for this concept")
                continue
            stem = n[:-2] if n.endswith("id") and len(n) > 2 else n
            for concept in by_term.get(stem, []) + (by_term.get(singular(stem), []) if singular(stem) != stem else []):
                add(concept, (cat, ns, table, name), "naming",
                    f"column name {name} matches a term of this concept")

    # history: carry an approved key across a join to its other side
    keys: Dict[Tuple[str, str, str, str], List[str]] = {}
    for b in bindings:
        if b.get("status") == "approved" and b.get("role") == "key":
            keys.setdefault(_ref(b), []).append(b["concept"])
    for e in edges:
        if e.get("evidence") not in ("observed", "approved", "fk"):
            continue
        src, dst = split_table(e.get("source", "")), split_table(e.get("target", ""))
        if not src or not dst:
            continue
        for j in (e.get("joins") or []) + (e.get("fk_joins") or []):
            lc, rc = str(j.get("left_column", "")).lower(), str(j.get("right_column", "")).lower()
            if not lc or not rc:
                continue
            how = ("approved join" if e["evidence"] == "approved"
                   else "foreign key in the source" if e["evidence"] == "fk"
                   else f"joined in {j.get('count') or e.get('count') or 1} queries")
            for a, b, ac, bc in ((src, dst, lc, rc), (dst, src, rc, lc)):
                for concept in keys.get((*a, ac), []):
                    add(concept, (*b, bc), "history",
                        f"{how} to {a[2]}.{ac}, already a key of this concept", role="key")

    return sorted(out.values(), key=lambda p: (p["concept"], p["catalog"], p["namespace"],
                                               p["table"], p["column"]))


def _keyish(col: str) -> bool:
    n = col.lower()
    return n == "id" or n.endswith("_id")


def approved_join_edges(joins: Iterable[dict], engine_name) -> List[dict]:
    """semantic_joins rows ({catalog, from_table, to_table, on_columns}) as edges in the
    relationship-graph shape. `engine_name` maps a registry name to the engine's."""
    out = []
    for j in joins:
        cat = (engine_name(j["catalog"]) or j["catalog"]).lower()
        out.append({"source": f"{cat}.{j['from_table']}".lower(),
                    "target": f"{cat}.{j['to_table']}".lower(), "evidence": "approved",
                    "joins": [{"left_column": a, "right_column": b} for a, b in j["on_columns"]]})
    return out


def pii_gaps(concepts: Iterable[dict], bindings: Iterable[dict], masks: Iterable,
             engine_name) -> List[dict]:
    """Columns approved for a PII concept that no enabled column mask covers.

    A suggestion for Governance, never an action: a concept says what a column IS, a
    mask says what a role may SEE, and only an administrator decides the second (Access
    policies). A segment's condition is not a column holding the concept, so filters are
    left out. A key column is listed with `key: true` — masking it breaks joins on it
    unless the mask keeps equal values equal (hash). `masks` are app/rls MaskPolicy rows
    (catalog, schema, table, column, enabled, role_map); `engine_name` maps either catalog
    name to the engine's, so a mask written against `AwsDataCatalog` covers `iceberg`. A
    mask that applies to no role masks nothing (Access policies says so) and covers nothing.
    """
    pii = {c["name"] for c in concepts if c.get("pii")}
    covered = {((engine_name(m.catalog) or m.catalog).lower(), m.schema.lower(),
                m.table.lower(), m.column.lower())
               for m in masks if getattr(m, "enabled", True)
               and any(not exempt for exempt in (getattr(m, "role_map", None) or {}).values())}
    seen, out = set(), []
    for b in bindings:
        if b.get("status") != "approved" or b["concept"] not in pii or b["role"] == "filter":
            continue
        ref = _ref(b)
        if ref in covered or (b["concept"], ref) in seen:
            continue
        seen.add((b["concept"], ref))
        out.append({"concept": b["concept"], "catalog": ref[0], "namespace": ref[1],
                    "table": ref[2], "column": ref[3], "key": b["role"] == "key"})
    return sorted(out, key=lambda g: (g["concept"], g["catalog"], g["namespace"], g["table"], g["column"]))
