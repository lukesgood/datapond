"""How far one turn may go before it has to stop.

Asked "how many products are there?", the assistant called catalog.find_tables and
the turn ended. From the user's side it looked something up and said nothing — which
is the complaint: it gets partway and stops.

One tool per turn was written for a specific reason, stated in the code: the
assistant must not chain work past a human. That reason is about *approval*. A read
already runs without approval — the human is not in that loop and never was — so
stopping after one read protects nothing and costs the answer.

So a turn continues while the model keeps choosing reads, and stops the moment it
proposes anything else. The bound is what keeps "continue" from meaning "forever".
"""
import pytest

from app.chat.turn import should_continue


def test_a_read_that_ran_lets_the_turn_continue():
    assert should_continue(kind="read", status="executed", step=1, limit=4) is True


def test_a_write_stops_the_turn_for_approval():
    """The whole reason the rule exists. A proposed write parks, and the next thing
    that happens is a person deciding."""
    assert should_continue(kind="create", status="proposed", step=1, limit=4) is False


def test_a_destructive_action_stops_it_too():
    assert should_continue(kind="destructive", status="proposed", step=1, limit=4) is False


def test_a_read_that_failed_stops_rather_than_looping_on_it():
    """Continuing after a failure invites the model to retry the same call with the
    same arguments until the bound runs out, spending on each attempt."""
    assert should_continue(kind="read", status="failed", step=1, limit=4) is False


def test_the_bound_is_reached():
    assert should_continue(kind="read", status="executed", step=4, limit=4) is False


def test_the_bound_is_not_off_by_one():
    assert should_continue(kind="read", status="executed", step=3, limit=4) is True


def test_no_action_at_all_ends_the_turn():
    """The model answered in prose. There is nothing to continue from."""
    assert should_continue(kind=None, status=None, step=1, limit=4) is False


def test_a_limit_of_one_reproduces_the_old_behaviour():
    """So the change can be turned off by configuration rather than by reverting it."""
    assert should_continue(kind="read", status="executed", step=1, limit=1) is False
