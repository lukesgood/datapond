"""What depends on a table (Data Map step 4: downstream impact in Lineage).

Upstream is the flow map (source → sync → table → transform). Downstream of a table, past
the transforms, are the things that break when it changes: governed metrics built on it,
concepts bound to its columns, saved dashboards whose query reads it, and the people and
agents who queried it (the tool-call log). "What breaks if this changes."

Pure here: matching the four kinds to table ids. The route reads them, each already
limited to what the caller may see.

A table id is `catalog.namespace.table` with the ENGINE's catalog name, lower case. The
tool-call log keeps the name it saw (`AwsDataCatalog.default.orders` before 2.4 and
`iceberg.default.orders` after), so every name is passed through `canonical` first.
"""
from typing import Callable, Dict, Iterable, List, Optional

MAX_TABLES = 12
TOP_CALLERS = 5


def table_id(name: str, canonical: Callable[[str], str]) -> Optional[str]:
    """`AwsDataCatalog.Default.Orders` → `iceberg.default.orders`; None unless three parts."""
    parts = [p.strip().strip('"') for p in (name or "").split(".")]
    if len(parts) != 3 or not all(parts):
        return None
    return f"{canonical(parts[0])}.{parts[1]}.{parts[2]}".lower()


def _empty() -> dict:
    return {"metrics": [], "concepts": [], "dashboards": [],
            "queries": {"calls": 0, "people": 0, "services": 0, "service_calls": 0, "callers": []}}


def impact(tables: Iterable[str], *, metrics: List[dict], bindings: List[dict],
           dashboards: List[dict], calls: List[dict], canonical: Callable[[str], str],
           show_callers: bool) -> Dict[str, dict]:
    """{table id: {metrics, concepts, dashboards, queries}} for each of `tables`.

    metrics:    [{name, label, version, base_table}] — base_table is catalog.ns.table.
    bindings:   approved concept bindings [{concept, catalog, namespace, table, column, role, filter_sql}].
    dashboards: [{id, name, tables: [names the query reads]}].
    calls:      [{table, actor, kind: human|service, n}] — one row per name and caller.
    show_callers: names of who queried are audit data (governance:read); without it the
                  counts stay and the names are left out.
    """
    out: Dict[str, dict] = {}
    for t in tables:
        tid = table_id(t, canonical)
        if tid and tid not in out:
            out[tid] = _empty()

    for m in metrics:
        tid = table_id(m.get("base_table") or "", canonical)
        if tid in out:
            out[tid]["metrics"].append({"name": m["name"], "label": m.get("label") or m["name"],
                                        "version": m.get("version")})

    for b in bindings:
        tid = table_id(f"{b['catalog']}.{b['namespace']}.{b['table']}", canonical)
        if tid in out:
            out[tid]["concepts"].append({"concept": b["concept"], "column": b["column"], "role": b["role"],
                                         "filter_sql": b.get("filter_sql")})

    for d in dashboards:
        read = {table_id(n, canonical) for n in d.get("tables") or []}
        for tid in read & out.keys():
            out[tid]["dashboards"].append({"id": d["id"], "name": d["name"]})

    per: Dict[str, Dict[tuple, int]] = {}
    for c in calls:
        tid = table_id(c.get("table") or "", canonical)
        if tid in out:
            key = (c.get("actor") or "", c.get("kind") or "human")
            per.setdefault(tid, {})
            per[tid][key] = per[tid].get(key, 0) + int(c.get("n") or 0)
    for tid, who in per.items():
        q = out[tid]["queries"]
        q["calls"] = sum(who.values())
        q["people"] = sum(1 for (_, k) in who if k == "human")
        q["services"] = sum(1 for (_, k) in who if k == "service")
        q["service_calls"] = sum(n for (_, k), n in who.items() if k == "service")
        if show_callers:
            ranked = sorted(who.items(), key=lambda kv: (-kv[1], kv[0][0]))[:TOP_CALLERS]
            q["callers"] = [{"name": a or "(unknown)", "kind": k, "calls": n} for (a, k), n in ranked]

    for v in out.values():
        v["metrics"].sort(key=lambda m: m["name"])
        v["concepts"].sort(key=lambda c: (c["concept"], c["column"]))
        v["dashboards"].sort(key=lambda d: d["name"])
    return out
