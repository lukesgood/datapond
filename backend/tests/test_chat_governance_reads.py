"""Policy coverage and the governance summary, for the assistant."""
import asyncio
from contextlib import contextmanager

from app.chat.analysis import governance as mod


def _run(c):
    return asyncio.run(c)


def test_policy_coverage_passes_the_caller(monkeypatch):
    seen = {}

    async def _fake(user=None):
        seen["user"] = user
        return {"covered": 3, "uncovered": 1}

    monkeypatch.setattr("app.api.governance.rls_coverage", _fake)
    user = {"id": "u1"}
    out = _run(mod.policy_coverage({}, user))
    assert seen["user"] is user
    assert out["coverage"]["covered"] == 3


def test_summary_stats_opens_and_closes_a_session(monkeypatch):
    """The handler is sync and takes a Session as a Depends default. Called with no
    session it would receive a Depends object and fail inside SQLAlchemy."""
    closed = {"value": False}

    class _Session:
        pass

    session = _Session()

    @contextmanager
    def _ctx():
        try:
            yield session
        finally:
            closed["value"] = True

    monkeypatch.setattr("app.database.connection.get_db_context", _ctx)
    monkeypatch.setattr("app.api.governance.get_governance_stats",
                        lambda db: {"policies": 4, "seen_db": db})

    out = _run(mod.summary_stats({}, {"id": "u1"}))
    assert out["stats"]["seen_db"] is session
    assert closed["value"] is True


def test_both_are_reads_on_governance_read():
    for action_id in ("governance.policy_coverage", "governance.summary_stats"):
        action = next(a for a in mod.ACTIONS if a.id == action_id)
        assert action.kind.value == "read"
        assert action.permission == "governance:read"
        assert action.capability is None
