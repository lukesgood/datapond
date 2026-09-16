"""0012 creates the role 0005 said was needed — checked as text, like 0008-0011.

0005's own honesty note: append-only holds against the application's ordinary code
paths, but not against the role that owns the tables, because an owner can re-grant
itself anything and can drop the trigger. The fix it named is a role that does not own
them, holding SELECT and INSERT only.
"""
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
_RAW = (VERSIONS / "0012_audit_worm_role.sql").read_text(encoding="utf-8")
PY_TEXT = (VERSIONS / "0012_audit_worm_role.py").read_text(encoding="utf-8")
SQL = "\n".join(l for l in _RAW.splitlines() if not l.lstrip().startswith("--"))

AUDIT_TABLES = ("security_audit_log", "auth_audit_log", "tool_call_log")


def test_revision_chain_points_at_the_pii_scopes_revision():
    assert 'revision: str = "0012_audit_worm_role"' in PY_TEXT
    assert 'down_revision: Union[str, None] = "0011_pii_mode_scopes"' in PY_TEXT


def test_the_role_cannot_log_in_until_an_operator_says_so():
    """Creating it must not be a cutover: a role with no login cannot be used by
    accident, and the password is never in a migration."""
    assert "CREATE ROLE datapond_app NOLOGIN" in SQL
    assert "PASSWORD" not in SQL and "LOGIN PASSWORD" not in SQL


def test_creating_it_twice_is_not_an_error():
    assert "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datapond_app')" in SQL


def test_every_audit_table_loses_update_delete_and_truncate():
    revoke = SQL[SQL.index("REVOKE UPDATE, DELETE, TRUNCATE"):]
    for table in AUDIT_TABLES:
        assert f"public.{table}" in revoke, table


def test_the_revoke_comes_after_the_blanket_grant():
    """Order is the whole point: a blanket GRANT after the REVOKE would hand back
    exactly what was taken."""
    assert SQL.index("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES") < SQL.index("REVOKE UPDATE, DELETE, TRUNCATE")


def test_future_tables_are_granted_too():
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA public" in SQL
    assert SQL.count("ALTER DEFAULT PRIVILEGES") >= 2


def test_the_downgrade_does_not_drop_the_role():
    assert "DROP ROLE" not in PY_TEXT


def test_no_forbidden_ddl():
    from app.migration_rules import review_migration
    assert review_migration("0012_audit_worm_role", SQL, docstring=PY_TEXT) == []
