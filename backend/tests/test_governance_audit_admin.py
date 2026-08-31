"""
Unit tests: the legacy governance reads (/governance/audit-log and
/governance/ai-safety) still return a normal response for a caller who is allowed
to see them.

Both expose every user's raw SQL text, so — like the newer unified
/governance/audit-stream — access is restricted. That restriction moved from a
body-level `_require_admin` call to a `require_permission("audit:read")` route
dependency (see test_governance_auditor_access.py, which pins the route-level gate
and that the `auditor` role — not just `admin` — can now reach these reads). A
dependency runs before the handler body, so a direct call to `gov.get_audit_log(...)`
no longer exercises it; what is left to pin here is that the handler itself still
behaves correctly once a permitted caller reaches it.
"""
import asyncio

from app.api import governance as gov


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


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

def test_audit_log_returns_empty_page():
    resp = _run(gov.get_audit_log(db=_FakeDB()))
    assert resp.total == 0 and resp.items == []


# ── /governance/ai-safety ─────────────────────────────────────────────────────

def test_ai_safety_returns_empty_report():
    resp = _run(gov.get_ai_safety(db=_FakeDB()))
    assert resp.risk_distribution.high == 0 and resp.recent_flags == []
