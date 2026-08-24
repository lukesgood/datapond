"""Read an Athena/Trino execution plan and say what the query will actually do.

The first question about a generated query is not "is it fast" but **"does it read
what I asked for"**. `EXPLAIN (TYPE VALIDATE)` only proves every identifier resolves;
a query can pass it and still read the wrong table. Observed live on 2026-08-24:
asked for a table that does not exist, the model silently substituted a real one and
validation passed. `EXPLAIN (TYPE IO, FORMAT JSON)` names the tables and the
predicates that reached them, which answers the question validation cannot.

Structural signals come second, from `EXPLAIN (TYPE DISTRIBUTED)`. Deliberately no
cost score: on Iceberg tables without analyzed statistics Trino emits `NaN` for every
estimate (verified on the live cluster), so a numeric grade here would be invented.
`estimates_available` says so plainly instead.

Findings are split into `problems` (act on these) and `characteristics` (how it will
run). Anything that would fire on every query is neither — it is state, and belongs
in a field the UI can render quietly. A panel whose warnings are always present
teaches people to stop reading it.

Pure parsing — no I/O, no engine calls. The callers own the round-trips.
"""
import json
import re
from typing import Optional

# Fragment 3 [SOURCE]
_FRAGMENT = re.compile(r"^Fragment (\d+) \[([A-Z_]+)\]", re.M)
# InnerJoin[criteria = ("cust_id" = "cust_id_0"), distribution = REPLICATED]
_JOIN = re.compile(r"\b(\w*Join)\[([^\n]*?)\]\s*$", re.M)
_CRITERIA = re.compile(r"criteria = (.+?)(?:, distribution|$)")
_DISTRIBUTION = re.compile(r"distribution = (\w+)")
# ScanFilterProject[table = awsdatacatalog$iceberg-aws:planlab.orders$data@123, filterPredicate = (...), ...]
_SCAN = re.compile(r"\b(ScanFilterProject|ScanFilter|ScanProject|TableScan)\[([^\n]*?)\]\s*$", re.M)
_SCAN_TABLE = re.compile(r"table = [^:\s]*:([A-Za-z0-9_]+\.[A-Za-z0-9_]+)")
_FILTER_PRED = re.compile(r"filterPredicate = (.+?)(?:, dynamicFilters|, projectLocality|, protectedBarrier|$)")
_SORT = re.compile(r"\b(PartialSort|Sort)\[", re.M)
_BOUNDED_SORT = re.compile(r"\b(TopN|TopNPartial|Limit)\[", re.M)


def parse_io_plan(text: str) -> dict:
    """Tables read, predicates pushed to each, and whether estimates exist.

    Never raises: a plan we cannot read must degrade to "no information", not to an
    error that hides the query behind a broken reviewer.
    """
    out = {"tables": [], "estimates_available": False}
    try:
        doc = json.loads(text)
    except Exception:
        return out
    if not isinstance(doc, dict):
        return out

    def _is_number(v):
        if isinstance(v, (int, float)) and v == v:  # NaN != NaN
            return True
        return isinstance(v, str) and v.strip().lower() not in ("nan", "")  and _floaty(v)

    def _floaty(v):
        try:
            f = float(v)
            return f == f
        except Exception:
            return False

    for info in doc.get("inputTableColumnInfos") or []:
        st = ((info.get("table") or {}).get("schemaTable")) or {}
        filters = []
        for c in ((info.get("constraint") or {}).get("columnConstraints") or []):
            filters.append({
                "column": c.get("columnName", ""),
                "summary": _domain_summary(c.get("domain") or {}),
            })
        out["tables"].append({
            "schema": st.get("schema", ""),
            "table": st.get("table", ""),
            "filters": filters,
        })
        est = info.get("estimate") or {}
        if _is_number(est.get("outputRowCount")) or _is_number(est.get("outputSizeInBytes")):
            out["estimates_available"] = True
    return out


def _domain_summary(domain: dict) -> str:
    """Human-readable form of a pushed-down predicate domain ('= us', 'in 3 values')."""
    ranges = domain.get("ranges") or []
    values = []
    for r in ranges:
        low, high = (r.get("low") or {}), (r.get("high") or {})
        lv, hv = low.get("value"), high.get("value")
        if lv is not None and lv == hv:
            values.append(str(lv))
        elif lv is not None or hv is not None:
            values.append(f"{lv if lv is not None else '*'}..{hv if hv is not None else '*'}")
    if not values:
        return "constrained"
    if len(values) == 1:
        return f"= {values[0]}"
    return "in " + ", ".join(values[:5]) + ("…" if len(values) > 5 else "")


def parse_distributed_plan(text: str) -> dict:
    """Joins, scans, shuffle stages and sort shape from the distributed plan text."""
    out = {"joins": [], "scans": [], "fragments": 0,
           "dynamic_filters": False, "has_sort": False, "sort_is_bounded": False}
    if not text:
        return out

    out["fragments"] = len(_FRAGMENT.findall(text))
    out["has_sort"] = bool(_SORT.search(text))
    out["sort_is_bounded"] = bool(_BOUNDED_SORT.search(text))
    out["dynamic_filters"] = "dynamicFilters = {" in text

    for kind, body in _JOIN.findall(text):
        cm, dm = _CRITERIA.search(body), _DISTRIBUTION.search(body)
        out["joins"].append({
            "type": kind,
            "criteria": cm.group(1).strip() if cm else "",
            "distribution": dm.group(1) if dm else None,
        })

    for kind, body in _SCAN.findall(text):
        tm = _SCAN_TABLE.search(body)
        fm = _FILTER_PRED.search(body)
        out["scans"].append({
            "node": kind,
            "table": tm.group(1) if tm else "",
            "filter": fm.group(1).strip() if fm else None,
            "dynamic_filter": "dynamicFilters = {" in body,
        })
    return out


def _finding(severity: str, code: str, message: str) -> dict:
    return {"severity": severity, "code": code, "message": message}


def review(io_text: Optional[str], dist_text: Optional[str] = None) -> dict:
    """Combine both plans into {accessed, problems, characteristics, findings, ...}.

    `dist_text` is optional on purpose: TYPE DISTRIBUTED is a second engine
    round-trip, and the table list — the part that answers "is this the query I
    meant" — must not depend on paying for it.

    Findings are split so warnings stay worth reading. `problems` are things to act
    on; `characteristics` describe how the engine will run it. Anything that would
    fire on every query belongs in neither: it is state, not news.
    """
    io = parse_io_plan(io_text or "")
    dist = parse_distributed_plan(dist_text or "")

    problems, characteristics = [], []

    for j in dist["joins"]:
        if j["type"].lower().startswith("cross"):
            problems.append(_finding(
                "critical", "cross_join",
                f"Cross join in the plan ({j['criteria'] or 'no join condition'}) — "
                "row count multiplies."))
        elif j["distribution"] == "REPLICATED":
            characteristics.append(_finding(
                "info", "broadcast_join",
                f"{j['type']} {j['criteria']} — broadcast (REPLICATED): the smaller "
                "side is copied to every worker."))

    # A full scan only matters on a large table, and without statistics we cannot know
    # the size. Warning regardless fires on every ordinary aggregate, which teaches
    # people to ignore the panel — and the accessed-tables list already states which
    # predicates reached each table, so nothing is hidden by staying quiet here.
    if io["estimates_available"]:
        filtered = {s["table"] for s in dist["scans"] if s["filter"]}
        for s in dist["scans"]:
            if not s["filter"] and s["table"] and s["table"] not in filtered:
                problems.append(_finding(
                    "warning", "unfiltered_scan",
                    f"{s['table']}: read in full, no predicate pushed down."))

    if dist["has_sort"] and not dist["sort_is_bounded"]:
        problems.append(_finding(
            "warning", "sort_without_limit",
            "Global sort with no LIMIT — the whole result set is ordered."))

    if dist["dynamic_filters"]:
        characteristics.append(_finding(
            "good", "dynamic_filter",
            "Dynamic filtering is active — the scan is narrowed by the join's values."))

    if dist["fragments"] > 4:
        characteristics.append(_finding(
            "info", "many_stages",
            f"{dist['fragments']} fragments — several shuffle stages."))

    order = {"critical": 0, "warning": 1}
    problems.sort(key=lambda f: order.get(f["severity"], 9))

    return {
        "accessed": io["tables"],
        "problems": problems,
        "characteristics": characteristics,
        "findings": problems + characteristics,
        "estimates_available": io["estimates_available"],
        "joins": dist["joins"],
        "fragments": dist["fragments"],
    }
