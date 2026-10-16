"""Migration 0024: the cap an operator set, shared by every backend pod."""
import re
from pathlib import Path

from app.migration_rules import review_migration

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
PY = VERSIONS / "0024_ai_budget_caps.py"
SQL = VERSIONS / "0024_ai_budget_caps.sql"


def test_files_exist_and_chain_from_0023():
    body = PY.read_text()
    assert 'revision: str = "0024_ai_budget_caps"' in body
    assert 'down_revision: Union[str, None] = "0023_semantic_metrics"' in body
    assert "run_sql_file" in body


def test_it_is_the_highest_revision():
    stems = sorted(p.stem for p in VERSIONS.glob("*.py") if re.fullmatch(r"\d{4}_[a-z0-9_]+", p.stem))
    assert stems[-1] == "0024_ai_budget_caps"


def test_the_table_is_created_idempotently_and_holds_only_set_caps():
    sql = SQL.read_text()
    assert "CREATE TABLE IF NOT EXISTS public.ai_budget_caps" in sql
    assert "user_id     text PRIMARY KEY" in sql
    assert "max_budget  double precision NOT NULL CHECK (max_budget >= 0)" in sql


def test_it_needs_no_contract_note():
    assert review_migration("0024_ai_budget_caps", SQL.read_text(), PY.read_text()) == []
