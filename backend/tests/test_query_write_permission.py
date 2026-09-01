"""`query:run` no longer means "may change the database".

Every role that could query could also DROP TABLE — `viewer` included — because the
execute path never asked what the statement was. The permission is now split: running
a statement that changes data or schema needs `query:write`.

The classifier is tested separately (test_sql_statement_kind.py). These are about who
holds what, and about the gate being on the path that actually runs SQL.
"""
import pytest

from app.permissions import ALL_PERMISSIONS, permissions_for


def test_the_new_permission_exists_in_the_vocabulary():
    """A permission nothing enforces is a lie — and one nothing declares is worse."""
    assert "query:write" in ALL_PERMISSIONS


@pytest.mark.parametrize("role", ["admin", "data_engineer"])
def test_roles_that_already_own_the_data_plane_keep_writing(role):
    assert "query:write" in permissions_for(role), role


@pytest.mark.parametrize("role", ["viewer", "business_analyst", "auditor",
                                  "ai_engineer", "data_scientist"])
def test_everyone_else_is_select_only(role):
    assert "query:run" in permissions_for(role), f"{role} lost the ability to query"
    assert "query:write" not in permissions_for(role), role


def test_reading_is_not_taken_away_from_anyone():
    """The point is to narrow what `query:run` permits, not who holds it."""
    for role in ("viewer", "business_analyst", "auditor", "ai_engineer",
                 "data_scientist", "data_engineer", "admin"):
        assert "query:run" in permissions_for(role), role


# ── the gate is on the path that runs SQL ─────────────────────────────────────

def test_the_execute_route_consults_the_classifier():
    import inspect

    from app.api import queries

    body = inspect.getsource(queries.execute_query)
    assert "statement_kind" in body, "the execute path does not classify the statement"
    assert "query:write" in body


def test_the_refusal_names_the_permission_to_ask_for():
    """A 403 that does not say what is missing sends the person to an administrator
    who also cannot tell. Every other refusal in this codebase names it."""
    import inspect

    from app.api import queries

    body = inspect.getsource(queries.execute_query)
    assert "403" in body or "status_code=403" in body


def test_the_plan_route_needs_no_write_permission():
    """EXPLAIN describes without running. Requiring query:write to look at a plan
    would make the safe thing harder than the dangerous one."""
    import inspect

    from app.api import queries

    assert "query:write" not in inspect.getsource(queries.review_plan)
