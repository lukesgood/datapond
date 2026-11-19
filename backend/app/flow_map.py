"""The data flow map: what feeds which table, drawn only from things that run.

Three kinds of edge, each read from where it already lives:
  sync       a source's enabled sync job → the table it writes (connector_sync_jobs)
  stream     a RisingWave Iceberg sink → the table it writes (rw_catalog definitions)
  transform  every table a transform's SQL reads → the table it writes

Tables are keyed `namespace.table` (lower case, catalog dropped): the map is about
how data moves between tables, and the console's tables live in one lakehouse
catalog. A transform reading `iceberg.raw.orders` and a sync writing
`datapond.raw.orders` therefore meet at `raw.orders`.

Pure: the route gathers rows, this shapes them. No I/O here.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

STALE_AFTER = timedelta(hours=24)

_IDENT = re.compile(r"[^a-zA-Z0-9_]")


def _norm(part: str) -> str:
    return _IDENT.sub("_", str(part or "")).lower()


def table_key(name: str, default_ns: str = "default") -> Optional[str]:
    """`namespace.table` for "catalog.ns.table", "ns.table" or "table"."""
    parts = [p.strip('"') for p in str(name or "").split(".") if p.strip('"')]
    if not parts:
        return None
    if len(parts) == 1:
        return f"{_norm(default_ns)}.{_norm(parts[0])}"
    return f"{_norm(parts[-2])}.{_norm(parts[-1])}"


def sync_target_key(source_table: str, target_table: str) -> Optional[str]:
    """Where a sync job writes, read the way the writer reads it
    (connectors/trino_sync.target_ref): the namespace from the target, the table's own
    name from the source (schema stripped)."""
    src = str(source_table or "").split(".")[-1]
    target = str(target_table or "")
    for suffix in (f".{source_table}", f".{src}"):
        if source_table and target.endswith(suffix):
            target = target[: -len(suffix)]
            break
    else:
        target = target.rsplit(".", 1)[0] if "." in target else ""
    ns = target.split(".")[-1] if target else "default"
    return f"{_norm(ns or 'default')}.{_norm(src)}" if src else None


_SINK_DB = re.compile(r"database\.name\s*=\s*'((?:[^']|'')*)'", re.I)
_SINK_TABLE = re.compile(r"table\.name\s*=\s*'((?:[^']|'')*)'", re.I)
_SINK_FROM = re.compile(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)


def sink_target(definition: str) -> Optional[str]:
    """`namespace.table` an Iceberg sink writes, from its DDL."""
    db = _SINK_DB.search(definition or "")
    tb = _SINK_TABLE.search(definition or "")
    if not (db and tb):
        return None
    unq = lambda m: m.group(1).replace("''", "'")
    return f"{_norm(unq(db))}.{_norm(unq(tb))}"


def _parse_ts(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _state(status: Optional[str], at: Optional[datetime], now: datetime, live: bool = False) -> str:
    """ok | failed | running | stale | never | live"""
    if live:
        return "live"
    s = (status or "").lower()
    if s in ("failed", "error", "upstream_failed"):
        return "failed"
    if s in ("running", "queued", "pending"):
        return "running"
    if at is None:
        return "never"
    if now - at > STALE_AFTER:
        return "stale"
    return "ok"


def build_flow(
    connections: Iterable[Dict[str, Any]],
    jobs: Iterable[Dict[str, Any]],
    transforms: Iterable[Dict[str, Any]],
    sinks: Iterable[Dict[str, Any]] = (),
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Nodes and edges for the map.

    connections: {id, name, connector_type}
    jobs:        {connection_id, source_table, target_table, last_run_status, last_run_at}
    transforms:  {id, name, dag_id, schedule, target_namespace, target_table, reads: [names],
                  last_run_state, last_run_at}
    sinks:       {name, definition, source_connector}  (RisingWave Iceberg sinks)
    """
    now = now or datetime.now(timezone.utc)
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    def table(key: str) -> Dict[str, Any]:
        if key not in nodes:
            ns, name = key.split(".", 1)
            nodes[key] = {"id": key, "kind": "table", "namespace": ns, "name": name,
                          "state": "external", "at": None, "written_by": None}
        return nodes[key]

    by_conn = {str(c["id"]): c for c in connections}
    for j in jobs:
        conn = by_conn.get(str(j.get("connection_id")))
        if not conn:
            continue  # a source the caller may not see
        key = sync_target_key(j.get("source_table", ""), j.get("target_table", ""))
        if not key:
            continue
        src_id = f"source:{conn['id']}"
        nodes.setdefault(src_id, {"id": src_id, "kind": "source", "name": conn.get("name"),
                                  "connector_type": conn.get("connector_type"), "ref": str(conn["id"])})
        at = _parse_ts(j.get("last_run_at"))
        t = table(key)
        t.update(state=_state(j.get("last_run_status"), at, now),
                 at=at.isoformat() if at else None,
                 written_by={"kind": "sync", "ref": str(conn["id"]), "name": conn.get("name")})
        edges.append({"from": src_id, "to": key, "kind": "sync", "via": conn.get("name")})

    for s in sinks:
        key = sink_target(s.get("definition", ""))
        if not key:
            continue
        name = str(s.get("name", ""))
        stream = name[:-5] if name.endswith("_sink") else name
        src_id = f"stream:{stream}"
        nodes.setdefault(src_id, {"id": src_id, "kind": "stream", "name": stream,
                                  "connector_type": s.get("source_connector")})
        t = table(key)
        t.update(state="live", written_by={"kind": "stream", "ref": stream, "name": stream})
        edges.append({"from": src_id, "to": key, "kind": "stream", "via": stream})

    for tr in transforms:
        out = table_key(f"{tr.get('target_namespace')}.{tr.get('target_table')}")
        if not out:
            continue
        at = _parse_ts(tr.get("last_run_at"))
        t = table(out)
        t.update(state=_state(tr.get("last_run_state"), at, now),
                 at=at.isoformat() if at else None,
                 written_by={"kind": "transform", "ref": str(tr.get("id")), "name": tr.get("name"),
                             "dag_id": tr.get("dag_id"), "schedule": tr.get("schedule")})
        if not tr.get("schedule") and t["state"] == "stale":
            t["state"] = "ok"  # run by hand: age is not a fault
        for r in sorted(set(filter(None, (table_key(x) for x in tr.get("reads") or [])))):
            if r == out:
                continue
            table(r)
            edges.append({"from": r, "to": out, "kind": "transform", "via": tr.get("name"),
                          "ref": str(tr.get("id"))})

    _layout(nodes, edges)
    _propagate(nodes, edges)
    return {"nodes": sorted(nodes.values(), key=lambda n: (n["column"], n.get("namespace") or "", n["name"] or "")),
            "edges": edges, "generated_at": now.isoformat()}


def _layout(nodes: Dict[str, Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
    """Column = longest path from a source. Sources and streams are column 0; a table
    nothing in DataPond writes sits in column 1 beside the synced ones."""
    preds: Dict[str, List[str]] = {k: [] for k in nodes}
    for e in edges:
        preds.setdefault(e["to"], []).append(e["from"])
    memo: Dict[str, int] = {}

    def depth(k: str, seen: frozenset) -> int:
        if k in memo:
            return memo[k]
        n = nodes[k]
        if n["kind"] != "table":
            memo[k] = 0
            return 0
        ps = [p for p in preds.get(k, []) if p not in seen]
        d = 1 if not ps else max(depth(p, seen | {k}) for p in ps) + (0 if all(nodes[p]["kind"] != "table" for p in ps) else 1)
        memo[k] = max(d, 1)
        return memo[k]

    for k in nodes:
        nodes[k]["column"] = depth(k, frozenset())


def _propagate(nodes: Dict[str, Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
    """A table whose input failed or went stale is marked `stale_input`, transitively."""
    preds: Dict[str, List[str]] = {}
    for e in edges:
        preds.setdefault(e["to"], []).append(e["from"])
    order = sorted((n for n in nodes.values() if n["kind"] == "table"), key=lambda n: n["column"])
    for n in order:
        bad = [p for p in preds.get(n["id"], [])
               if nodes[p]["kind"] == "table"
               and (nodes[p]["state"] in ("failed", "stale") or nodes[p].get("stale_input"))]
        n["stale_input"] = sorted(bad) or None
