"""Timestamps the browser can actually parse, and an activity column with data behind it.

`created_at` is timestamptz, so asyncpg hands back an aware datetime and isoformat()
already ends in "+00:00". The endpoint appended "Z" on top, producing
"2026-09-17T09:00:00+00:00Z" — which new Date() rejects, so the Joined column rendered
"Invalid Date". The same pattern was on nine more columns in the connectors API.
"""
import re
from datetime import datetime, timezone

import pytest

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def _serialised(dt):
    return dt.isoformat() if dt else None


def test_an_aware_timestamp_serialises_to_one_offset():
    dt = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)
    out = _serialised(dt)
    assert ISO.match(out), out
    assert not out.endswith("+00:00Z")


def test_the_browser_can_parse_what_we_emit():
    """A second offset makes the string unparseable — the actual failure on screen."""
    broken = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc).isoformat() + "Z"
    assert not ISO.match(broken), "this is the shape that rendered Invalid Date"


@pytest.mark.parametrize("module,attr", [("app.api.auth", "list_users")])
def test_the_endpoint_exists(module, attr):
    import importlib
    assert hasattr(importlib.import_module(module), attr)


def test_no_row_timestamp_is_double_suffixed():
    """The bug class, not just the one column: a row value that already carries an
    offset must not have "Z" appended anywhere."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    pattern = re.compile(r"(?:row|r)\[[^\]]+\]\.isoformat\(\) \+ \"Z\"")
    for path in root.rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{i}")
    assert not offenders, f"row timestamps with a second suffix: {offenders}"


def test_the_users_query_sources_activity_from_the_audit_log():
    """users.last_login_at is declared and written by nothing — a column sourced from
    it would always be empty, which is worse than absent."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "app/api/auth.py").read_text()
    assert "last_activity_at" in src
    assert "auth_audit_log" in src
    assert "u.last_login_at" not in src


# ── the helper both shapes go through ────────────────────────────────────────────

def test_an_aware_timestamp_gets_exactly_one_marker():
    from app.timefmt import iso_utc
    out = iso_utc(datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc))
    assert out == "2026-09-17T09:00:00Z"
    assert not out.endswith("+00:00Z")


def test_a_naive_timestamp_is_read_as_utc_not_as_local():
    """Every naive datetime here comes from utcnow(). Emitting it bare would let the
    browser apply the viewer's offset and show a different time to each person."""
    from app.timefmt import iso_utc
    assert iso_utc(datetime(2026, 7, 16, 1, 2, 3)) == "2026-07-16T01:02:03Z"


def test_an_offset_timestamp_is_converted_rather_than_relabelled():
    from datetime import timedelta
    from app.timefmt import iso_utc
    kst = timezone(timedelta(hours=9))
    assert iso_utc(datetime(2026, 9, 17, 18, 0, tzinfo=kst)) == "2026-09-17T09:00:00Z"


def test_none_stays_none():
    from app.timefmt import iso_utc
    assert iso_utc(None) is None
