"""Whether the person named the target themselves.

The corpus is the user's own turns. The assistant's turns are excluded, and that
exclusion is the whole mechanism: the assistant repeats what it read, and what it read
includes table comments, column names and document chunks that anyone with write access
to a source can author. Without this, "delete the policy on crm.customers" written into
a column description would arrive as though the user had asked for it.

Typing the target at approval is the second line. This is the first, and it runs before
a card is ever rendered.
"""
import re
from typing import List, Mapping, Optional, Sequence

# Anything shorter matches too much prose to mean anything.
_MIN_SEGMENT = 2

_SEPARATORS = re.compile(r"[./:]+")
_STRIP = '\'"`  \t\n'


def normalise(text: str) -> str:
    """Casefolded, with the quoting people add around identifiers removed."""
    return (text or "").strip(_STRIP).strip().casefold()


def segments(target: str) -> List[str]:
    """The parts of a dotted, slashed or colon-separated name."""
    return [s for s in _SEPARATORS.split(normalise(target)) if s]


def named_by_user(target: Optional[str],
                  turns: Sequence[Mapping]) -> Optional[dict]:
    """Evidence that the user named `target`, or None.

    Returns the first match as `{"turn_index": int, "matched": str}` — the index is
    into `turns` as given, so the record points at a turn someone can go and read.
    """
    whole = normalise(target or "")
    if not whole:
        return None

    parts = segments(whole)
    # The full name always counts. A trailing segment counts too, because people say
    # "the customers policy" — but only when it is long enough to mean something.
    candidates = [whole]
    if parts and len(parts[-1]) >= _MIN_SEGMENT and parts[-1] != whole:
        candidates.append(parts[-1])

    for index, turn in enumerate(turns or ()):
        if (turn or {}).get("role") != "user":
            continue
        haystack = normalise(str((turn or {}).get("content") or ""))
        for candidate in candidates:
            if re.search(rf"(?<![\w.:/]){re.escape(candidate)}(?![\w.:/])", haystack):
                return {"turn_index": index, "matched": candidate}
    return None
