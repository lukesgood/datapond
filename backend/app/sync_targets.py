"""One lake table per source table.

A connection's sync jobs each land in a lake table: catalog.namespace.table, where the
namespace and table come from the job (app/connectors/trino_sync.target_ref) and the
catalog from its target_catalog. Two jobs of one connection that land in the same
namespace.table are the same source table synced twice — `customers` and
`public.customers` both land in default.customers. In one catalog they overwrite each
other; in two they are independent copies that drift apart, each with its own grants.

To read a table from a second catalog, export a mirror (app/catalog_export.py). To change
where it lands, move it. This module only answers which jobs collide; the routes refuse
a new collision (409) and Overview lists the ones that already exist.
"""
from typing import Dict, Iterable, List, Optional, Tuple

from app.connectors import trino_sync


def default_target(source_table: str) -> str:
    """The target a job stores when nobody names one: `datapond.default.<table>`. A
    Trino source lists its tables with their schema (`public.orders`); the schema is
    not part of the target — the writer drops it (trino_sync.target_ref) — so it is not
    stored either. Older rows say `datapond.default.public.orders`; both read the same."""
    return f"datapond.default.{str(source_table or '').split('.')[-1]}"


def lake_table(source_table: str, target_table: Optional[str]) -> Tuple[str, str]:
    """(namespace, table) a job lands in, whatever the catalog."""
    ref = trino_sync.target_ref(source_table, target_table, None)
    return (ref.namespace or "default", ref.table)


def conflict(jobs: Iterable[dict], source_table: str, target_table: Optional[str]) -> Optional[dict]:
    """The other job of the same connection that lands in the same namespace.table, if
    any. `jobs` are that connection's rows (source_table, target_table, target_catalog)."""
    mine = lake_table(source_table, target_table)
    for j in jobs:
        if j["source_table"] == source_table:
            continue
        if lake_table(j["source_table"], j.get("target_table")) == mine:
            return j
    return None


def duplicates(jobs: Iterable[dict]) -> List[dict]:
    """Groups of enabled jobs that land in one namespace.table of one connection.

    Each group: connection_id, namespace, table, and its jobs (source_table, catalog,
    last_run_at), oldest run first."""
    groups: Dict[Tuple[str, str, str], List[dict]] = {}
    for j in jobs:
        if not j.get("enabled", True):
            continue
        ns, table = lake_table(j["source_table"], j.get("target_table"))
        groups.setdefault((str(j["connection_id"]), ns, table), []).append(j)
    out = []
    for (conn, ns, table), rows in groups.items():
        if len(rows) < 2:
            continue
        rows = sorted(rows, key=lambda r: (r.get("last_run_at") is None, r.get("last_run_at") or 0))
        out.append({"connection_id": conn, "namespace": ns, "table": table,
                    "jobs": [{"source_table": r["source_table"], "catalog": r.get("target_catalog") or None,
                              "last_run_at": r.get("last_run_at")} for r in rows]})
    return out
