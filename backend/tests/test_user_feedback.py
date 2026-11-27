"""Problem reports and feature requests (app/api/feedback.py)."""
import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import app.api.feedback as fb

UID = str(uuid.uuid4())
NOW = datetime(2026, 11, 27, tzinfo=timezone.utc)


def _r(**kw):
    base = {"id": uuid.uuid4(), "kind": "bug", "title": "t", "body": "", "page": None,
            "app_version": None, "user_agent": None, "created_by": uuid.UUID(UID),
            "created_by_name": "Luke", "status": "open", "admin_note": None,
            "created_at": NOW, "updated_at": NOW}
    return {**base, **kw}


class _Conn:
    def __init__(self):
        self.sql = []

    async def fetchrow(self, sql, *a):
        self.sql.append((sql, a))
        if sql.startswith("INSERT"):
            return _r(kind=a[0], title=a[1], body=a[2], page=a[3])
        return _r(status=a[0]) if "UPDATE" in sql else None

    async def fetch(self, sql, *a):
        self.sql.append((sql, a))
        return []


def _pool(monkeypatch, conn):
    class _Acq:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *e):
            return False

    async def _p():
        return SimpleNamespace(acquire=lambda: _Acq())
    monkeypatch.setattr(fb, "_get_pool", _p)

    async def _no(item):
        return None
    monkeypatch.setattr(fb, "_notify_admins", _no)


def test_a_report_is_filed_as_the_caller_with_the_page_path_only(monkeypatch):
    conn = _Conn(); _pool(monkeypatch, conn)
    body = fb.FeedbackIn(kind="bug", title="  Chart wraps  ", body="x",
                         page="/query?sql=SELECT%201#top", app_version="2.7.0-abc")
    out = asyncio.run(fb.file_feedback(body, user={"id": UID, "username": "luke"}))
    sql, args = conn.sql[0]
    assert args[1] == "Chart wraps"
    assert args[3] == "/query"                 # no query string (it may hold SQL or data)
    assert args[6] == uuid.UUID(UID) and args[7] == "luke"
    assert out["kind"] == "bug"


def test_a_full_url_or_other_host_is_not_stored_as_the_page():
    assert fb._clean_page("https://evil.example/x") is None
    assert fb._clean_page("//evil.example") is None
    assert fb._clean_page("/catalog") == "/catalog"


def test_kind_and_lengths_are_checked():
    with pytest.raises(ValidationError):
        fb.FeedbackIn(kind="praise", title="x")
    with pytest.raises(ValidationError):
        fb.FeedbackIn(kind="bug", title="")
    with pytest.raises(ValidationError):
        fb.FeedbackIn(kind="bug", title="x" * 201)


def test_triage_changes_status_and_note(monkeypatch):
    conn = _Conn(); _pool(monkeypatch, conn)
    out = asyncio.run(fb.update_feedback(str(uuid.uuid4()), fb.FeedbackUpdate(status="planned", admin_note="next sprint"), _admin={}))
    assert out["status"] == "planned"
    assert "status = $1" in conn.sql[0][0] and "admin_note = $2" in conn.sql[0][0]


def test_triage_with_nothing_to_change_is_refused(monkeypatch):
    _pool(monkeypatch, _Conn())
    with pytest.raises(HTTPException) as e:
        asyncio.run(fb.update_feedback(str(uuid.uuid4()), fb.FeedbackUpdate(), _admin={}))
    assert e.value.status_code == 400


def test_the_admin_email_names_the_report_and_where_it_came_from():
    subject, text = fb.report_email({"kind": "feature", "title": "Dark mode", "body": "please",
                                     "created_by_name": "Luke", "page": "/catalog",
                                     "app_version": "2.7.0"}, "https://dp/settings?tab=feedback")
    assert subject == "[DataPond] Feature request: Dark mode"
    assert "Page: /catalog" in text and "https://dp/settings?tab=feedback" in text


def test_only_admins_triage_and_any_person_files():
    import app.api.auth as auth
    routes = {(tuple(sorted(r.methods)), r.path): r for r in fb.router.routes}
    deps = lambda r: {d.call for d in r.dependant.dependencies}
    assert auth.require_admin in deps(routes[(("GET",), "/feedback")])
    assert auth.require_admin in deps(routes[(("PATCH",), "/feedback/{feedback_id}")])
    assert auth.require_human in deps(routes[(("POST",), "/feedback")])
