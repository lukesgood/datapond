"""Approved metric definitions as /ai/sql prompt context.

What goes in the prompt is reported as `metrics_provided` — given, not used: nothing
here can tell whether the model followed a definition. `suggest` is a verbatim string
match, not a model call, so it is reproducible and cannot be talked into anything.
"""
from typing import List, Optional, Tuple

RULE = ("If the question asks for one of these metrics, use its expression and filters "
        "exactly.")


def _terms(m: dict) -> List[str]:
    return [t for t in [m["label"], *(m.get("synonyms") or [])] if t and t.strip()]


def _matches(m: dict, question: str) -> int:
    """Length of the longest label/synonym found in the question; 0 if none."""
    q = (question or "").lower()
    return max((len(t) for t in _terms(m) if t.lower() in q), default=0)


def metric_lines(metrics: List[dict], question: str, limit: int = 20) -> Tuple[str, List[str]]:
    if not metrics:
        return "", []
    ranked = sorted(metrics, key=lambda m: (-_matches(m, question), m["name"]))[:limit]
    lines = []
    for m in ranked:
        names = m["label"] + (f"; {', '.join(m['synonyms'])}" if m.get("synonyms") else "")
        where = f" WHERE {m['filters']}" if m.get("filters") else ""
        time = f" [time: {m['time_column']}]" if m.get("time_column") else ""
        lines.append(f"- {m['name']} ({names}): {m['measure']} FROM {m['base_table']}{where}{time}")
    block = "Approved metric definitions:\n" + "\n".join(lines) + "\n" + RULE
    return block, [f"{m['name']}@v{m['version']}" for m in ranked]


def suggest(metrics: List[dict], question: str) -> Optional[dict]:
    best = max(metrics or [], key=lambda m: _matches(m, question), default=None)
    if best is None or _matches(best, question) == 0:
        return None
    return {"name": best["name"], "dimensions": list(best.get("dimensions") or [])}


async def for_caller(user: dict, catalog: Optional[str] = None) -> List[dict]:
    """Approved metrics this caller may see, with their current version's fields."""
    from app.semantic import service, store
    visible = {m["name"] for m in await service.list_visible(user, catalog)}
    if not visible:
        return []
    pool = await service._pool()
    out = []
    for m in await store.list_metrics(pool):
        if m["name"] not in visible:
            continue
        v = await store.get_version(pool, m["id"], m["name"], m["current_version"])
        if v is None:
            continue
        out.append({"name": m["name"], "label": m["label"], "synonyms": list(m["synonyms"] or []),
                    "version": v.version, "measure": v.measure, "filters": v.filters,
                    "base_table": v.base_table, "time_column": v.time_column,
                    "dimensions": [d.name for d in v.dimensions]})
    return out
