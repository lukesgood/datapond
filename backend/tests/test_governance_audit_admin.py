"""
Unit tests: the legacy governance reads (/governance/audit-log and
/governance/ai-safety) are admin-only.

Both expose every user's raw SQL text, so — like the newer unified
/governance/audit-stream — they must reject non-admin callers. These tests pin
that the admin gate runs (a non-admin is 403'd before any DB access) and that an
admin passes through to a normal response.
"""
import asyncio

import pytest
from fastapi import HTTPException

import app.api.governance as gov

ADMIN = {"id": "u1", "role": "admin"}
VIEWER = {"id": "u2", "role": "viewer"}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _stub_admin_gate(monkeypatch):
    """Replace the RLS-coupled _require_admin with a plain role check, so these
    tests don't depend on the RLS loader / _RLS_ADMIN_OK. Asserting a viewer is
    rejected proves each endpoint actually invokes the gate."""
    async def _fake(user):
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin privileges required")
        return user
    monkeypatch.setattr(gov, "_require_admin", _fake)


class _FakeQuery:
    """Chainable no-op query returning an empty result set."""
    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def offset(self, *a, **k):
        return self

    def count(self):
        return 0

    def all(self):
        return []


class _FakeDB:
    def query(self, *a, **k):
        return _FakeQuery()


# ── /governance/audit-log ─────────────────────────────────────────────────────

def test_audit_log_rejects_non_admin():
    with pytest.raises(HTTPException) as e:
        _run(gov.get_audit_log(user=VIEWER, db=_FakeDB()))
    assert e.value.status_code == 403


def test_audit_log_rejects_anonymous():
    with pytest.raises(HTTPException) as e:
        _run(gov.get_audit_log(user=None, db=_FakeDB()))
    assert e.value.status_code == 403


def test_audit_log_allows_admin():
    resp = _run(gov.get_audit_log(user=ADMIN, db=_FakeDB()))
    assert resp.total == 0 and resp.items == []


# ── /governance/ai-safety ─────────────────────────────────────────────────────

def test_ai_safety_rejects_non_admin():
    with pytest.raises(HTTPException) as e:
        _run(gov.get_ai_safety(user=VIEWER, db=_FakeDB()))
    assert e.value.status_code == 403


def test_ai_safety_rejects_anonymous():
    with pytest.raises(HTTPException) as e:
        _run(gov.get_ai_safety(user=None, db=_FakeDB()))
    assert e.value.status_code == 403


def test_ai_safety_allows_admin():
    resp = _run(gov.get_ai_safety(user=ADMIN, db=_FakeDB()))
    assert resp.risk_distribution.high == 0 and resp.recent_flags == []
