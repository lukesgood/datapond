"""Two holes in the role matrix, both found by walking a role's day instead of
reading the matrix.

A data_scientist could query a table through Catalog and Analytics but not see
Sources — so "how old is this data?" had no answer for the person analysing it.
Every other role that can query either holds connector:read or is deliberately
read-only.

And they could spend model tokens (ai:generate) while having no way to see what they
had spent. The usage endpoints take no caller argument: they report the whole
deployment's spend and every user's share, which is why simply granting spend:read
would have been the wrong fix.
"""
from app.permissions import ROLE_PERMISSIONS, has_permission


def test_a_data_scientist_can_see_where_their_data_came_from():
    assert has_permission("data_scientist", "connector:read")


def test_everyone_who_queries_can_check_freshness():
    """The rule this encodes: if a role can run a query against a table, it can find
    out when that table was last synced. Anything else asks people to analyse data of
    unknown age."""
    for role, perms in ROLE_PERMISSIONS.items():
        if "query:run" in perms and "connector:read" not in perms:
            assert role in ("viewer", "business_analyst", "auditor"), (
                f"{role} can query but cannot see source freshness")


def test_seeing_sources_is_not_the_same_as_changing_them():
    """The widening is read-only. Nothing about it lets a data_scientist run a sync
    or edit a connector."""
    assert not has_permission("data_scientist", "connector:write")
