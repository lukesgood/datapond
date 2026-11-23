"""Approved metric definitions as /ai/sql prompt context.

What goes in the prompt is reported as `metrics_provided` — given, not used: nothing
here can tell whether the model followed a definition. `suggest` is a word match, not a
model call, so it is reproducible and cannot be talked into anything. It is a hint: it
knows the metric's name, not whether its dimensions fit the question.
"""
import re
from typing import Dict, List, Optional, Tuple

RULE = ("If the question asks for one of these metrics, use its expression and filters "
        "exactly.")


def _terms(m: dict) -> List[str]:
    return [t for t in [m["label"], *(m.get("synonyms") or [])] if t and t.strip()]


# Words a term may carry that the question need not repeat ("총 매출액" ~ "매출액").
_OPTIONAL = {"총", "전체", "합계", "total", "sum"}
# A term's count word ("주문 수", "청구서 건수") is satisfied by the question asking for a
# count: an explicit cue ("주문은 몇 건", "how many orders"), or "수" right after one of
# the term's own words ("고객 수는", "고객수"). A bare "수" is not a cue: it is in
# "할 수 있다", "점수" and "수량".
_COUNT_WORDS = {"수", "건수", "개수", "횟수", "count", "number"}
_COUNT_CUE = re.compile(r"몇\s*(건|개|명|번|회)|건수|개수|횟수|how many|number of|\bcount\b")


Aliases = Dict[str, List[str]]


def alias_map(concepts: List[dict]) -> Aliases:
    """word -> the other words of its concept, from the approved concept vocabulary
    (Metrics › Concepts). Korean aliases are kept in one place: a metric labelled
    "고객 수" answers "회원 수" when 회원 is a term of the concept 고객, without the
    metric repeating 회원 as a synonym. Only one-word terms take part — a word of a
    metric's label is compared with a word, never with a phrase."""
    out: Aliases = {}
    for c in concepts or []:
        words = {t.strip().lower() for t in [c.get("name"), *(c.get("terms") or [])]
                 if t and t.strip() and len(t.strip().split()) == 1}
        for w in words:
            out.setdefault(w, [])
            out[w] += sorted(x for x in words - {w} if x not in out[w])
    return out


def _found(word: str, q: str, aliases: Optional[Aliases]) -> Optional[str]:
    """The form of `word` the question uses: the word itself, or one of its concept's
    other words; None when neither occurs."""
    if word in q:
        return word
    return next((a for a in (aliases or {}).get(word, []) if a in q), None)


def _counted(anchors: List[str], q: str) -> bool:
    if _COUNT_CUE.search(q):
        return True
    return any(re.search(re.escape(a) + r"\s?수(는|를|가|도|와|과|만|의)?(?!\w)", q)
               for a in anchors)


def _term_score(term: str, q: str, aliases: Optional[Aliases] = None) -> int:
    """Characters of the term's words found in the question when every required word is
    found (as a substring, so Korean particles and spacing do not matter; a word may be
    found as another word of its concept); else 0. A term made only of count or optional
    words never matches on its own."""
    words = [w for w in re.findall(r"\w+", term.lower()) if w not in _OPTIONAL]
    anchors = [w for w in words if w not in _COUNT_WORDS]
    used = [_found(a, q, aliases) for a in anchors]
    if not anchors or any(u is None for u in used):
        return 0
    counts = [w for w in words if w in _COUNT_WORDS]
    if counts and not _counted(used, q):
        return 0
    return sum(len(w) for w in words)


def _matches(m: dict, question: str, aliases: Optional[Aliases] = None) -> int:
    """Best term score for this metric; 0 if no label/synonym matches."""
    q = (question or "").lower()
    return max((_term_score(t, q, aliases) for t in _terms(m)), default=0)


def metric_lines(metrics: List[dict], question: str, limit: int = 20,
                 aliases: Optional[Aliases] = None) -> Tuple[str, List[str]]:
    if not metrics:
        return "", []
    ranked = sorted(metrics, key=lambda m: (-_matches(m, question, aliases), m["name"]))[:limit]
    lines = []
    for m in ranked:
        names = m["label"] + (f"; {', '.join(m['synonyms'])}" if m.get("synonyms") else "")
        where = f" WHERE {m['filters']}" if m.get("filters") else ""
        time = f" [time: {m['time_column']}]" if m.get("time_column") else ""
        lines.append(f"- {m['name']} ({names}): {m['measure']} FROM {m['base_table']}{where}{time}")
    block = "Approved metric definitions:\n" + "\n".join(lines) + "\n" + RULE
    return block, [f"{m['name']}@v{m['version']}" for m in ranked]


def suggest(metrics: List[dict], question: str,
            aliases: Optional[Aliases] = None) -> Optional[dict]:
    """The best-matching metric, or None when nothing matches or two metrics tie: a
    coin flip between them is not a suggestion."""
    scored = sorted(((_matches(m, question, aliases), m) for m in metrics or []),
                    key=lambda x: -x[0])
    if not scored or scored[0][0] == 0 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return None
    best = scored[0][1]
    return {"name": best["name"], "dimensions": list(best.get("dimensions") or []),
            "period_required": bool(best.get("time_column"))}


async def for_caller(user: dict, catalog: Optional[str] = None) -> List[dict]:
    """Approved metrics this caller may see, with their current version's fields.
    base_table is catalog.schema.table in the engine's naming, as the prompt's rules and
    schema context name every other table."""
    from app import catalog_access
    from app.semantic import service, store
    visible = {m["name"] for m in await service.list_visible(user, catalog)}
    if not visible:
        return []
    access = await catalog_access.for_caller(user)
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
                    "base_table": f"{access.resolve(v.catalog).engine_catalog}.{v.base_table}",
                    "time_column": v.time_column,
                    "dimensions": [d.name for d in v.dimensions]})
    return out
