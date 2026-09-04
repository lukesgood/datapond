"""Whether the person named the target themselves.

The corpus is the user's own turns only — not content from any other source. The
assistant's turns are excluded, and that exclusion is the whole mechanism: the
assistant repeats what it read, and what it read includes table comments, column
names and document chunks that anyone with write access to a source can author.
Tool results are excluded too, for the same reason: they arrive under role: "user"
but carry untrusted catalog text and document chunks.

This function refuses to parse structured content (lists, dicts). If content is not
a plain string, the turn is skipped entirely. Text inside tool results or structured
payloads is by definition not what the user wrote, so there is nothing there worth
finding.

Typing the target at approval is the second line of defense. This is the first, and
it runs before a card is ever rendered.
"""
import re
from typing import List, Mapping, Optional, Sequence

# Segments shorter than this match ordinary prose: "ip" matches "clean up the ip
# in the report", "a" matches almost anything. Require 4 chars minimum so that
# two- and three-character table names must be named in full.
_MIN_SEGMENT = 4

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
    # A target that normalises to separators only (e.g., "...", "///") has no segments.
    if not parts:
        return None

    # The full name always counts. A trailing segment counts too, because people say
    # "the customers policy" — but only when it is long enough to mean something.
    candidates = [whole]
    if len(parts[-1]) >= _MIN_SEGMENT and parts[-1] != whole:
        candidates.append(parts[-1])

    for index, turn in enumerate(turns or ()):
        if (turn or {}).get("role") != "user":
            continue
        # Content must be a plain string. Tool results and structured content are
        # untrusted catalog text and live under role: "user"; refuse to parse them.
        content = (turn or {}).get("content")
        if not isinstance(content, str):
            continue
        haystack = normalise(content)
        for candidate in candidates:
            if re.search(rf"(?<![\w.:/]){re.escape(candidate)}(?![\w.:/])", haystack):
                return {"turn_index": index, "matched": candidate}
    return None
