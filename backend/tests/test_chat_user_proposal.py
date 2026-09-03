"""A person choosing an action, rather than the model choosing it.

Asking the assistant a data question produced SQL and stopped. That was two faults,
and this file is about the second: there was no way to get from the SQL to an answer.
The model cannot chain — one tool per turn, deliberately, so it cannot run work past a
human — and the panel had no way to say "yes, run that one" other than typing another
sentence and hoping the model reconstructed the same statement.

So the panel can propose an action directly. That is a *narrower* trust boundary than
the model proposing, not a wider one: a person read the SQL and chose it. Everything
downstream is unchanged — the same permission check, the same server-computed preview,
the same approval by invocation id for anything that writes.
"""
import asyncio

import pytest

from app.chat import gate
from app.chat.actions import ActionKind, resolve
from app.chat.gate import ActionRefused, propose


@pytest.fixture(autouse=True)
def _capabilities_on(monkeypatch):
    """This file is about a person choosing an action, not capability gating — which
    has its own tests in test_chat_capability_gate.py. query.generate_sql and
    query.run now carry a capability; hold it open so this environment's actual
    FEATURE_* flags can't fail a test about something else."""
    monkeypatch.setattr(gate, "capability_on", lambda key: True)


class Store:
    """Enough InvocationStore for the gate; no database."""

    def __init__(self):
        self.rows = {}

    async def create(self, **kw):
        row = {"id": f"inv-{len(self.rows)}", **kw}
        self.rows[row["id"]] = row
        return row

    async def get(self, invocation_id):
        return self.rows.get(invocation_id)

    async def update(self, invocation_id, **kw):
        self.rows[invocation_id].update(kw)
        return self.rows[invocation_id]

    async def audit(self, *a, **kw):
        return None


USER = {"id": "u1", "role": "admin"}


def _propose(action_id, params, user=USER, executor=None, previewer=None):
    return asyncio.run(propose(action_id, params, user=user, page="*", store=Store(),
                               executor=executor, previewer=previewer))


def test_a_read_chosen_by_a_person_runs_immediately():
    async def run_it(params, user):
        return {"sql": "SELECT 1", "explanation": "one"}

    inv = _propose("query.generate_sql", {"question": "how many"}, executor=run_it)
    assert inv["status"] == "executed"
    assert inv["result"]["sql"] == "SELECT 1"


def test_a_write_chosen_by_a_person_still_waits_for_approval():
    """The point of the gate is that nothing writes without a second, deliberate act.
    Choosing the action is not that act — approving the invocation is."""
    async def preview(params, user):
        return {"reads": ["sales.orders"], "validated": True}

    inv = _propose("query.run", {"sql": "SELECT 1"}, previewer=preview)
    assert inv["status"] == "proposed"
    assert resolve("query.run").kind is not ActionKind.READ


def test_the_permission_is_checked_the_same_way():
    """Not a viewer — every role in this product holds query:run, which is the point
    of the matrix: reading is broad and writing is what gets withheld. A scoped
    service-account key, whose effective set can be narrower than any role, is the
    caller that can actually be missing it."""
    with pytest.raises(ActionRefused):
        _propose("query.run", {"sql": "SELECT 1"},
                 user={"id": "svc", "role": "viewer", "permissions": []})


def test_an_unknown_action_is_refused_rather_than_attempted():
    with pytest.raises(ActionRefused):
        _propose("query.definitely_not_an_action", {"sql": "SELECT 1"})


def test_parameters_are_validated_against_the_action_model():
    """A client sending the wrong shape is refused here, not somewhere deeper where
    the failure would be a stack trace."""
    with pytest.raises(ActionRefused):
        _propose("query.run", {"not_sql": "SELECT 1"})


# ── where these actions are offered ───────────────────────────────────────────

def test_asking_about_data_works_from_any_page():
    """generate_sql and run were offered on /query only, so the assistant had no SQL
    tool anywhere else — and the panel is on every page. "What does the data say" does
    not depend on which screen you happen to be looking at."""
    from app.chat.actions import actions_for

    perms = {"ai:generate", "query:run"}
    on_knowledge = {a.id for a in actions_for(perms, "/knowledge", {"query": True})}
    assert "query.generate_sql" in on_knowledge
    assert "query.run" in on_knowledge
