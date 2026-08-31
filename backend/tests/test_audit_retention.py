"""B4 — retention for the audit tables, and an export that does not need the DB.

Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (B4)

B3 (`0005_audit_append_only`) made `security_audit_log` and `auth_audit_log` reject
every UPDATE and DELETE except one: a DELETE issued from inside
`prune_security_audit_log(cutoff_ts)` / `prune_auth_audit_log(cutoff_ts)`, the two
SECURITY DEFINER functions that flip the trigger's escape-hatch GUC on, delete, and
flip it back off. Anything else that tries `DELETE FROM security_audit_log ...`
directly gets the same `insufficient_privilege` exception every other caller does —
but only at runtime, against a real Postgres, which is why the first half of this
file checks `app/audit_retention.py`'s own source text for a bare DELETE rather than
trusting that a behavioural test against a fake connection would catch one. A fake
`_FakeConn.execute` happily "succeeds" against SQL text it never validates, so a
regression that swapped the two `SELECT prune_*(...)` calls for
`DELETE FROM security_audit_log WHERE ...` would sail through every test below that
only inspects call arguments — it would only ever fail in production, the first time
the trigger actually saw it. The source-text assertion is the one that would have
caught it before that.

There is no database in this test environment (same limitation
`tests/test_audit_append_only.py` names), so nothing here proves the trigger really
rejects a bare DELETE, or that `prune_security_audit_log` really deletes rows in a
live cluster — B3's tests and this file both stop at "the SQL says what it should."
A live proof belongs in an acceptance/integration run against a real PostgreSQL
instance.
"""
import ast
import asyncio
import inspect
import io
import json
import re
import tokenize
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.audit_retention as audit_retention
from app.audit_retention import prune, retention_cutoff, retention_days, tick


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _now():
    return datetime(2026, 8, 31, 6, 0, tzinfo=timezone.utc)


# ── retention_cutoff / retention_days: the floor ────────────────────────────

def test_the_cutoff_is_the_retention_window_back_from_now():
    assert retention_cutoff(_now(), 365) == _now() - timedelta(days=365)


def test_retention_cannot_be_disabled_by_a_zero_or_negative_setting():
    """The whole point of a floor rather than an off switch: a zero or negative
    number configured by mistake (or by someone trying to turn retention off
    entirely) must still prune something, not nothing. Mirrors
    test_system_events.py::test_retention_cannot_be_disabled_by_a_zero_or_negative_setting
    at the higher floor a compliance-relevant log needs — see the module docstring
    for why 90 days rather than system_events' 1."""
    assert retention_cutoff(_now(), 0) == _now() - timedelta(days=90)
    assert retention_cutoff(_now(), -5) == _now() - timedelta(days=90)


def test_the_floor_is_well_above_system_events_operational_floor():
    """A security audit log is compliance evidence, not operational telemetry —
    system_events.py's 1-day floor would let an operator configure this table down
    to next to nothing. Pinning the relationship, not just the number, so a future
    edit to either module's floor gets compared against the other on purpose."""
    from app.system_events import _MIN_RETENTION_DAYS as system_events_floor
    assert audit_retention._MIN_RETENTION_DAYS > system_events_floor


def test_default_retention_is_substantially_longer_than_system_events(monkeypatch):
    """No env override: the shipped default. Deliberately not pinned to an exact
    number beyond "much longer than 30" — the reasoning for the specific value lives
    in the module docstring, not in an assertion that would need editing every time
    someone reads a compliance framework more carefully than this comment did."""
    monkeypatch.delenv("AUDIT_RETENTION_DAYS", raising=False)
    assert retention_days() >= 180


def test_retention_days_reads_the_env_var_but_still_enforces_the_floor(monkeypatch):
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "400")
    assert retention_days() == 400
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "3")
    assert retention_days() == 90


def test_retention_days_survives_a_garbage_env_value(monkeypatch):
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "not-a-number")
    assert retention_days() == audit_retention._DEFAULT_RETENTION_DAYS


# ── prune(): the sanctioned deletion path, not a bare DELETE ────────────────

class _FakeConn:
    """Records exactly what SQL text and arguments prune() sends, and returns a
    canned row count per statement — enough to prove *which* statements were issued
    without a real database."""

    def __init__(self, calls, results):
        self._calls = calls
        self._results = results

    async def fetchval(self, sql, *args):
        self._calls.append((sql, args))
        for pattern, value in self._results:
            if pattern in sql:
                return value
        return 0

    async def execute(self, sql, *args):
        self._calls.append((sql, args))
        return "OK"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, calls, results=()):
        self._calls = calls
        self._results = results

    def acquire(self, *a, **k):
        return _FakeConn(self._calls, self._results)


def _audit_retention_source() -> str:
    return Path(inspect.getfile(audit_retention)).read_text()


def _audit_retention_code() -> str:
    """`app/audit_retention.py` with its comments and docstrings removed, and every
    other string literal left in place.

    The pin below reads the module's source looking for a bare DELETE against an
    audit table — and the module's docstring explains, in prose and by name, why it
    must never contain one. Searched raw, the file matches its own explanation and
    a correct module fails.

    Stripping *all* string literals would be the wrong way out of that. Every SQL
    statement this module sends lives in a string literal, so a real bare
    `DELETE FROM security_audit_log ...` would be written in one too — strip them
    and the pin can never fire again, which is worse than the false positive it
    fixes. Comments and docstrings are the only places prose lives and the only
    places SQL cannot be executed from, so they are exactly what comes out.
    """
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


def test_prune_calls_the_sanctioned_functions_not_a_bare_delete():
    """Behavioural half of the pin described in the module docstring: the exact two
    statements prune() sends, and that neither is a DELETE issued directly against
    the tables."""
    calls = []
    conn = _FakeConn(calls, [("prune_security_audit_log", 4), ("prune_auth_audit_log", 9)])
    result = _run(prune(conn, _now()))
    assert result == {"security_audit_log": 4, "auth_audit_log": 9}
    assert len(calls) == 2
    for sql, args in calls:
        assert "select" in sql.lower()
        assert "delete" not in sql.lower(), (
            f"prune() issued a bare DELETE ({sql!r}) instead of calling a "
            f"prune_*_audit_log() function — B3's trigger will reject this at runtime"
        )
        assert args == (_now(),)
    sqls = {sql for sql, _ in calls}
    assert any("prune_security_audit_log" in s for s in sqls)
    assert any("prune_auth_audit_log" in s for s in sqls)


def test_prune_returns_zero_for_a_table_with_nothing_to_remove():
    calls = []
    conn = _FakeConn(calls, [("prune_security_audit_log", None), ("prune_auth_audit_log", None)])
    result = _run(prune(conn, _now()))
    assert result == {"security_audit_log": 0, "auth_audit_log": 0}


def test_module_source_never_spells_a_bare_delete_on_either_audit_table():
    """Static half of the same pin, against the file itself rather than a mock's
    call log — a mock only proves what ran during *this* test; the source text is
    what a reviewer (or a future edit) actually has to get right. `prune_*_audit_log`
    is exempt because that identifier necessarily contains the substring
    "audit_log" and legitimately names the sanctioned function, not a table.

    Read against the code with comments and docstrings removed — see
    `_audit_retention_code()` for why that subtraction, and only that one."""
    src = _audit_retention_code()
    for table in ("security_audit_log", "auth_audit_log"):
        assert not re.search(rf"DELETE\s+FROM\s+{table}\b", src, re.I), (
            f"found a bare DELETE FROM {table} in app/audit_retention.py"
        )
    assert "prune_security_audit_log" in src
    assert "prune_auth_audit_log" in src


# ── tick(): single-leader via its own advisory lock key ─────────────────────

class _LockConn(_FakeConn):
    def __init__(self, calls, results, lock_granted=True):
        super().__init__(calls, results)
        self.lock_granted = lock_granted
        self.unlocked = False

    async def fetchval(self, sql, *args):
        if "pg_try_advisory_lock" in sql:
            self._calls.append((sql, args))
            return self.lock_granted
        return await super().fetchval(sql, *args)

    async def execute(self, sql, *args):
        if "pg_advisory_unlock" in sql:
            self.unlocked = True
        return await super().execute(sql, *args)


class _LockPool(_FakePool):
    def __init__(self, calls, results, lock_granted=True):
        self._calls = calls
        self._results = results
        self._lock_granted = lock_granted
        self.conn = None

    def acquire(self, *a, **k):
        self.conn = _LockConn(self._calls, self._results, self._lock_granted)
        return self.conn


def test_tick_prunes_and_releases_the_lock_when_it_gets_one(monkeypatch):
    monkeypatch.delenv("AUDIT_RETENTION_DAYS", raising=False)
    calls = []
    pool = _LockPool(calls, [("prune_security_audit_log", 1), ("prune_auth_audit_log", 2)])
    result = _run(tick(pool))
    assert result == {"security_audit_log": 1, "auth_audit_log": 2}
    assert pool.conn.unlocked is True


def test_tick_does_nothing_when_another_replica_holds_the_lock():
    calls = []
    pool = _LockPool(calls, [], lock_granted=False)
    result = _run(tick(pool))
    assert result == {}
    # Nothing beyond the failed lock attempt was ever sent.
    assert not any("prune_" in sql for sql, _ in calls)


def test_lock_key_is_distinct_from_system_events_and_rag_scheduler():
    """Reusing either existing key would serialize audit retention behind an
    unrelated loop for no reason — each holds its key for the length of its own
    tick, and the two have nothing to coordinate about."""
    from app.rag_scheduler import LOCK_KEY as rag_scheduler_key
    from app.system_events import LOCK_KEY as system_events_key
    assert audit_retention.LOCK_KEY not in (rag_scheduler_key, system_events_key)


# ── Export: NDJSON shape, one object per line, time-filtered ────────────────

def test_row_to_ndjson_line_is_one_parseable_json_object_per_row():
    from app.audit_retention import security_audit_row_to_json

    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "actor_id": "22222222-2222-2222-2222-222222222222",
        "actor_username": "alice",
        "permission": "connector:write",
        "route": "/api/connectors/abc/sync",
        "method": "POST",
        "outcome": "denied",
        "reason": "missing permission",
        "client_address": "203.0.113.9",
        "occurred_at": _now(),
    }
    line = security_audit_row_to_json(row)
    assert line.endswith("\n") is False  # the caller appends the newline, once
    parsed = json.loads(line)
    assert parsed["permission"] == "connector:write"
    assert parsed["outcome"] == "denied"
    assert parsed["occurred_at"] == _now().isoformat()


def test_row_to_ndjson_line_handles_a_null_actor():
    """actor_id is SET NULL on account deletion (0004's schema comment) — a row
    naming nobody must still serialize rather than raising mid-stream."""
    from app.audit_retention import security_audit_row_to_json

    row = {
        "id": "id", "actor_id": None, "actor_username": "", "permission": "p",
        "route": "/x", "method": "GET", "outcome": "denied", "reason": "r",
        "client_address": None, "occurred_at": _now(),
    }
    parsed = json.loads(security_audit_row_to_json(row))
    assert parsed["actor_id"] is None
    assert parsed["client_address"] is None


class _ExportConn:
    """Two pages of rows, keyset-paginated by (occurred_at, id) — enough to prove
    the generator streams page by page rather than reading the whole table with one
    unbounded query, without needing a real cursor or a real database."""

    def __init__(self, rows):
        self._rows = rows
        self.fetch_calls = []

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        since, until = args[0], args[1]
        # Five arguments is the keyset page: (since, until, last_occurred, last_id,
        # page_size). The first page sends three — (since, until, page_size) — and
        # has no cursor to resume from. Counting them is how this fake tells the two
        # queries apart without parsing SQL, so the count has to match what
        # stream_security_audit_export() actually sends: a fake that never
        # recognises the keyset page keeps answering with the first one, and the
        # generator, which stops only on a short or empty page, then never stops.
        if len(args) == 5:
            last_occurred, last_id = args[2], args[3]
            candidates = [r for r in self._rows
                          if (r["occurred_at"], r["id"]) > (last_occurred, last_id)]
        else:
            candidates = list(self._rows)
        candidates = [r for r in candidates if since <= r["occurred_at"] <= until]
        candidates.sort(key=lambda r: (r["occurred_at"], r["id"]))
        page_size = args[-1]
        return candidates[:page_size]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _ExportPool:
    """A connection per page, as stream_security_audit_export() takes one — with a
    ceiling on how many it will hand out.

    The ceiling is not paranoia about the production loop; it is about this file.
    The generator paginates until a page comes back short or empty, so a fake that
    answers every page identically makes it loop forever, and a test that loops
    forever inside an `async for` hangs the whole pytest run rather than failing it
    — no failure line, no traceback, just a suite that never finishes. len(rows) + 2
    is more pages than any correct run of these tests can need (the smallest
    page_size here is 1), so exceeding it means the loop is not converging, and
    raising says so with a stack trace instead of stalling.
    """

    def __init__(self, rows):
        self._rows = rows
        self._pages = 0

    def acquire(self, *a, **k):
        self._pages += 1
        assert self._pages <= len(self._rows) + 2, (
            f"the export generator asked for page {self._pages} of at most "
            f"{len(self._rows) + 2} — it is not converging on the end of the rows"
        )
        return _ExportConn(self._rows)


def _rows(n, start_hour=0):
    base = _now()
    return [
        {
            "id": f"{i:08d}-0000-0000-0000-000000000000",
            "actor_id": None, "actor_username": "svc", "permission": "connector:write",
            "route": "/api/connectors", "method": "POST", "outcome": "allowed",
            "reason": "", "client_address": None,
            "occurred_at": base + timedelta(hours=start_hour + i),
        }
        for i in range(n)
    ]


def test_export_stream_yields_one_ndjson_line_per_row_in_order():
    from app.audit_retention import stream_security_audit_export

    rows = _rows(5)
    pool = _ExportPool(rows)
    lines = _run(_collect(stream_security_audit_export(
        pool, since=rows[0]["occurred_at"], until=rows[-1]["occurred_at"], page_size=2)))
    assert len(lines) == 5
    for line in lines:
        assert line.endswith("\n")
        json.loads(line)  # parseable
    ids = [json.loads(line)["id"] for line in lines]
    assert ids == [r["id"] for r in rows]


def test_export_stream_applies_the_time_range_filter():
    from app.audit_retention import stream_security_audit_export

    rows = _rows(10)
    pool = _ExportPool(rows)
    since = rows[3]["occurred_at"]
    until = rows[6]["occurred_at"]
    lines = _run(_collect(stream_security_audit_export(pool, since=since, until=until, page_size=2)))
    ids = [json.loads(line)["id"] for line in lines]
    assert ids == [r["id"] for r in rows[3:7]]


def test_export_stream_is_empty_when_the_window_matches_nothing():
    from app.audit_retention import stream_security_audit_export

    rows = _rows(3)
    pool = _ExportPool(rows)
    since = rows[-1]["occurred_at"] + timedelta(days=1)
    until = since + timedelta(days=1)
    lines = _run(_collect(stream_security_audit_export(pool, since=since, until=until, page_size=2)))
    assert lines == []


async def _collect(agen):
    out = []
    async for item in agen:
        out.append(item)
    return out


# ── Export route: gated on audit:read ───────────────────────────────────────

def _authorization_markers(route) -> set:
    """Same walk as test_governance_auditor_access.py: a permission is equally
    valid on the decorator's dependencies=[...] as on a signature parameter."""
    found, seen = set(), set()

    def walk(dependant):
        if id(dependant) in seen:
            return
        seen.add(id(dependant))
        marker = getattr(dependant.call, "__datapond_authorization__", None)
        if marker:
            found.add(marker)
        for sub in dependant.dependencies:
            walk(sub)

    walk(route.dependant)
    return found


def test_the_export_route_exists_and_requires_audit_read():
    import main

    matches = [
        route for route in main.app.routes
        if getattr(route, "path", None) == "/api/audit/export"
        and "GET" in getattr(route, "methods", set())
    ]
    assert matches, "GET /api/audit/export is not registered"
    assert "audit:read" in _authorization_markers(matches[0])
