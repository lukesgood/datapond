import asyncio
import ast
import inspect
import io
import json
import re
import tokenize
from datetime import datetime, timezone
from pathlib import Path

from app import audit_retention as ar


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _audit_retention_source() -> str:
    """Read the source of the audit_retention module."""
    return Path(inspect.getfile(ar)).read_text()


def _audit_retention_code() -> str:
    """`app/audit_retention.py` with its comments and docstrings removed, and every
    other string literal left in place. Mirrors test_audit_retention.py helper."""
    src = _audit_retention_source()
    lines = src.splitlines()
    blanked = set()

    # Docstrings: the first statement of a module, class or function when it is a
    # bare string. ast gives the line span; the literal may be several lines long.
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if ast.get_docstring(node, clean=False) is None:
            continue
        doc = node.body[0]
        blanked.update(range(doc.lineno, doc.end_lineno + 1))

    # Comments: tokenized rather than regex-matched, so a `#` inside a SQL string
    # does not truncate the statement that follows it on the same line.
    out = [line for line in lines]
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            continue
        (row, col), (_, end_col) = tok.start, tok.end
        out[row - 1] = out[row - 1][:col] + out[row - 1][end_col:]

    return "\n".join("" if i in blanked else line for i, line in enumerate(out, start=1))


def test_prune_calls_the_sanctioned_function_only():
    """Static check: module source contains the sanctioned function and no bare DELETE
    for tool_call_log. This mirrors test_audit_retention.py::test_module_source_never_spells_a_bare_delete_on_either_audit_table
    but scoped to tool_call_log specifically."""
    src = _audit_retention_code()

    # Check for bare DELETE FROM tool_call_log in the stripped code
    assert not re.search(r"DELETE\s+FROM\s+(public\.)?tool_call_log\b", src, re.I), (
        "found a bare DELETE FROM tool_call_log in app/audit_retention.py"
    )

    # Check that the sanctioned function is present
    full_src = _audit_retention_source()
    assert "SELECT prune_tool_call_log($1)" in full_src, (
        "prune_tool_call_log($1) SQL statement not found in audit_retention.py"
    )



def test_row_to_json_is_one_line_with_all_fields():
    row = {"id": 7, "occurred_at": datetime(2026, 9, 7, tzinfo=timezone.utc),
           "actor_id": "11111111-1111-1111-1111-111111111111", "actor_username": "svc-bot",
           "actor_kind": "service", "tool": "ai.rag", "resource_kind": "collection",
           "resource": ["faq"], "request_hash": "abc", "request_masked": "q",
           "hit_count": 3, "citation_sources": ["a.md"], "pii_masked": 1,
           "outcome": "ok", "duration_ms": 12, "client_address": None, "via": "api"}
    line = ar.tool_call_row_to_json(row)
    assert "\n" not in line
    d = json.loads(line)
    assert d["tool"] == "ai.rag" and d["resource"] == ["faq"] and d["occurred_at"].startswith("2026-09-07")


class _Conn:
    def __init__(self, pages):
        self._pages = list(pages)

    async def fetch(self, sql, *args):
        return self._pages.pop(0) if self._pages else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self._conn


def _row(i):
    return {"id": i, "occurred_at": datetime(2026, 9, 7, i, tzinfo=timezone.utc),
            "actor_id": None, "actor_username": "u", "actor_kind": "human",
            "tool": "ai.search", "resource_kind": "collection", "resource": ["c"],
            "request_hash": "h", "request_masked": "q", "hit_count": 1,
            "citation_sources": [], "pii_masked": 0, "outcome": "ok",
            "duration_ms": 1, "client_address": None, "via": "api"}


def test_stream_pages_until_short_page():
    pool = _Pool(_Conn([[_row(1), _row(2)], [_row(3)]]))

    async def _collect():
        out = []
        async for line in ar.stream_tool_call_export(
                pool, datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 12, 31, tzinfo=timezone.utc), page_size=2):
            out.append(line)
        return out
    lines = _run(_collect())
    assert len(lines) == 3 and all(l.endswith("\n") for l in lines)
