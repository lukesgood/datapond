"""Who may read or change a collection — one decision, asked the same way everywhere.

Before this, "may this caller see this collection" was inlined into `_collection_id`
in app/api/ai_vectors.py as `owner_id == user OR owner_id IS NULL OR admin`, and two
other paths (list_collections, knowledge_lineage) rebuilt the same rule from scratch
in raw SQL. `ai_collection_members` (0003_collection_members.sql, A2) adds a third
state — named people, not just the owner or the world — and there was still no single
place that could be wrong instead of several. This module is that place.

The precedence is the whole design; it is written down again in
app/knowledge_access.py's own docstring, and every branch below pins one line of it
so a change to the order fails a test instead of shipping quietly.
"""
from app.knowledge_access import may_read, may_write


ADMIN = {"id": "admin-id", "role": "admin"}
OWNER = {"id": "owner-id", "role": "viewer"}
OTHER = {"id": "other-id", "role": "viewer"}

OWNED = {"owner_id": "owner-id"}
GLOBAL = {"owner_id": None}


def test_admin_may_read_and_write_regardless_of_ownership_or_membership():
    """A private collection admin neither owns nor has a grant on. The role alone
    must be enough — that is what makes admin admin."""
    assert may_read(OWNED, ADMIN, None) is True
    assert may_write(OWNED, ADMIN, None) is True


def test_owner_may_read_and_write_their_own_collection():
    assert may_read(OWNED, OWNER, None) is True
    assert may_write(OWNED, OWNER, None) is True


def test_explicit_editor_may_read_and_write():
    """A membership row is the only thing that can grant access to a private
    collection once admin and owner are ruled out."""
    assert may_read(OWNED, OTHER, "editor") is True
    assert may_write(OWNED, OTHER, "editor") is True


def test_explicit_reader_may_read_but_not_write():
    assert may_read(OWNED, OTHER, "reader") is True
    assert may_write(OWNED, OTHER, "reader") is False


def test_legacy_global_collection_is_readable_by_anyone_holding_knowledge_read():
    """owner_id IS NULL predates membership entirely: the rule since before this
    module existed was 'read for anyone', enforced only by the route's own
    knowledge:read gate. Proven here by actually consulting the permission rather
    than assuming it — monkeypatching has_permission to False must flip the
    answer, or this branch is just returning True unconditionally."""
    assert may_read(GLOBAL, OTHER, None) is True


def test_legacy_global_collection_read_actually_consults_the_permission(monkeypatch):
    import app.knowledge_access as knowledge_access

    monkeypatch.setattr(knowledge_access, "has_permission", lambda role, perm: False)
    assert may_read(GLOBAL, OTHER, None) is False


def test_legacy_global_collection_is_writable_only_by_owner_or_admin():
    """There is no owner to delegate write from, so a non-admin, non-member caller
    never gets to change it — that half of the rule is unchanged from before
    membership existed."""
    assert may_write(GLOBAL, OTHER, None) is False
    assert may_write(GLOBAL, ADMIN, None) is True


def test_a_private_collection_with_no_grant_is_closed_to_read_and_write():
    """The combination that matters most: not the owner, not an admin, no
    membership row at all. This is what 'private' has to mean."""
    assert may_read(OWNED, OTHER, None) is False
    assert may_write(OWNED, OTHER, None) is False


def test_reader_membership_on_a_global_collection_does_not_downgrade_write():
    """Explicit membership is checked before the legacy-global fallback, so a
    reader grant on an ownerless collection still cannot write — reader never
    grants write, full stop, regardless of which branch would otherwise apply."""
    assert may_write(GLOBAL, OTHER, "reader") is False


def test_editor_membership_on_a_global_collection_does_grant_write():
    """The mirror case: explicit editor membership outranks the global fallback,
    so an editor grant on an ownerless collection DOES grant write even though
    'owner_id IS NULL' alone would not."""
    assert may_write(GLOBAL, OTHER, "editor") is True
