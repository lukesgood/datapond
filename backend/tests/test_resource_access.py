"""One precedence, asked by collections and by sources.

Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (D2)

A3 wrote the decision for collections in `app/knowledge_access.py`. D2 needs the same
decision for connectors and transforms, and "nearly the same rule in two files" is how
one of them ends up wrong — so the rule moves to `app/resource_access.py` and both ask
it, differing only in an `AccessRules` value that says what an *unowned* resource means
for that kind.

That difference is the whole reason this is parameterised rather than copied, and it is
not cosmetic:

- A collection with `owner_id IS NULL` is the deliberate everyone-can-read artifact,
  and A3 made writing to it admin-only — there is no owner to delegate write from.
- A connector with `owner_id IS NULL` is, right now, *every connector that exists*: the
  column landed in 0006 and nothing backfills it. Admin-only writes there would take
  source management away from every data engineer on every existing deployment on the
  day D2 ships. So an unowned source keeps today's rule — anyone holding
  `connector:write` (or `pipeline:write`) may change it — while an owned one is the
  owner's, and that is what makes newly created sources private.
"""
import pytest

from app.resource_access import KNOWLEDGE, SOURCE, TRANSFORM, may_read, may_write


ADMIN = {"id": "u-admin", "role": "admin"}
OWNER = {"id": "u-owner", "role": "data_engineer"}
OTHER = {"id": "u-other", "role": "data_engineer"}
VIEWER = {"id": "u-viewer", "role": "viewer"}

OWNED = {"owner_id": "u-owner"}
UNOWNED = {"owner_id": None}

ALL_RULES = (KNOWLEDGE, SOURCE, TRANSFORM)


# ── the three branches every kind shares ────────────────────────────────────

@pytest.mark.parametrize("rules", ALL_RULES)
def test_an_admin_reads_and_writes_anything(rules):
    for resource in (OWNED, UNOWNED):
        assert may_read(resource, ADMIN, None, rules) is True
        assert may_write(resource, ADMIN, None, rules) is True


@pytest.mark.parametrize("rules", ALL_RULES)
def test_the_owner_reads_and_writes_their_own(rules):
    assert may_read(OWNED, OWNER, None, rules) is True
    assert may_write(OWNED, OWNER, None, rules) is True


@pytest.mark.parametrize("rules", ALL_RULES)
def test_a_stranger_reads_nothing_they_were_not_given(rules):
    assert may_read(OWNED, OTHER, None, rules) is False
    assert may_write(OWNED, OTHER, None, rules) is False


@pytest.mark.parametrize("rules", ALL_RULES)
def test_a_reader_grant_reads_and_does_not_write(rules):
    assert may_read(OWNED, OTHER, "reader", rules) is True
    assert may_write(OWNED, OTHER, "reader", rules) is False


@pytest.mark.parametrize("rules", ALL_RULES)
def test_an_editor_grant_reads_and_writes(rules):
    assert may_read(OWNED, OTHER, "editor", rules) is True
    assert may_write(OWNED, OTHER, "editor", rules) is True


@pytest.mark.parametrize("rules", ALL_RULES)
def test_a_grant_outranks_the_unowned_fallback(rules):
    """An editor grant on an unowned resource still means editor. Checked before the
    fallback, so the grant is meaningful even where the fallback would already have
    allowed a read — otherwise a grant on a public resource would silently do
    nothing."""
    assert may_write(UNOWNED, VIEWER, "editor", rules) is True


# ── where the kinds differ: what "unowned" means ────────────────────────────

def test_an_unowned_collection_is_read_by_the_permission_the_route_required():
    """Not "anyone": the fallback actually consults knowledge:read. Shown with a
    service-account identity carrying its own (empty) permission set rather than an
    unknown role string — permissions_for() deliberately gives an unrecognised role
    the viewer set, so a made-up role would still hold knowledge:read and would prove
    nothing here."""
    assert may_read(UNOWNED, VIEWER, None, KNOWLEDGE) is True      # viewer has knowledge:read
    scoped_to_nothing = {"id": "svc", "role": "viewer", "permissions": []}
    assert may_read(UNOWNED, scoped_to_nothing, None, KNOWLEDGE) is False


def test_an_unowned_collection_is_written_only_by_an_admin():
    """A3's rule, unchanged: no owner means nobody to delegate write from."""
    assert may_write(UNOWNED, OWNER, None, KNOWLEDGE) is False
    assert may_write(UNOWNED, ADMIN, None, KNOWLEDGE) is True


@pytest.mark.parametrize("rules", (SOURCE, TRANSFORM))
def test_an_unowned_source_is_readable_by_any_authenticated_caller(rules):
    """Every connector and transform that exists today is unowned, and every
    authenticated caller can already see them. D2 must not change that — 0006's
    whole argument for a nullable owner_id was that NULL keeps meaning what it
    means today."""
    assert may_read(UNOWNED, VIEWER, None, rules) is True


def test_an_unowned_connector_is_changed_by_anyone_holding_connector_write():
    """data_engineer holds connector:write and manages every existing (unowned)
    connector today. Admin-only here would be an outage on the day this ships, so
    the unowned fallback keeps today's rule and ownership protects what is created
    from now on."""
    assert may_write(UNOWNED, OWNER, None, SOURCE) is True          # data_engineer
    assert may_write(UNOWNED, VIEWER, None, SOURCE) is False        # no connector:write


def test_an_unowned_transform_is_changed_by_anyone_holding_pipeline_write():
    assert may_write(UNOWNED, OWNER, None, TRANSFORM) is True       # data_engineer
    assert may_write(UNOWNED, VIEWER, None, TRANSFORM) is False     # no pipeline:write


# ── the shapes callers actually pass ────────────────────────────────────────

@pytest.mark.parametrize("rules", ALL_RULES)
def test_owner_comparison_survives_uuid_versus_string(rules):
    """asyncpg hands back a uuid.UUID and the JWT carries a string. Comparing them
    without normalising is how an owner gets locked out of their own resource."""
    import uuid as _uuid

    ident = _uuid.UUID("00000000-0000-0000-0000-0000000000a1")
    assert may_write({"owner_id": ident}, {"id": str(ident), "role": "viewer"}, None, rules) is True


@pytest.mark.parametrize("rules", ALL_RULES)
def test_a_missing_user_or_resource_is_refused_rather_than_crashing(rules):
    assert may_read(None, None, None, rules) is False
    assert may_write(None, None, None, rules) is False


@pytest.mark.parametrize("rules", ALL_RULES)
def test_an_anonymous_caller_does_not_own_an_unowned_resource(rules):
    """Both sides NULL must not read as "the same owner" — that would hand every
    unowned resource to a caller with no id at all."""
    assert may_write(UNOWNED, {"id": None, "role": "viewer"}, None, rules) is False


def test_knowledge_access_still_answers_exactly_as_it_did():
    """app/knowledge_access.py keeps its name and signature — A3's call sites and
    tests go on working — and now delegates here instead of holding a second copy
    of the rule."""
    from app import knowledge_access

    assert knowledge_access.may_read(UNOWNED, VIEWER, None) is True
    assert knowledge_access.may_write(UNOWNED, OWNER, None) is False
    assert knowledge_access.may_write(OWNED, OWNER, None) is True
    assert knowledge_access.may_read(OWNED, OTHER, "reader") is True
