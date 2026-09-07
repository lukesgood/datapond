import asyncio
import json
from datetime import datetime, timezone

from app import audit_retention as ar


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_prune_calls_the_sanctioned_function_only():
    import inspect
    src = inspect.getsource(ar.prune)
    assert "prune_tool_call_log($1)" in src
    # Verify no bare DELETE FROM statements in the function body
    # (the docstring mentions DELETE, so we check the code part only)
    lines = src.split('\n')
    for line in lines:
        # Skip docstring lines (anything in triple quotes)
        if '"""' in line:
            continue
        # Check for DELETE FROM (SQL statement, not prose)
        if 'delete' in line.lower() and 'from' in line.lower():
            raise AssertionError(f"Found bare DELETE statement: {line}")



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
