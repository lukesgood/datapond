"""An account with audit history can be deleted, and its audit rows stay as they were.

The audit tables referenced users with ON DELETE SET NULL. Deleting a user therefore
asked Postgres to UPDATE its audit rows, which the append-only trigger (migration
0012) refuses: every service account or user that had ever called a tool, been
authorised or signed in could not be deleted (DELETE /service-accounts/{id} → 500,
found in the live demo rehearsal on 2026-10-01). An audit row must not depend on the
row it describes still existing, so the foreign keys go; the row keeps the id and the
name it was written with.
"""
import re
from pathlib import Path

from app.migration_rules import review_migration

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = VERSIONS / "0022_audit_rows_outlive_users.sql"
PY = VERSIONS / "0022_audit_rows_outlive_users.py"

DROPPED = [
    ("tool_call_log", "tool_call_log_actor_id_fkey"),
    ("security_audit_log", "security_audit_log_actor_id_fkey"),
    ("auth_audit_log", "auth_audit_log_user_id_fkey"),
    ("auth_audit_log", "auth_audit_log_target_user_id_fkey"),
]


def test_the_migration_drops_every_audit_foreign_key_to_users():
    sql = SQL.read_text()
    for table, fk in DROPPED:
        assert re.search(rf"ALTER TABLE public\.{table}\s+DROP CONSTRAINT IF EXISTS {fk}\b", sql), fk


def test_it_follows_the_previous_head_and_passes_review():
    py = PY.read_text()
    assert 'down_revision: Union[str, None] = "0021_catalog_grants"' in py
    assert review_migration("0022_audit_rows_outlive_users", SQL.read_text(), py) == []


def test_no_later_migration_points_an_audit_table_at_users_again():
    for f in sorted(VERSIONS.glob("*.sql")):
        if f.name <= "0022":
            continue
        assert not re.search(r"(tool_call_log|security_audit_log|auth_audit_log)[\s\S]{0,400}REFERENCES\s+public\.users",
                             f.read_text()), f.name
