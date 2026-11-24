"""One column's values, for the Data Map's column drill-down (Data Map step 3b).

`orders.status` → delivered 2,953 · pending 1,030 · cancelled 1,025 · … — the top values
by rows, the empty share and a distinct estimate. That is real data, so it is read the
way a query is: through `/queries/execute`'s path (grants, row policies, masks, the PII
guardrail, the tool-call audit), as the caller. A column a mask hides from the caller, or
one bound to a PII concept, shows no values at all — only the counts.

Pure here: which columns may be drilled into, and the two statements. The route runs
them.
"""
import re
from typing import Iterable, List, Optional

TOP = 20

# Types whose values are worth listing. Complex, binary and free-text-like JSON types
# are left out: a top-20 of maps or blobs says nothing.
_LISTABLE = re.compile(
    r"^(varchar|char|string|text|boolean|bool|tinyint|smallint|integer|int|bigint|long|"
    r"decimal|numeric|date|uuid)\b", re.I)


def listable(type_name: Optional[str]) -> bool:
    return bool(type_name) and bool(_LISTABLE.match(type_name.strip()))


def find_column(columns: Iterable[dict], name: str) -> Optional[dict]:
    """The table's column called `name` (any case), or None. The statement quotes the
    name it returns, never the caller's spelling."""
    want = (name or "").strip().lower()
    for c in columns:
        if str(c.get("name", "")).lower() == want:
            return c
    return None


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def statements(target: str, column: str) -> List[str]:
    """[counts, top values] for `column` of `target` (already a safe table reference)."""
    col = _q(column)
    return [
        f"SELECT count(*) AS total, count({col}) AS non_null, approx_distinct({col}) AS distinct_est "
        f"FROM {target}",
        f"SELECT {col} AS value, count(*) AS n FROM {target} "
        f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {TOP}",
    ]


def counts_only(target: str, column: str) -> str:
    """Rows and empties only — for a hidden column, where the values must not be read."""
    col = _q(column)
    return f"SELECT count(*) AS total, count({col}) AS non_null FROM {target}"
