"""Whether the schema is actually there, not just recorded as there.

Removing the lazy `ensure_*` calls from request paths takes away a self-healing
property: an endpoint used to create its own table if it was missing. That was the
wrong place for DDL — it ran on every request and hid the fact that the schema was
incomplete — but taking it out means a database missing a table now fails at whichever
endpoint touches it first.

alembic_version says migrations ran. It does not say the tables exist: a deployment
where a bootstrap silently failed was stamped at the baseline anyway, because stamping
records a decision rather than an inspection.

So readiness looks.
"""
import pytest

from app.migrations import CORE_TABLES, missing_tables


def test_nothing_missing_is_reported_as_nothing():
    assert missing_tables(present=set(CORE_TABLES)) == []


def test_a_missing_table_is_named():
    present = set(CORE_TABLES) - {"ai_chunks"}
    assert missing_tables(present) == ["ai_chunks"]


def test_several_missing_are_all_named_and_sorted():
    present = set(CORE_TABLES) - {"users", "ai_chunks"}
    assert missing_tables(present) == ["ai_chunks", "users"]


def test_extra_tables_are_not_a_problem():
    """An optional add-on's tables, or something an operator added. The check is that
    what the product needs is present, not that nothing else is."""
    assert missing_tables(set(CORE_TABLES) | {"something_else"}) == []


def test_the_core_list_is_what_the_product_cannot_run_without():
    """Small on purpose. Listing all 41 would make this fail on any deployment that
    has an optional feature switched off, and then nobody would trust it."""
    assert {"users", "ai_collections", "ai_chunks"} <= set(CORE_TABLES)
    assert len(CORE_TABLES) <= 10
