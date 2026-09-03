"""The confirmation gate.

Design §5 and §14. Tested with no model in the loop: the gate is the part that must
be right, and it is right or wrong independently of what any model says.

The property that matters most: **the approved artifact and the executed artifact are
the same server-side record**. If a client could re-send parameters at approval time,
the preview would be decorative.
"""
import asyncio

import pytest

from app.chat import gate
from app.chat.actions import ActionKind
from app.chat.gate import (
    ActionRefused,
    InvocationStore,
    approve,
    propose,
    reject,
)

ADMIN = {"id": "11111111-1111-1111-1111-111111111111", "username": "ada", "role": "admin"}
READER = {"id": "22222222-2222-2222-2222-222222222222", "username": "bo", "role": "viewer"}


@pytest.fixture(autouse=True)
def _capabilities_on(monkeypatch):
    """This file exercises permission and approval mechanics, not capability gating —
    that has its own tests in test_chat_capability_gate.py. Hold every capability open
    here so this environment's actual FEATURE_* flags (usually all off) cannot fail a
    test about something else."""
    monkeypatch.setattr(gate, "capability_on", lambda key: True)


class _Store(InvocationStore):
    """In-memory stand-in; the real one is Postgres."""

    def __init__(self):
        self.rows = {}
        self.audit = []
        self._n = 0

    async def create(self, **fields):
        self._n += 1
        inv = {"id": f"inv-{self._n}", **fields}
        self.rows[inv["id"]] = inv
        return inv

    async def get(self, invocation_id):
        return self.rows.get(invocation_id)

    async def update(self, invocation_id, **fields):
        self.rows[invocation_id].update(fields)
        return self.rows[invocation_id]

    async def claim_for_approval(self, invocation_id, approved_by):
        """The in-memory twin of the Postgres conditional UPDATE.

        There is no await between the read and the write here, which is exactly why
        the concurrency test below drives the store's own method rather than trying
        to interleave two approve() calls: what has to be atomic is this claim, and a
        fake that "wins" twice would prove nothing about the real one.
        """
        row = self.rows.get(invocation_id)
        if not row or row.get("status") != "proposed":
            return None
        row.update(status="approved", approved_by=approved_by)
        return row

    async def record_audit(self, event, user_id, user_email, details):
        self.audit.append({"event": event, "user_id": user_id,
                           "user_email": user_email, "details": details})


def _run(coro):
    return asyncio.run(coro)


# ── proposal ──────────────────────────────────────────────────────────────────

def test_a_read_action_is_executed_without_approval():
    store = _Store()
    executed = []

    async def _exec(params, user):
        executed.append(params)
        return {"columns": ["id"]}

    inv = _run(propose("catalog.describe_table", {"namespace": "sales", "table": "orders"},
                       user=ADMIN, page="/catalog", store=store, executor=_exec))
    assert inv["status"] == "executed"
    assert executed == [{"namespace": "sales", "table": "orders"}]


def test_a_create_action_stops_at_proposed():
    store = _Store()
    executed = []

    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, executor=lambda p, u: executed.append(p),
                       previewer=lambda p, u: {"reads": ["sales.orders"]}))
    assert inv["status"] == "proposed"
    assert inv["preview"] == {"reads": ["sales.orders"]}
    assert executed == [], "nothing runs before a human approves"


def test_a_fabricated_action_is_refused():
    store = _Store()
    with pytest.raises(ActionRefused):
        _run(propose("catalog.drop_everything", {}, user=ADMIN, page="*", store=store))


def test_parameters_that_fail_validation_are_refused():
    store = _Store()
    with pytest.raises(ActionRefused):
        _run(propose("catalog.describe_table", {"namespace": "sales"},
                     user=ADMIN, page="/catalog", store=store))


def test_an_action_the_caller_cannot_use_is_refused_at_proposal():
    """The second gate. The first is that a viewer's model never sees this action."""
    store = _Store()
    with pytest.raises(ActionRefused) as ei:
        _run(propose("knowledge.create_collection", {"name": "x"},
                     user=READER, page="/knowledge", store=store))
    assert "knowledge:write" in str(ei.value)


def test_a_service_account_key_is_bounded_by_its_scopes():
    store = _Store()
    scoped = {"id": "svc", "role": "admin", "permissions": ["catalog:read"]}
    with pytest.raises(ActionRefused):
        _run(propose("dashboard.save", {"name": "n", "sql": "SELECT 1"},
                     user=scoped, page="/query", store=store))


# ── approval ──────────────────────────────────────────────────────────────────

def test_approval_executes_the_parameters_that_were_previewed():
    """A client cannot approve one thing and have another run."""
    store = _Store()
    seen = []

    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, previewer=lambda p, u: {"reads": []}))
    done = _run(approve(inv["id"], user=ADMIN, store=store,
                        executor=lambda p, u: seen.append(p) or {"rows": 1}))

    assert seen == [{"sql": "SELECT 1"}], "the stored parameters are what runs"
    assert done["status"] == "executed"


def test_approving_rechecks_the_permission():
    """Time passes between proposal and approval; a role can change in between.
    dashboard:write is used because a viewer does hold query:run."""
    store = _Store()
    inv = _run(propose("dashboard.save", {"name": "n", "sql": "SELECT 1"},
                       user=ADMIN, page="/query", store=store, previewer=lambda p, u: {}))
    demoted = {**ADMIN, "role": "viewer"}
    with pytest.raises(ActionRefused):
        _run(approve(inv["id"], user=demoted, store=store,
                     executor=lambda p, u: {"rows": 1}))


def test_only_the_person_who_was_offered_the_action_may_approve_it():
    """Otherwise a colleague with the same role could confirm a change someone else
    was asked about — and the audit trail would name the wrong person as approver."""
    store = _Store()
    executed = []
    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, previewer=lambda p, u: {}))
    other_admin = {"id": "33333333-3333-3333-3333-333333333333",
                   "username": "cy", "role": "admin"}
    with pytest.raises(ActionRefused):
        _run(approve(inv["id"], user=other_admin, store=store,
                     executor=lambda p, u: executed.append(p)))
    assert executed == []


def test_only_the_owner_may_reject_it_either():
    store = _Store()
    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, previewer=lambda p, u: {}))
    other = {"id": "33333333-3333-3333-3333-333333333333", "role": "admin"}
    with pytest.raises(ActionRefused):
        _run(reject(inv["id"], user=other, store=store))


def test_a_rejected_invocation_never_executes():
    store = _Store()
    executed = []
    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, previewer=lambda p, u: {}))
    _run(reject(inv["id"], user=ADMIN, store=store))

    with pytest.raises(ActionRefused):
        _run(approve(inv["id"], user=ADMIN, store=store,
                     executor=lambda p, u: executed.append(p)))
    assert executed == []


def test_an_invocation_cannot_be_approved_twice():
    store = _Store()
    runs = []
    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, previewer=lambda p, u: {}))
    _run(approve(inv["id"], user=ADMIN, store=store,
                 executor=lambda p, u: runs.append(1) or {}))
    with pytest.raises(ActionRefused):
        _run(approve(inv["id"], user=ADMIN, store=store,
                     executor=lambda p, u: runs.append(1) or {}))
    assert len(runs) == 1


def test_only_one_of_two_simultaneous_approvals_executes():
    """A double-click, or a client retry, sends approve() twice. Both calls read
    status="proposed" before either writes, so a check-then-act approval runs the
    query — or saves the dashboard — twice, and the message "a request can only be
    approved once" describes an invariant nothing enforces.

    Both halves are pinned: the store's claim admits exactly one winner, and approve()
    goes through that claim rather than an unconditional update. Without the second
    assertion a correct store would still be bypassed by a gate that ignores it.
    """
    import inspect

    from app.chat import gate as gate_module

    store = _Store()
    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, previewer=lambda p, u: {}))

    winners = [_run(store.claim_for_approval(inv["id"], ADMIN["id"])) for _ in range(2)]
    assert [w is not None for w in winners] == [True, False], (
        "two approvals both claimed the same invocation")

    source = inspect.getsource(gate_module.approve)
    assert "claim_for_approval" in source, (
        "approve() still writes status='approved' unconditionally — a correct store "
        "cannot save it")
    assert 'status="approved"' not in source


def test_an_unknown_invocation_is_refused():
    store = _Store()
    with pytest.raises(ActionRefused):
        _run(approve("inv-nope", user=ADMIN, store=store, executor=lambda p, u: {}))


def test_a_failing_execution_is_recorded_rather_than_swallowed():
    store = _Store()

    def _boom(params, user):
        raise RuntimeError("engine unavailable")

    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, previewer=lambda p, u: {}))
    with pytest.raises(ActionRefused):
        _run(approve(inv["id"], user=ADMIN, store=store, executor=_boom))
    assert store.rows[inv["id"]]["status"] == "failed"


# ── audit ─────────────────────────────────────────────────────────────────────

def test_every_step_is_audited_against_the_human_not_the_assistant():
    store = _Store()
    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, previewer=lambda p, u: {}))
    _run(approve(inv["id"], user=ADMIN, store=store, executor=lambda p, u: {"rows": 1}))

    events = [a["event"] for a in store.audit]
    assert "chat_action_proposed" in events
    assert "chat_action_approved" in events
    assert "chat_action_executed" in events
    for entry in store.audit:
        assert entry["user_id"] == ADMIN["id"]
        assert entry["details"].get("via") == "chat"
        # The audit viewer renders user_email. Without it the trail reads
        # "someone executed this", which is the one thing it exists to answer.
        assert entry["user_email"] == ADMIN["username"]


def test_a_refusal_is_audited_too():
    store = _Store()
    with pytest.raises(ActionRefused):
        _run(propose("knowledge.create_collection", {"name": "x"},
                     user=READER, page="/knowledge", store=store))
    assert any(a["event"] == "chat_action_refused" for a in store.audit)


# ── what is kept (design §9) ──────────────────────────────────────────────────

def test_the_request_that_produced_an_action_is_stored_with_it():
    """The only transcript kept: a change needs a reason on record."""
    store = _Store()
    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, previewer=lambda p, u: {},
                       request_text="run the daily totals for me"))
    assert inv["request_text"] == "run the daily totals for me"


def test_an_overlong_request_is_truncated_rather_than_rejected():
    store = _Store()
    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, previewer=lambda p, u: {},
                       request_text="x" * 5000))
    assert len(inv["request_text"]) == 2000


def test_no_request_text_stores_null_rather_than_an_empty_string():
    store = _Store()
    inv = _run(propose("query.run", {"sql": "SELECT 1"}, user=ADMIN, page="/query",
                       store=store, previewer=lambda p, u: {}))
    assert inv["request_text"] is None
