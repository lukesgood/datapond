"""Whether a statement reads or changes something.

`query:run` meant "execute SQL", and every role holding it could also `DROP TABLE` —
`viewer` included. Nothing in the execute path looked at what the statement was. The
only sign it had ever been considered is a comment in queries.py reading "Don't add
LIMIT to DDL or SHOW commands", written on the assumption that DDL flows through.

Fail-closed by construction: anything unparseable or unrecognised is a write. The two
errors are not symmetric — refusing a legitimate SELECT is an annoyance a permission
grant fixes, and allowing a DROP is a restore.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Statement types sqlglot produces that only read. Everything else — named or not —
# counts as a write, so a dialect sqlglot parses into a node this list does not know
# is refused rather than waved through.
_READ_NODES = {
    "Select", "Union", "Except", "Intersect", "Subquery",
    "Show", "Describe", "Explain", "Use", "Pragma",
}

# `WITH ... SELECT` parses to a Select carrying a With; `WITH ... INSERT` does not.
# Reading the top-level node is therefore enough, and asking about `With` itself is not.

# sqlglot parses SHOW and EXPLAIN into `Command`, its fallback for syntax the dialect
# does not model — and unsupported DDL (VACUUM, OPTIMIZE, CALL) lands there too. So the
# node is not enough; the leading keyword decides, from an allowlist.
_READ_COMMANDS = {"SHOW", "DESCRIBE", "DESC", "EXPLAIN", "USE"}

# EXPLAIN describes. EXPLAIN ANALYZE executes: an analyzed plan for a DELETE has
# already deleted the rows.
_EXECUTING_EXPLAIN = "ANALYZE"


def statement_kind(sql: Optional[str], dialect: str = "trino") -> str:
    """`"read"` or `"write"`. Never raises.

    A batch is as privileged as its most privileged statement: one write anywhere makes
    the whole request a write, wherever it sits and whatever precedes it.
    """
    if not sql or not sql.strip():
        return "write"

    import sqlglot

    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception as e:
        logger.info("unparseable SQL treated as a write: %s", str(e)[:200])
        return "write"

    if not statements or all(s is None for s in statements):
        # Comments only, or nothing sqlglot recognised as a statement. Not a read.
        return "write"

    for statement in statements:
        if statement is None:
            continue
        name = type(statement).__name__
        if name == "Command":
            if not _command_reads(statement):
                return "write"
            continue
        if name not in _READ_NODES:
            return "write"
    return "read"


def _command_reads(statement) -> bool:
    """A `Command` fallback node, judged by its leading keyword."""
    keyword = str(getattr(statement, "this", "") or "").strip().upper()
    if keyword not in _READ_COMMANDS:
        return False
    if keyword == "EXPLAIN":
        # `expression` is a Literal wrapping the rest of the text; str() on it keeps
        # the quotes, which is how the first attempt let EXPLAIN ANALYZE through.
        expression = getattr(statement, "expression", None)
        rest = str(getattr(expression, "this", expression) or "").strip().upper()
        if rest.startswith(_EXECUTING_EXPLAIN):
            return False
    return True
