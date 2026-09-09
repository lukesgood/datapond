"""Migration 0009, checked as text — there is no database in this test environment."""
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0009_tool_call_log_tool_ids.sql").read_text(encoding="utf-8")
PY = (VERSIONS / "0009_tool_call_log_tool_ids.py").read_text(encoding="utf-8")


def test_revision_chain_points_at_0008():
    assert 'revision: str = "0009_tool_call_log_tool_ids"' in PY
    assert 'down_revision: Union[str, None] = "0008_tool_call_log"' in PY


def test_the_old_constraint_is_found_by_definition_not_by_name():
    """An inline column CHECK is auto-named by PostgreSQL. Dropping a guessed name would
    silently do nothing and leave the old constraint rejecting every new row.

    Asserted by structure, not by keyword presence: those words could all appear in a
    comment while the DO block that actually drops the constraint was deleted, leaving
    0008's constraint in place alongside the new one — every action-id row rejected
    forever in a table nothing can repair.
    """
    assert "pg_constraint" in SQL and "conrelid" in SQL
    assert "DROP CONSTRAINT" in SQL
    execute_pos = SQL.index("EXECUTE format(")
    drop_pos = SQL.index("ALTER TABLE public.tool_call_log DROP CONSTRAINT %I")
    add_pos = SQL.index("ADD CONSTRAINT")
    assert execute_pos < add_pos
    assert drop_pos < add_pos


def test_a_new_constraint_replaces_it_rather_than_nothing():
    assert "ADD CONSTRAINT tool_call_log_tool_check" in SQL
    for tool in ("ai.search", "ai.rag", "ai.sql", "query.execute"):
        assert tool in SQL, tool


def test_every_registered_action_id_satisfies_the_new_pattern():
    """The constraint must not reject a tool the server can legitimately log — and must
    not accept everything either. An unbounded pattern (e.g. `^.+$`, or the anchors
    dropped) would satisfy the positive half of this test while leaving the column
    effectively free text in a table that has no UPDATE to correct it afterwards."""
    import re
    from app.chat.actions import REGISTRY
    pattern = re.search(r"tool ~ '\^(.+?)\$'", SQL)
    assert pattern, "expected a regex branch in the CHECK"
    rx = re.compile("^" + pattern.group(1).replace("\\\\", "\\") + "$")
    for action_id in REGISTRY:
        assert rx.match(action_id), action_id
    for bad in ("", " ", "ai search", "AI.Search", "DROP TABLE x",
                "ai.", ".rag", "a.b.c", "ai.search\n; --"):
        assert not rx.match(bad), bad


def test_no_forbidden_ddl():
    from app.migration_rules import review_migration
    assert review_migration("0009_tool_call_log_tool_ids", SQL) == []
