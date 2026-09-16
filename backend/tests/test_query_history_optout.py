"""`save_history=false` is a person's choice, not an agent's.

POSITIONING_FIT_AUDIT §2.5: "쿼리 이력은 호출자가 끌 수 있음 — 에이전트가 자기 흔적을
지울 수 있다." The tool call log records every execution either way, but query_history is
what the Governance screen reads, and a service account should not be able to keep
itself out of it.
"""
from app.api.queries import _history_is_optional

HUMAN = {"id": "u1", "username": "alice", "auth_method": "local"}
SSO = {"id": "u2", "username": "bob", "auth_method": "oidc"}
SERVICE = {"id": "s1", "username": "svc-bot", "auth_method": "service"}


def test_a_person_may_decline():
    assert _history_is_optional(HUMAN) is True
    assert _history_is_optional(SSO) is True


def test_a_service_account_may_not():
    assert _history_is_optional(SERVICE) is False


def test_an_unknown_caller_is_treated_as_a_person_not_ignored():
    """No auth_method means a human session shape; the service case is explicit."""
    assert _history_is_optional({}) is True
    assert _history_is_optional(None) is True


def test_both_history_branches_consult_it():
    """The error path and the success path each write a row; a guard on only one of
    them would let a failing statement escape the record."""
    import inspect
    from app.api import queries

    src = inspect.getsource(queries._execute_query_impl)
    assert src.count("_history_is_optional(user)") == 2
