"""The roles the product ships with have to exist in the database that ships it.

`roles` is created empty by 0001_baseline, and the only two `INSERT INTO roles`
statements in the repo live in `schema/auth.sql` and `schema/rls_migration.sql` —
files nothing applies any more, since the startup bootstrap that ran them was removed
in favour of Alembic. So on a database built from migrations the table stays empty,
and everything keyed on it fails quietly rather than loudly:

- `GET /governance/rls/roles` returns `[]`, so the policy editor offers no roles.
- Creating a policy with `role_names=["data_scientist"]` runs
  `INSERT INTO rls_policy_roles … SELECT $1, id FROM roles WHERE name = $2` against an
  empty table. Zero rows inserted, no error: the policy binds to nobody and, with
  RLS_DEFAULT_DENY off, filters nothing at all. A governance feature that reports
  success and enforces nothing is worse than one that is missing.

`app/permissions.py` is the source of truth for which roles exist — it is what the API
authorises from — so this file checks the migration against that list rather than
against a copy of it.
"""
import re
from pathlib import Path

import pytest

from app.permissions import KNOWN_ROLES

VERSIONS = Path(__file__).resolve().parents[1] / "migrations/versions"


def _seed_sql() -> str:
    """Every migration's SQL, concatenated — the seed may live in any of them."""
    return "\n".join(p.read_text() for p in sorted(VERSIONS.glob("*.sql")))


def _seeded_roles() -> set:
    sql = _seed_sql()
    seeded = set()
    for block in re.findall(r"INSERT\s+INTO\s+(?:public\.)?roles\b(.*?);", sql,
                            re.I | re.S):
        seeded |= set(re.findall(r"\(\s*'([a-z_]+)'", block))
    return seeded


@pytest.mark.parametrize("role", KNOWN_ROLES)
def test_every_role_the_api_authorises_from_exists_in_the_database(role):
    assert role in _seeded_roles(), (
        f"'{role}' is a role app/permissions.py enforces and no migration creates. "
        "An RLS policy naming it binds to nothing, silently.")


def test_the_seed_can_run_twice():
    """Migrations are re-run against databases that already have rows — an install
    that predates Alembic already carries these roles from schema/auth.sql. Seeding
    has to be a no-op there, not a unique-violation that aborts the upgrade."""
    sql = _seed_sql()
    inserts = re.findall(r"INSERT\s+INTO\s+(?:public\.)?roles\b.*?;", sql, re.I | re.S)
    assert inserts, "no role seed found at all"
    for statement in inserts:
        assert re.search(r"ON\s+CONFLICT", statement, re.I), (
            "a role seed without ON CONFLICT fails the whole migration on any "
            "database that already has these rows")


def test_the_seed_marks_them_as_system_roles():
    """`is_system` is what tells the UI these are not user-defined and must not be
    offered for deletion."""
    sql = _seed_sql()
    block = re.search(r"INSERT\s+INTO\s+(?:public\.)?roles\b(.*?);", sql, re.I | re.S)
    assert block and "is_system" in block.group(1)
