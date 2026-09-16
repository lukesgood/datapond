"""0011 adds the two places a stricter PII mode can be set — checked as text, like 0008-0010."""
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
_RAW = (VERSIONS / "0011_pii_mode_scopes.sql").read_text(encoding="utf-8")
# Prose is not DDL: this file's own comments explain NOT VALID and NULL, and counting
# those sentences as code is how the first version of this test failed.
SQL = "\n".join(line for line in _RAW.splitlines() if not line.lstrip().startswith("--"))
PY_TEXT = (VERSIONS / "0011_pii_mode_scopes.py").read_text(encoding="utf-8")


def test_revision_chain_points_at_the_refused_revision():
    assert 'revision: str = "0011_pii_mode_scopes"' in PY_TEXT
    assert 'down_revision: Union[str, None] = "0010_tool_call_log_refused"' in PY_TEXT


def test_both_scopes_get_a_nullable_column():
    for table in ("public.ai_collections", "public.users"):
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS pii_mode text;" in SQL
    # NULL is "inherit" — no NOT NULL, no DEFAULT, so existing rows change nothing.
    assert "NOT NULL" not in SQL and "DEFAULT" not in SQL  # NULL means inherit


def test_the_value_is_constrained_to_the_vocabulary():
    assert SQL.count("pii_mode IS NULL OR pii_mode IN ('off', 'mask', 'block')") == 2
    assert SQL.count("NOT VALID") == 2


def test_the_downgrade_does_not_drop_a_column():
    assert "DROP COLUMN" not in PY_TEXT
    assert "DROP CONSTRAINT IF EXISTS" in PY_TEXT


def test_no_forbidden_ddl():
    from app.migration_rules import review_migration
    assert review_migration("0011_pii_mode_scopes", SQL, docstring=PY_TEXT) == []
