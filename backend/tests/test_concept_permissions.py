"""Who may curate the vocabulary that changes what search returns.

Concept expansion rewrites a user's query before retrieval, so the term list is a
retrieval-quality control. It was admin-only to write and ungated to read — neither
matching the role that is actually accountable for it.

`ai_engineer` already creates collections, ingests into them, and schedules
re-embedding. Being unable to say that "refund" and "전액 환불" are the same thing,
while being responsible for whether the search works, is the wrong line.

The reverse direction matters too: this is the kind of gap the route inventory could
not find. That test asks whether a route has *any* authorization, so a route pinned
to admin when it should not be looks perfectly correct to it.
"""
import pytest

from app.api import ontology


def _gates(path, method):
    route = next(r for r in ontology.router.routes
                 if getattr(r, "path", "") == path and method in r.methods)
    return {getattr(d.call, "__datapond_authorization__", None)
            for d in route.dependant.dependencies}


def test_reading_concepts_needs_knowledge_read():
    """It was require_user — outside the permission vocabulary entirely, so no role
    could be denied it and no role could be granted it deliberately."""
    assert "knowledge:read" in _gates("/ai/concepts", "GET")


@pytest.mark.parametrize("path,method", [
    ("/ai/concepts", "POST"),
    ("/ai/concepts/{name}", "DELETE"),
    ("/ai/concepts/import", "POST"),
])
def test_writing_concepts_needs_knowledge_write(path, method):
    gates = _gates(path, method)
    assert "knowledge:write" in gates, f"{method} {path} gates were {gates}"
    assert "role:admin" not in gates


def test_the_roles_that_build_collections_can_curate_their_vocabulary():
    from app.permissions import has_permission
    for role in ("admin", "ai_engineer", "data_scientist"):
        assert has_permission(role, "knowledge:write"), role


def test_the_roles_that_only_read_cannot():
    from app.permissions import has_permission
    for role in ("viewer", "business_analyst", "auditor", "data_engineer"):
        assert not has_permission(role, "knowledge:write"), role
        # but they can still see why a search expanded the way it did
        assert has_permission(role, "knowledge:read"), role
