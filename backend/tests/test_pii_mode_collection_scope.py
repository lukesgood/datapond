"""A collection can be held to a stricter PII mode than the deployment default.

The mode was one env var, so a collection of public FAQ text and one holding resident
registration numbers were treated identically (POSITIONING_FIT_AUDIT §2.4). The gate
every collection route already calls now applies the collection's own setting.
"""
import asyncio

import pytest

from app.api import ai_vectors
from app.guardrails import pii_ko


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


USER = {"id": "11111111-1111-1111-1111-111111111111", "username": "alice", "role": "admin"}


class _Conn:
    def __init__(self, row):
        self.row = row
        self.sql = None

    async def fetchrow(self, sql, *args):
        self.sql = sql
        return self.row


def _row(pii_mode):
    return {"id": "c-1", "owner_id": USER["id"], "pii_mode": pii_mode, "member_role": None}


@pytest.fixture(autouse=True)
def default_mask(monkeypatch):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "mask")
    monkeypatch.setattr(ai_vectors, "may_read", lambda *a, **k: True)
    monkeypatch.setattr(ai_vectors, "may_write", lambda *a, **k: True)


def test_the_gate_reads_the_collections_mode():
    conn = _Conn(_row("block"))
    _run(ai_vectors._collection_id(conn, "customers", USER))
    assert "col.pii_mode" in conn.sql, "the gate's own query has to carry the column"


async def _mode_after_gate(pii_mode):
    """The mode as the rest of the request would see it.

    Read inside the same coroutine on purpose: a ContextVar set in a coroutine does
    not propagate back to the caller's context, and asserting from outside would pass
    whatever the gate did. In a request, the handler and everything it awaits share
    one context — which is the property being tested.
    """
    await ai_vectors._collection_id(_Conn(_row(pii_mode)), "c", USER)
    return pii_ko.get_mode()


def test_a_stricter_collection_tightens_the_request():
    assert _run(_mode_after_gate("block")) == "block"


def test_a_collection_cannot_loosen_the_deployment_default():
    assert _run(_mode_after_gate("off")) == "mask"


@pytest.mark.parametrize("value", [None, "", "sometimes"])
def test_unset_or_nonsense_inherits_rather_than_disabling(value):
    assert _run(_mode_after_gate(value)) == "mask"


def test_the_tightening_does_not_escape_into_the_next_request():
    """Each request gets its own context; one collection set to block must not leave
    every later call in block mode."""
    assert _run(_mode_after_gate("block")) == "block"
    assert _run(_mode_after_gate(None)) == "mask"


def test_the_id_is_still_what_the_gate_returns():
    assert _run(ai_vectors._collection_id(_Conn(_row("block")), "customers", USER)) == "c-1"
