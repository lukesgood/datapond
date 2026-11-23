"""What /ai/sql questions say about the concepts that are missing (migration 0032).

The concept store grows by hand, and a person guessing which words to bind guesses
wrong: the 2026-11-23 evaluation (docs/CONCEPT_EVAL_2026-11.md) found the largest gain
in one segment value nobody would have listed first. This closes the loop from use back
to the store. Each generation leaves one row; read in aggregate they suggest:

- words — terms several questions use that no concept, alias or metric label covers:
  a new concept or an alias of an existing one;
- joins — statements that equated keys of two different concepts, whether the repair
  round fixed them or not: bindings worth a look;
- values — literal conditions (`tier = 'Platinum'`) on columns no approved segment
  states: a segment with the exact value.

Suggestions only, like every other proposal: nothing is bound from here. Questions are
stored PII-masked, as the tool-call log stores them, and only governance readers see the
aggregate. Deterministic, no model call.
"""
import json
import logging
import random
import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Off for evaluation runs, which call the generator directly and are not use.
ENABLED = True

_RETENTION_DAYS = 90
_MIN_QUESTIONS = 2           # a word or value seen in one question is an anecdote

# Korean particles and endings a word may carry ("고객의", "주문별로"); longest first.
_SUFFIXES = sorted(["에서는", "으로는", "에게서", "이라는", "에서", "으로", "에게", "까지", "부터",
                    "보다", "처럼", "마다", "별로", "별", "은", "는", "이", "가", "을", "를",
                    "의", "에", "로", "와", "과", "도", "만", "들"], key=len, reverse=True)
# Question endings glued to the last word ("건인가요", "몇명인지"); stripped first.
_ENDINGS = sorted(["인가요", "입니까", "인지요", "인가", "인지", "나요", "가요", "이에요", "예요",
                   "해줘", "해주세요", "주세요"], key=len, reverse=True)
_STOP = {
    "알려주세요", "알려줘", "알려", "보여주세요", "보여줘", "보여", "주세요", "해주세요", "얼마", "얼마인가요",
    "얼마나", "몇", "몇명", "건수", "개수", "합계", "평균", "최대", "최소", "총", "전체", "기준",
    "상위", "하위", "최근", "지난달", "이번달", "올해", "작년", "금년", "어제", "오늘", "수", "금액",
    "목록", "무엇", "어떤", "각", "모든", "중", "대한", "있는", "없는", "가장", "많은", "적은",
    "높은", "낮은", "명", "건", "개", "인가요", "입니까", "인지", "나요", "모두", "제외", "포함",
    "the", "of", "by", "per", "top", "total", "count", "sum", "avg", "average", "how", "many",
    "much", "what", "which", "show", "list", "last", "month", "year", "and", "for", "in", "with",
}
_WORD = re.compile(r"[가-힣]+|[A-Za-z][A-Za-z0-9_]*")


def words(question: str) -> List[str]:
    """Content words of a question, particles stripped, stopwords and numbers dropped."""
    out = []
    for w in _WORD.findall(question or ""):
        w = w.lower()
        if re.match(r"[가-힣]", w):
            for s in _ENDINGS:
                if w.endswith(s) and len(w) > len(s):
                    w = w[: -len(s)]
                    break
            for s in _SUFFIXES:
                if w.endswith(s) and len(w) - len(s) >= 2:
                    w = w[: -len(s)]
                    break
        # snake_case is a column the question named, not a business word
        if len(w) >= 2 and w not in _STOP and "_" not in w:
            out.append(w)
    return out


def known_words(concepts: Iterable[dict], metrics: Iterable[dict] = ()) -> List[str]:
    """Every concept name and term and every metric label and synonym, lowercased."""
    out = []
    for c in concepts:
        out += [c.get("name") or "", *(c.get("terms") or [])]
    for m in metrics:
        out += [m.get("label") or "", *(m.get("synonyms") or [])]
    return [w.strip().lower() for w in out if w and w.strip()]


def _covered(word: str, known: List[str]) -> bool:
    # "플래티넘" is covered by "플래티넘 고객"; "고객센터" by "고객". Substring either way
    # is generous on purpose: a suggestion that is already a term wastes a person's time.
    return any(word in k or k in word for k in known if len(k) >= 2)


def literals(sql: str, dialect: str = "trino", default_catalog: str = "") -> List[dict]:
    """`column = 'value'`, `column IN ('a', 'b')` and `column = true` conditions, each
    {table: catalog.namespace.table or "", column, value}. The table is resolved through
    aliases; an unqualified column belongs to the only table, or to none."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return []
    names: Dict[str, str] = {}
    tables = []
    for t in tree.find_all(exp.Table):
        full = ".".join(p for p in ((t.catalog or default_catalog), t.db, t.name) if p).lower()
        tables.append(full)
        names[(t.alias_or_name or t.name).lower()] = full
    only = tables[0] if len(set(tables)) == 1 else ""

    def table_of(col) -> str:
        return names.get(col.table.lower(), "") if col.table else only

    def value(node) -> Optional[str]:
        if isinstance(node, exp.Literal) and node.is_string:
            return node.this
        if isinstance(node, exp.Boolean):
            return "true" if node.this else "false"
        return None

    out, seen = [], set()

    def add(col, v):
        key = (table_of(col), col.name.lower(), v)
        if v is not None and key not in seen:
            seen.add(key)
            out.append({"table": key[0], "column": key[1], "value": v})

    for eq in tree.find_all(exp.EQ):
        a, b = eq.left, eq.right
        if isinstance(a, exp.Column):
            add(a, value(b))
        elif isinstance(b, exp.Column):
            add(b, value(a))
    for i in tree.find_all(exp.In):
        if isinstance(i.this, exp.Column):
            for v in i.expressions:
                add(i.this, value(v))
    return out


def _segment_values(bindings: Iterable[dict]) -> Dict[Tuple[str, str], str]:
    """(table, column) → the joined text of every approved segment on it."""
    out: Dict[Tuple[str, str], str] = defaultdict(str)
    for b in bindings:
        if b.get("role") == "filter" and b.get("filter_sql"):
            key = (f"{b['catalog']}.{b['namespace']}.{b['table']}".lower(), b["column"].lower())
            out[key] += " " + b["filter_sql"]
    return out


def suggest(rows: List[dict], concepts: List[dict], bindings: List[dict],
            metrics: List[dict] = (), limit: int = 20) -> dict:
    """The three kinds of suggestion from feedback rows ({question_masked, concepts,
    conflicts, conflicts_left, literals}), most frequent first."""
    known = known_words(concepts, metrics)
    word_q: Dict[str, set] = defaultdict(set)
    examples: Dict[str, List[str]] = defaultdict(list)
    for i, r in enumerate(rows):
        for w in set(words(r["question_masked"])):
            if not _covered(w, known):
                word_q[w].add(i)
                if len(examples[w]) < 2:
                    examples[w].append(r["question_masked"])
    word_out = [{"word": w, "questions": len(q), "examples": examples[w]}
                for w, q in word_q.items() if len(q) >= _MIN_QUESTIONS]
    word_out.sort(key=lambda x: (-x["questions"], x["word"]))

    joins: Dict[str, dict] = {}
    for r in rows:
        left = set(r.get("conflicts_left") or [])
        for msg in r.get("conflicts") or []:
            j = joins.setdefault(msg, {"join": msg, "seen": 0, "unrepaired": 0, "example": r["question_masked"]})
            j["seen"] += 1
            j["unrepaired"] += msg in left
    join_out = sorted(joins.values(), key=lambda x: (-x["unrepaired"], -x["seen"], x["join"]))

    segs = _segment_values(bindings)
    vals: Dict[Tuple[str, str, str], dict] = {}
    for r in rows:
        lits = r.get("literals") or []
        if isinstance(lits, str):
            lits = json.loads(lits)
        for lit in lits:
            if not lit.get("table"):
                continue
            stated = segs.get((lit["table"], lit["column"]), "")
            if f"'{lit['value']}'" in stated or (lit["value"] in ("true", "false") and lit["value"] in stated.lower()):
                continue
            k = (lit["table"], lit["column"], lit["value"])
            v = vals.setdefault(k, {"table": lit["table"], "column": lit["column"], "value": lit["value"],
                                    "questions": 0, "example": r["question_masked"],
                                    "segments_on_column": bool(stated)})
            v["questions"] += 1
    val_out = sorted((v for v in vals.values() if v["questions"] >= _MIN_QUESTIONS),
                     key=lambda x: (-x["questions"], x["table"], x["column"], x["value"]))
    return {"questions": len(rows), "words": word_out[:limit], "joins": join_out[:limit],
            "values": val_out[:limit]}


async def record(user: dict, question: str, sql: str, concepts_provided: List[dict],
                 conflicts: List[str], conflicts_left: List[str],
                 dialect: str = "trino", default_catalog: str = "") -> None:
    """Store one generation. Never raises into /ai/sql."""
    if not ENABLED:
        return
    try:
        from app import tool_call_log
        from app.api.connectors import get_db_pool
        from app.guardrails import pii_ko
        # A value that holds personal data is no segment and is not kept at all.
        lits = [x for x in literals(sql or "", dialect, default_catalog)
                if pii_ko.mask(x["value"]) == x["value"]]
        pool = await get_db_pool()
        actor = user.get("id")
        async with pool.acquire(timeout=2) as c:
            await c.execute(
                "INSERT INTO concept_feedback (actor_id, question_masked, concepts, conflicts, "
                "conflicts_left, literals) VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb)",
                actor if actor and re.fullmatch(r"[0-9a-f-]{36}", str(actor)) else None,
                tool_call_log.masked_for_log(question or ""),
                [c_["name"] for c_ in concepts_provided or []], list(conflicts or []),
                list(conflicts_left or []), json.dumps(lits, ensure_ascii=False))
            if random.random() < 0.01:
                await c.execute("DELETE FROM concept_feedback WHERE occurred_at < "
                                f"now() - interval '{_RETENTION_DAYS} days'")
    except Exception as e:
        logger.info("[concepts] feedback not recorded: %s", e)


async def load(pool, days: int = 30) -> List[dict]:
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT question_masked, concepts, conflicts, conflicts_left, literals "
            "FROM concept_feedback WHERE occurred_at >= now() - make_interval(days => $1) "
            "ORDER BY occurred_at DESC LIMIT 5000", int(days))
    return [dict(r) for r in rows]


def visible_rows(rows: List[dict], allows_table) -> List[dict]:
    """Literals on catalogs the reader may not use are dropped; the rest of the row stays."""
    out = []
    for r in rows:
        lits = r.get("literals") or []
        if isinstance(lits, str):
            lits = json.loads(lits)
        out.append(dict(r, literals=[x for x in lits if x.get("table") and allows_table(x["table"])]))
    return out


def counts(rows: List[dict]) -> Counter:
    return Counter(n for r in rows for n in (r.get("concepts") or []))
