# SQL Semantic Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Governed metric definitions that agents query through a deterministic `metric_query` tool. The result carries a citation (metric, version, approver, SQL) that is recorded in `tool_call_log`. `/ai/sql` receives the definitions as context.

**Architecture:**
- Definitions live in three PostgreSQL tables (migration 0023). The version table is append-only.
- A pure module (`app/semantic/`) validates definitions and compiles a version plus a request into one SQL statement. It works on the sqlglot AST and renders in the engine dialect.
- `app/semantic/service.py` checks catalog visibility, compiles, runs the statement through the existing `_execute_query_impl` (write classifier, hidden-catalog refusal, RLS, masking, LIMIT), and writes one audit row.
- Three READ actions expose the service over MCP. A REST router serves the console. `/ai/sql` adds the definitions to its prompt.

**Tech Stack:** FastAPI, asyncpg (via `app.api.connectors.get_db_pool`), sqlglot 26.33, pydantic v2, Alembic + SQL files, Next.js/React (shadcn ui), `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-15-sql-semantic-layer-design.md`

## Global Constraints

- Metric `name` matches `^[a-z][a-z0-9_]{0,62}$`.
- Measure: exactly one top-level aggregate from `SUM`, `COUNT`, `COUNT(DISTINCT …)`, `AVG`, `MIN`, `MAX`. No nested aggregates, subqueries, window functions, multiple statements, or functions outside the allow-list. Columns are bare base-table columns.
- Filters: comparisons, `IN`, `BETWEEN`, `IS [NOT] NULL`, `LIKE`, `AND`/`OR`/`NOT` over base-table columns and literals.
- Grains are a subset of `day, week, month, quarter, year`. `max_period_days` defaults to 366.
- `period` is one of `this_month`, `last_month`, `this_quarter`, `last_quarter`, `this_year`, `last_year`, `last_n_days:N`, or the inclusive range `YYYY-MM-DD..YYYY-MM-DD`.
  - It is required when the version has a `time_column`, refused when longer than `max_period_days`, and refused when the metric has no time column.
  - The time zone comes from env `SEMANTIC_TIMEZONE`, default `Asia/Seoul`.
- Joins are one hop, many-to-one only, within one catalog. Join conditions are copied by value into the version's `dimensions`.
- Agents see only approved current versions. Drafts can be previewed only by their author or by a signed-in admin.
- Visibility follows `CatalogAccess.allows(catalog)`. A hidden metric gets the same 404 text as a missing one: `Unknown metric '<name>'.`
- Approve, retire and join approval use `require_admin`. Keys and IdP tokens never pass it.
- Authoring (create metric, new version, preview) needs `governance:write` **and a person**: a key or IdP token is refused (403) even when it holds the permission. Today only `admin` holds `governance:write`.
- Actions are `metric.list` (`catalog:read`), `metric.describe` (`catalog:read`) and `metric.query` (`query:run`). All are `ActionKind.READ` with `capability="query"`. The MCP read-tool count goes from 26 to 29.
- The audit row has `tool="metric.query"`, `resource_kind="metric"`, `resource=[name]` and `citation_sources=["metric:<name>@v<N>"]`. The compiled SQL goes in `response_text`. No second `query.execute` row is written.
- `/ai/sql` context: at most 20 metrics, the response field `metrics_provided`, a deterministic `suggested_metric`, and audit `citation_sources` entries prefixed `context:metric:`.
- Docs must never call the version table tamper-proof. The owning DB role can disable the trigger.
- Backend tests: `backend/.venv/bin/python -m pytest tests -q --ignore=tests/acceptance`. Frontend: `cd frontend && npm test && npx tsc --noEmit && npm run lint`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A `where` value carrying SQL:** `x' OR 1=1 --` must end up as one quoted literal, never as SQL. Owned by Task 3 (`test_where_values_stay_literals`).
2. **A metric whose base table later loses a column:** execution fails with the engine's error. Describe must report `broken: true` rather than 500. Owned by Task 7 (`test_describe_reports_broken_when_column_missing`).
3. **A draft version requested by an agent key on an admin account:** must be 404, because a delegated credential is not a signed-in admin. Owned by Task 5 (`test_delegated_admin_key_cannot_preview_draft`).
4. **Two dimensions through the same join:** one `LEFT JOIN`, not two. Owned by Task 3 (`test_two_dimensions_share_one_join`).
5. **A timestamp `time_column` at the boundaries of `last_month`:** the range must be half-open (`>= start AND < end`), so the first instant of the current month is excluded. Owned by Task 2 (`test_last_month_is_half_open`) and Task 3 (`test_period_bounds_are_half_open`).

## File Structure

| File | Responsibility |
|---|---|
| `backend/migrations/versions/0023_semantic_metrics.{py,sql}` | tables + append-only trigger |
| `backend/app/semantic/__init__.py` | package marker |
| `backend/app/semantic/model.py` | dataclasses + error types (no I/O) |
| `backend/app/semantic/validate.py` | definition validation on the AST (no I/O) |
| `backend/app/semantic/periods.py` | period → half-open date range (no I/O) |
| `backend/app/semantic/compile.py` | version + request → SQL + citation (no I/O) |
| `backend/app/semantic/store.py` | asyncpg reads/writes of the three tables |
| `backend/app/semantic/service.py` | visibility, compile, execute, audit; list/describe |
| `backend/app/chat/analysis/metrics.py` | the three actions |
| `backend/app/api/semantic.py` | REST router for the console |
| `backend/app/api/queries.py` | +RLS-applied holder, +`metric` origin, relationships excludes `metric` |
| `backend/app/api/ai_sql.py` | metric context, `metrics_provided`, `suggested_metric`, audit |
| `frontend/lib/metrics.ts` | pure view helpers + types |
| `frontend/app/metrics/page.tsx` | console page |
| `frontend/lib/nav-items.ts` | menu entry |
| `frontend/app/query/page.tsx` | provided-definitions chip + "Query as metric" |

---

### Task 0: Baseline measurement (before any code)

This runs against the live node, which is up weekdays 07:30–18:00 KST, and spends Bedrock tokens. Get the user's go-ahead before running it. If the go-ahead is withheld, record "baseline not taken" in the appendix and continue.

**Files:**
- Create: `docs/superpowers/specs/2026-10-15-sql-semantic-layer-baseline.md`

- [ ] **Step 1: Write 20 metric-style questions with reference SQL** over the live sample tables (`sales.orders`, `sales.customers` and others from `app/sample_data.py`). Examples: "지난달 지역별 매출", "이번 분기 채널별 주문 수". Put each question and its reference SQL in the baseline file as a table.
- [ ] **Step 2: Ask each question three times** through `POST /api/ai/sql` as a short-lived service account. The account is created and deleted over SSM, the same way as earlier probes (`aws-live-deploy-mechanism` memory). Record each SQL.
- [ ] **Step 3: Score each answer.** Accuracy means the result set equals the reference result. Agreement means all three SQLs return the same result. Write totals at the top of the file.
- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-15-sql-semantic-layer-baseline.md
git commit -m "docs: /ai/sql baseline for the semantic layer (20 questions x3)"
```

---

### Task 1: Migration 0023 — tables and append-only versions

**Files:**
- Create: `backend/migrations/versions/0023_semantic_metrics.py`
- Create: `backend/migrations/versions/0023_semantic_metrics.sql`
- Test: `backend/tests/test_semantic_migration.py`
- Test: `backend/tests/test_semantic_migration_pg.py` (opt-in, real PostgreSQL)

**Interfaces:**
- Produces: tables `semantic_metrics`, `semantic_metric_versions`, `semantic_joins`; trigger function `public.reject_metric_version_mutation()`.

- [ ] **Step 1: Write the failing text tests**

```python
# backend/tests/test_semantic_migration.py
"""Migration 0023: the semantic layer's tables, and versions that cannot be edited."""
import re
from pathlib import Path

from app.migration_rules import review_migration

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
PY = VERSIONS / "0023_semantic_metrics.py"
SQL = VERSIONS / "0023_semantic_metrics.sql"


def _sql() -> str:
    return SQL.read_text()


def test_files_exist_and_chain_from_0022():
    body = PY.read_text()
    assert 'revision: str = "0023_semantic_metrics"' in body
    assert 'down_revision: Union[str, None] = "0022_audit_rows_outlive_users"' in body
    assert "run_sql_file" in body


def test_it_is_the_highest_revision():
    stems = sorted(p.stem for p in VERSIONS.glob("*.py") if re.fullmatch(r"\d{4}_[a-z0-9_]+", p.stem))
    assert stems[-1] == "0023_semantic_metrics"


def test_three_tables_are_created_idempotently():
    sql = _sql()
    for table in ("semantic_metrics", "semantic_metric_versions", "semantic_joins"):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in sql


def test_metric_names_are_constrained_in_the_database():
    assert "^[a-z][a-z0-9_]{0,62}$" in _sql()


def test_versions_have_an_update_and_delete_trigger():
    sql = _sql()
    assert "BEFORE UPDATE OR DELETE ON public.semantic_metric_versions" in sql
    assert "reject_metric_version_mutation" in sql


def test_no_foreign_key_to_users():
    """Like the audit tables after 0022: deleting a user must not need to touch a version."""
    assert "REFERENCES public.users" not in _sql()


def test_migration_rules_do_not_flag_it():
    assert review_migration("0023_semantic_metrics", _sql(), PY.read_text()) == []
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_migration.py -q`
Expected: FAIL (`FileNotFoundError` for `0023_semantic_metrics.py`).

- [ ] **Step 3: Write the migration**

```python
# backend/migrations/versions/0023_semantic_metrics.py
"""Semantic layer: governed metric definitions, their versions, approved joins.

Revision ID: 0023_semantic_metrics
Revises: 0022_audit_rows_outlive_users
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0023_semantic_metrics"
down_revision: Union[str, None] = "0022_audit_rows_outlive_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # Not dropped: a version is what an audit row's `metric:<name>@v<N>` points at.
    # Dropping the tables would leave every such citation unresolvable.
    pass
```

```sql
-- backend/migrations/versions/0023_semantic_metrics.sql
-- Governed metric definitions (docs/superpowers/specs/2026-10-15-sql-semantic-layer-design.md).
--
-- A version is what an audit citation `metric:<name>@v<N>` names, so it must reproduce
-- the same SQL for as long as that row exists. Hence: versions are append-only, and a
-- dimension's join condition is copied into the version rather than referenced.
--
-- Append-only here is the same strength as the audit tables (0005): it stops the
-- application's normal code paths. The role that owns the table can still disable the
-- trigger. Never describe it as tamper-proof.
--
-- No foreign keys to users: like the audit tables after 0022, a version keeps the id
-- and the name it was written with, and deleting a user must not need to update it.

CREATE TABLE IF NOT EXISTS public.semantic_metrics (
    id               serial PRIMARY KEY,
    name             text NOT NULL UNIQUE CHECK (name ~ '^[a-z][a-z0-9_]{0,62}$'),
    label            text NOT NULL,
    description      text NOT NULL DEFAULT '',
    synonyms         text[] NOT NULL DEFAULT '{}',
    owner_id         uuid,
    owner_name       text,
    status           text NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft', 'approved', 'retired')),
    current_version  integer,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.semantic_metric_versions (
    metric_id         integer NOT NULL REFERENCES public.semantic_metrics(id),
    version           integer NOT NULL CHECK (version >= 1),
    catalog           text NOT NULL,
    base_table        text NOT NULL,
    measure           text NOT NULL,
    filters           text,
    time_column       text,
    grains            text[] NOT NULL DEFAULT '{}',
    max_period_days   integer NOT NULL DEFAULT 366 CHECK (max_period_days BETWEEN 1 AND 3660),
    dimensions        jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_by        uuid,
    created_by_name   text,
    change_note       text NOT NULL DEFAULT '',
    created_at        timestamptz NOT NULL DEFAULT now(),
    approved_by       uuid,
    approved_by_name  text,
    approved_at       timestamptz,
    PRIMARY KEY (metric_id, version)
);

CREATE TABLE IF NOT EXISTS public.semantic_joins (
    id                serial PRIMARY KEY,
    catalog           text NOT NULL,
    from_table        text NOT NULL,
    to_table          text NOT NULL,
    on_columns        jsonb NOT NULL,
    source            text NOT NULL CHECK (source IN ('history', 'naming', 'manual')),
    approved_by       uuid,
    approved_by_name  text,
    approved_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (catalog, from_table, to_table, on_columns)
);

-- The one permitted UPDATE: approving an unapproved version, changing nothing else.
CREATE OR REPLACE FUNCTION public.reject_metric_version_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.approved_at IS NULL AND NEW.approved_at IS NOT NULL
       AND (to_jsonb(NEW) - 'approved_by' - 'approved_by_name' - 'approved_at')
         = (to_jsonb(OLD) - 'approved_by' - 'approved_by_name' - 'approved_at') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'metric_version_append_only: % on %.% is not permitted; write a new version',
        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

DROP TRIGGER IF EXISTS semantic_metric_versions_append_only ON public.semantic_metric_versions;
CREATE TRIGGER semantic_metric_versions_append_only
    BEFORE UPDATE OR DELETE ON public.semantic_metric_versions
    FOR EACH ROW EXECUTE FUNCTION public.reject_metric_version_mutation();
```

- [ ] **Step 4: Run the text tests and confirm they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_migration.py -q`
Expected: 7 passed. If `test_it_chains_from_the_highest_revision_actually_present` in `tests/test_audit_append_only.py` or a similar chain test breaks, read its assertion. Those tests pin their own revision, so they should not break.

- [ ] **Step 5: Write the opt-in real-PostgreSQL test**

```python
# backend/tests/test_semantic_migration_pg.py
"""0023 against a real PostgreSQL. Opt-in: set DATAPOND_TEST_PG_DSN to a scratch
database (it is dropped and recreated schema-wise). CI's fresh-install job runs the
migration for real; this proves the trigger's behaviour locally."""
import asyncio
import os
from pathlib import Path

import pytest

DSN = os.environ.get("DATAPOND_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="DATAPOND_TEST_PG_DSN not set")
SQL = (Path(__file__).resolve().parents[1] / "migrations" / "versions"
       / "0023_semantic_metrics.sql").read_text()


async def _fresh():
    import asyncpg
    conn = await asyncpg.connect(DSN)
    await conn.execute("DROP TABLE IF EXISTS public.semantic_metric_versions, "
                       "public.semantic_joins, public.semantic_metrics CASCADE")
    await conn.execute(SQL)
    await conn.execute(SQL)                      # idempotent
    mid = await conn.fetchval(
        "INSERT INTO semantic_metrics (name, label) VALUES ('revenue', '매출') RETURNING id")
    await conn.execute(
        "INSERT INTO semantic_metric_versions (metric_id, version, catalog, base_table, measure) "
        "VALUES ($1, 1, 'glue', 'sales.orders', 'SUM(amount)')", mid)
    return conn, mid


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_approving_an_unapproved_version_is_allowed():
    async def go():
        conn, mid = await _fresh()
        await conn.execute("UPDATE semantic_metric_versions SET approved_by_name='root', "
                           "approved_at=now() WHERE metric_id=$1 AND version=1", mid)
        await conn.close()
    _run(go())


def test_editing_a_version_is_refused():
    import asyncpg

    async def go():
        conn, mid = await _fresh()
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute("UPDATE semantic_metric_versions SET measure='SUM(x)' "
                               "WHERE metric_id=$1", mid)
        await conn.close()
    _run(go())


def test_approving_twice_is_refused():
    import asyncpg

    async def go():
        conn, mid = await _fresh()
        await conn.execute("UPDATE semantic_metric_versions SET approved_at=now() WHERE metric_id=$1", mid)
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute("UPDATE semantic_metric_versions SET approved_at=now(), "
                               "approved_by_name='other' WHERE metric_id=$1", mid)
        await conn.close()
    _run(go())


def test_deleting_a_version_is_refused():
    import asyncpg

    async def go():
        conn, mid = await _fresh()
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute("DELETE FROM semantic_metric_versions WHERE metric_id=$1", mid)
        await conn.close()
    _run(go())


def test_bad_metric_name_is_refused_by_the_database():
    import asyncpg

    async def go():
        conn, _ = await _fresh()
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute("INSERT INTO semantic_metrics (name, label) VALUES ('Bad-Name', 'x')")
        await conn.close()
    _run(go())
```

- [ ] **Step 6: Run it against a local scratch database**

```bash
createdb dp_semantic_test 2>/dev/null || true
cd backend && DATAPOND_TEST_PG_DSN=postgresql://localhost/dp_semantic_test .venv/bin/python -m pytest tests/test_semantic_migration_pg.py -q
```
Expected: 5 passed. Without the env var: 5 skipped.

- [ ] **Step 7: Commit**

```bash
git add backend/migrations/versions/0023_semantic_metrics.py backend/migrations/versions/0023_semantic_metrics.sql backend/tests/test_semantic_migration.py backend/tests/test_semantic_migration_pg.py
git commit -m "feat(semantic): migration 0023 — metric tables, append-only versions"
```

---

### Task 2: Model, validation and periods (pure)

**Files:**
- Create: `backend/app/semantic/__init__.py` (empty)
- Create: `backend/app/semantic/model.py`
- Create: `backend/app/semantic/validate.py`
- Create: `backend/app/semantic/periods.py`
- Test: `backend/tests/test_semantic_validate.py`
- Test: `backend/tests/test_semantic_periods.py`

**Interfaces:**
- Produces:
  - `model.GRAINS: tuple[str, ...]`
  - `model.DefinitionError(field: str, message: str)` with `.field`
  - `model.MetricInputError(message: str, allowed: dict | None)` with `.allowed`
  - `model.Join(to_table: str, on: tuple[tuple[str, str], ...])`
  - `model.Dimension(name: str, column: str, join: Join | None = None)`
  - `model.MetricVersion(metric, version, catalog, base_table, measure, filters=None, time_column=None, grains=(), max_period_days=366, dimensions=(), approved_by=None, approved_at=None, created_by=None)` with `.dimension(name) -> Dimension | None`
  - `validate.check_name(name) -> str`
  - `validate.validate_measure(text, columns, dialect) -> exp.Expression`
  - `validate.validate_filters(text, columns, dialect) -> exp.Expression | None`
  - `validate.validate_grains(grains) -> tuple[str, ...]`
  - `validate.AGGREGATES`
  - `periods.resolve_period(period: str, today: date) -> tuple[date, date]` (half-open)
  - `periods.NAMED`

- [ ] **Step 1: Write the failing validation tests**

```python
# backend/tests/test_semantic_validate.py
"""What a metric definition may contain. Decided on node types, never on strings."""
import pytest

from app.semantic.model import DefinitionError
from app.semantic.validate import check_name, validate_filters, validate_grains, validate_measure

COLS = ["amount", "status", "channel", "ordered_at"]


@pytest.mark.parametrize("text", [
    "SUM(amount)", "COUNT(*)", "COUNT(DISTINCT channel)", "AVG(CAST(amount AS DOUBLE))",
    "SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END)", "MAX(COALESCE(amount, 0) * 2)",
])
def test_accepted_measures(text):
    validate_measure(text, COLS, "athena")


@pytest.mark.parametrize("text,needle", [
    ("SUM(amount) OVER ()", "one aggregate"),
    ("SUM((SELECT 1))", "SUBQUERY"),
    ("SUM(SUM(amount))", "Nested"),
    ("APPROX_DISTINCT(amount)", "one aggregate"),
    ("amount", "one aggregate"),
    ("SUM(amount); DROP TABLE x", "no ';'"),
    ("SUM(o.amount)", "bare column"),
    ("SUM(nope)", "Unknown column"),
    ("SUM(*)", "COUNT(*)"),
    ("", "Required"),
])
def test_refused_measures(text, needle):
    with pytest.raises(DefinitionError) as e:
        validate_measure(text, COLS, "athena")
    assert e.value.field == "measure"
    assert needle in str(e.value)


def test_column_match_ignores_case():
    validate_measure("SUM(Amount)", COLS, "athena")


@pytest.mark.parametrize("text", [
    "status = 'paid'", "status = 'paid' AND amount > 0", "channel IN ('web', 'app')",
    "amount BETWEEN 1 AND 10", "channel IS NOT NULL", "channel LIKE 'w%'", "NOT status = 'void'",
])
def test_accepted_filters(text):
    assert validate_filters(text, COLS, "athena") is not None


@pytest.mark.parametrize("text,needle", [
    ("SUM(amount) > 0", "SUM"),
    ("amount", "condition"),
    ("status IN (SELECT 1)", "SUBQUERY"),
    ("nope = 1", "Unknown column"),
])
def test_refused_filters(text, needle):
    with pytest.raises(DefinitionError) as e:
        validate_filters(text, COLS, "athena")
    assert e.value.field == "filters" and needle in str(e.value)


def test_empty_filters_mean_none():
    assert validate_filters("  ", COLS, "athena") is None
    assert validate_filters(None, COLS, "athena") is None


@pytest.mark.parametrize("name", ["revenue", "a", "order_count_2"])
def test_good_names(name):
    assert check_name(name) == name


@pytest.mark.parametrize("name", ["Revenue", "1x", "_x", "a-b", "a" * 64, ""])
def test_bad_names(name):
    with pytest.raises(DefinitionError):
        check_name(name)


def test_grains_are_deduplicated_and_checked():
    assert validate_grains(["month", "day", "month"]) == ("month", "day")
    with pytest.raises(DefinitionError):
        validate_grains(["hour"])
```

- [ ] **Step 2: Write the failing period tests**

```python
# backend/tests/test_semantic_periods.py
from datetime import date

import pytest

from app.semantic.model import MetricInputError
from app.semantic.periods import resolve_period

TODAY = date(2026, 10, 15)


@pytest.mark.parametrize("period,start,end", [
    ("this_month", date(2026, 10, 1), date(2026, 11, 1)),
    ("last_month", date(2026, 9, 1), date(2026, 10, 1)),
    ("this_quarter", date(2026, 10, 1), date(2027, 1, 1)),
    ("last_quarter", date(2026, 7, 1), date(2026, 10, 1)),
    ("this_year", date(2026, 1, 1), date(2027, 1, 1)),
    ("last_year", date(2025, 1, 1), date(2026, 1, 1)),
    ("last_n_days:7", date(2026, 10, 9), date(2026, 10, 16)),
    ("2026-01-01..2026-03-31", date(2026, 1, 1), date(2026, 4, 1)),
])
def test_named_and_explicit_periods(period, start, end):
    assert resolve_period(period, TODAY) == (start, end)


def test_last_month_is_half_open():
    start, end = resolve_period("last_month", TODAY)
    assert end == date(2026, 10, 1)       # compared with <, so Oct 1 00:00 is excluded


def test_january_last_month_crosses_the_year():
    assert resolve_period("last_month", date(2026, 1, 20)) == (date(2025, 12, 1), date(2026, 1, 1))


@pytest.mark.parametrize("period", ["yesterday", "last_n_days:0", "2026-03-31..2026-01-01",
                                    "2026-13-01..2026-12-01", "", "last_n_days:x"])
def test_bad_periods(period):
    with pytest.raises(MetricInputError):
        resolve_period(period, TODAY)


def test_unknown_period_lists_the_allowed_forms():
    with pytest.raises(MetricInputError) as e:
        resolve_period("yesterday", TODAY)
    assert "last_month" in e.value.allowed["period"]
```

- [ ] **Step 3: Run both and confirm they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_validate.py tests/test_semantic_periods.py -q`
Expected: collection errors (`ModuleNotFoundError: No module named 'app.semantic'`).

- [ ] **Step 4: Implement `model.py`**

```python
# backend/app/semantic/model.py
"""Metric definitions as the compiler sees them. No I/O."""
from dataclasses import dataclass
from typing import Optional, Tuple

GRAINS: Tuple[str, ...] = ("day", "week", "month", "quarter", "year")


class DefinitionError(ValueError):
    """A definition that cannot be saved. `field` names the input at fault (422)."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


class MetricInputError(ValueError):
    """A query the definition does not allow (400). `allowed` lets an agent correct
    itself without a second describe call."""

    def __init__(self, message: str, allowed: Optional[dict] = None):
        super().__init__(message)
        self.allowed = allowed or {}


@dataclass(frozen=True)
class Join:
    to_table: str                              # "schema.table", same catalog
    on: Tuple[Tuple[str, str], ...]            # (base column, target column) pairs


@dataclass(frozen=True)
class Dimension:
    name: str
    column: str
    join: Optional[Join] = None


@dataclass(frozen=True)
class MetricVersion:
    metric: str
    version: int
    catalog: str                               # registry name
    base_table: str                            # "schema.table"
    measure: str
    filters: Optional[str] = None
    time_column: Optional[str] = None
    grains: Tuple[str, ...] = ()
    max_period_days: int = 366
    dimensions: Tuple[Dimension, ...] = ()
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    created_by: Optional[str] = None           # user id, for the draft-preview rule

    def dimension(self, name: str) -> Optional[Dimension]:
        return next((d for d in self.dimensions if d.name == name), None)
```

- [ ] **Step 5: Implement `validate.py`**

```python
# backend/app/semantic/validate.py
"""What a metric definition may contain, decided on the parsed tree.

Strings are never searched for keywords: `SUM(amount)` and `SUM((SELECT …))` differ
only in their node types, so node types are what is checked. Anything not on an
allow-list is refused — a node type sqlglot adds later is refused until someone adds
it here.
"""
import re
from typing import Iterable, Optional

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.semantic.model import GRAINS, DefinitionError

NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
AGGREGATES = (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)

_SCALAR = (exp.Column, exp.Identifier, exp.Literal, exp.Null, exp.Boolean, exp.Paren,
           exp.Neg, exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Cast, exp.DataType,
           exp.Coalesce, exp.Case, exp.If)
_PREDICATE = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.In, exp.Between,
              exp.Is, exp.Like, exp.And, exp.Or, exp.Not)

MEASURE_NODES = _SCALAR + _PREDICATE + AGGREGATES + (exp.Distinct, exp.Star)
FILTER_NODES = _SCALAR + _PREDICATE


def check_name(name: str) -> str:
    if not isinstance(name, str) or not NAME.match(name):
        raise DefinitionError("name", "Use lowercase letters, digits and _; start with a "
                                      "letter; at most 63 characters.")
    return name


def _parse_one(field: str, text: Optional[str], dialect: str) -> exp.Expression:
    if not isinstance(text, str) or not text.strip():
        raise DefinitionError(field, "Required.")
    try:
        trees = [t for t in sqlglot.parse(text, dialect=dialect) if t is not None]
    except ParseError as e:
        raise DefinitionError(field, f"Not a valid expression: {str(e).splitlines()[0][:200]}")
    if len(trees) != 1:
        raise DefinitionError(field, "Exactly one expression; no ';'.")
    return trees[0]


def _check_nodes(field: str, tree: exp.Expression, allowed: tuple, columns: set) -> None:
    for node in tree.walk():
        if not isinstance(node, allowed):
            raise DefinitionError(field, f"{node.key.upper()} is not allowed here.")
        if isinstance(node, exp.Column):
            if node.table:
                raise DefinitionError(field, f"Use bare column names of the base table, not {node.sql()}.")
            if node.name.lower() not in columns:
                raise DefinitionError(field, f"Unknown column {node.name!r} on the base table.")
        if isinstance(node, exp.Star) and not isinstance(node.parent, exp.Count):
            raise DefinitionError(field, "* is allowed only as COUNT(*).")


def validate_measure(text: str, columns: Iterable[str], dialect: str) -> exp.Expression:
    cols = {c.lower() for c in columns}
    tree = _parse_one("measure", text, dialect)
    if not isinstance(tree, AGGREGATES):
        raise DefinitionError("measure", "Must be one aggregate: SUM, COUNT, AVG, MIN or MAX.")
    _check_nodes("measure", tree, MEASURE_NODES, cols)
    if sum(1 for n in tree.walk() if isinstance(n, AGGREGATES)) != 1:
        raise DefinitionError("measure", "Nested aggregates are not allowed.")
    return tree


def validate_filters(text: Optional[str], columns: Iterable[str],
                     dialect: str) -> Optional[exp.Expression]:
    if text is None or not str(text).strip():
        return None
    cols = {c.lower() for c in columns}
    tree = _parse_one("filters", text, dialect)
    _check_nodes("filters", tree, FILTER_NODES, cols)
    if not isinstance(tree, _PREDICATE):
        raise DefinitionError("filters", "Must be a condition, e.g. status = 'paid'.")
    return tree


def validate_grains(grains: Iterable[str]) -> tuple:
    out = tuple(dict.fromkeys(grains or ()))
    bad = [g for g in out if g not in GRAINS]
    if bad:
        raise DefinitionError("grains", f"Unknown grain(s) {bad}; use {list(GRAINS)}.")
    return out
```

- [ ] **Step 6: Implement `periods.py`**

```python
# backend/app/semantic/periods.py
"""`period` as a half-open date range [start, end). No I/O; `today` is passed in, so the
same request on the same day gives the same SQL."""
import re
from datetime import date, timedelta
from typing import Tuple

from app.semantic.model import MetricInputError

NAMED = ("this_month", "last_month", "this_quarter", "last_quarter", "this_year", "last_year")
_LAST_N = re.compile(r"^last_n_days:(\d{1,4})$")
_RANGE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")
FORMS = list(NAMED) + ["last_n_days:N", "YYYY-MM-DD..YYYY-MM-DD"]


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def resolve_period(period: str, today: date) -> Tuple[date, date]:
    p = str(period or "").strip()
    m = _RANGE.match(p)
    if m:
        try:
            start = date.fromisoformat(m.group(1))
            end = date.fromisoformat(m.group(2)) + timedelta(days=1)   # `to` is inclusive
        except ValueError:
            raise MetricInputError("period has an invalid date.", {"period": FORMS})
        if end <= start:
            raise MetricInputError("period ends before it starts.", {"period": FORMS})
        return start, end
    m = _LAST_N.match(p)
    if m:
        n = int(m.group(1))
        if n < 1:
            raise MetricInputError("last_n_days needs N >= 1.", {"period": FORMS})
        return today - timedelta(days=n - 1), today + timedelta(days=1)
    month0 = today.replace(day=1)
    quarter0 = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    ranges = {
        "this_month": (month0, _add_months(month0, 1)),
        "last_month": (_add_months(month0, -1), month0),
        "this_quarter": (quarter0, _add_months(quarter0, 3)),
        "last_quarter": (_add_months(quarter0, -3), quarter0),
        "this_year": (date(today.year, 1, 1), date(today.year + 1, 1, 1)),
        "last_year": (date(today.year - 1, 1, 1), date(today.year, 1, 1)),
    }
    if p in ranges:
        return ranges[p]
    raise MetricInputError(f"Unknown period {p!r}.", {"period": FORMS})
```

- [ ] **Step 7: Run both test files and confirm they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_validate.py tests/test_semantic_periods.py -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/semantic/__init__.py backend/app/semantic/model.py backend/app/semantic/validate.py backend/app/semantic/periods.py backend/tests/test_semantic_validate.py backend/tests/test_semantic_periods.py
git commit -m "feat(semantic): definition validation on the AST, half-open periods"
```

---

### Task 3: The compiler (pure)

**Files:**
- Create: `backend/app/semantic/compile.py`
- Test: `backend/tests/test_semantic_compile.py`

**Interfaces:**
- Consumes: Task 2 `MetricVersion`, `Dimension`, `Join`, `MetricInputError`, `resolve_period`.
- Produces:
  - `compile.CompiledQuery(sql: str, citation: dict)`. The citation has keys `metric`, `version`, `approved_by`, `approved_at`, `sql`, `period` (`[start_iso, end_iso]` or None).
  - `compile.compile_metric(v, *, engine_catalog: str, dialect: str, today: date, by: Sequence[str] = (), period: str | None = None, grain: str | None = None, where: Sequence[dict] = ()) -> CompiledQuery`
  - `compile.OPS = ("=", "!=", "in", ">", "<", "between")`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_semantic_compile.py
"""Version + request -> SQL. Deterministic, dialect-aware, no caller text spliced in."""
from datetime import date

import pytest

from app.semantic.compile import compile_metric
from app.semantic.model import Dimension, Join, MetricInputError, MetricVersion

CUST = Join("sales.customers", (("customer_id", "id"),))
V = MetricVersion(
    metric="revenue", version=3, catalog="glue", base_table="sales.orders",
    measure="SUM(amount)", filters="status = 'paid'", time_column="ordered_at",
    grains=("month",), max_period_days=366,
    dimensions=(Dimension("channel", "channel"), Dimension("region", "region", CUST),
                Dimension("segment", "segment", CUST)),
    approved_by="root", approved_at="2026-10-15T00:00:00+00:00")
TODAY = date(2026, 10, 15)


def _c(**kw):
    kw.setdefault("period", "last_month")
    return compile_metric(V, engine_catalog="AwsDataCatalog", dialect="athena", today=TODAY, **kw)


def test_total_without_dimensions():
    assert _c().sql == (
        'SELECT SUM("b"."amount") AS "revenue" FROM "AwsDataCatalog"."sales"."orders" AS "b" '
        "WHERE (\"b\".\"status\" = 'paid') AND \"b\".\"ordered_at\" >= CAST('2026-09-01' AS DATE) "
        "AND \"b\".\"ordered_at\" < CAST('2026-10-01' AS DATE)")


def test_grain_join_and_dimensions():
    sql = _c(by=["region", "channel"], grain="month").sql
    assert sql.startswith('SELECT DATE_TRUNC(\'month\', "b"."ordered_at") AS "month", '
                          '"j1"."region" AS "region", "b"."channel" AS "channel", '
                          'SUM("b"."amount") AS "revenue"')
    assert 'LEFT JOIN "AwsDataCatalog"."sales"."customers" AS "j1" ON "b"."customer_id" = "j1"."id"' in sql
    assert sql.endswith("GROUP BY 1, 2, 3 ORDER BY 1, 2, 3")


def test_two_dimensions_share_one_join():
    sql = _c(by=["region", "segment"]).sql
    assert sql.count("LEFT JOIN") == 1
    assert '"j1"."segment"' in sql


def test_period_bounds_are_half_open():
    sql = _c().sql
    assert ">= CAST('2026-09-01' AS DATE)" in sql and "< CAST('2026-10-01' AS DATE)" in sql
    assert "<= CAST" not in sql


def test_trino_dialect_renders_too():
    sql = compile_metric(V, engine_catalog="iceberg", dialect="trino", today=TODAY,
                         period="last_month").sql
    assert 'FROM "iceberg"."sales"."orders" AS "b"' in sql


def test_same_input_same_sql():
    assert _c(by=["channel"]).sql == _c(by=["channel"]).sql


def test_where_values_stay_literals():
    sql = _c(where=[{"dimension": "channel", "op": "in", "value": ["web", "x' OR 1=1 --"]}]).sql
    assert "IN ('web', 'x'' OR 1=1 --')" in sql


@pytest.mark.parametrize("op,value,expected", [
    ("=", "web", "\"b\".\"channel\" = 'web'"),
    ("!=", "web", "\"b\".\"channel\" <> 'web'"),
    (">", 5, "\"b\".\"channel\" > 5"),
    ("between", [1, 2], "\"b\".\"channel\" BETWEEN 1 AND 2"),
])
def test_where_ops(op, value, expected):
    assert expected in _c(where=[{"dimension": "channel", "op": op, "value": value}]).sql


def test_citation_carries_version_and_period():
    c = _c().citation
    assert (c["metric"], c["version"], c["approved_by"]) == ("revenue", 3, "root")
    assert c["period"] == ["2026-09-01", "2026-10-01"] and c["sql"] == _c().sql


@pytest.mark.parametrize("kw,needle,allowed_key", [
    ({"by": ["country"]}, "Unknown dimension", "dimensions"),
    ({"grain": "day"}, "Unknown grain", "grains"),
    ({"period": None}, "period is required", "max_period_days"),
    ({"period": "2024-01-01..2026-01-01"}, "longer than", "max_period_days"),
    ({"where": [{"dimension": "channel", "op": "like", "value": "w%"}]}, "Unknown op", "op"),
])
def test_refusals_name_what_is_allowed(kw, needle, allowed_key):
    with pytest.raises(MetricInputError) as e:
        _c(**kw)
    assert needle in str(e.value) and allowed_key in e.value.allowed


@pytest.mark.parametrize("where", [
    [{"dimension": "channel", "op": "in", "value": []}],
    [{"dimension": "channel", "op": "between", "value": [1]}],
    [{"dimension": "channel", "op": "=", "value": {"x": 1}}],
    [{"dimension": "channel", "op": "="}],
])
def test_malformed_where_terms(where):
    with pytest.raises(MetricInputError):
        _c(where=where)


def test_duplicate_dimension_is_refused():
    with pytest.raises(MetricInputError):
        _c(by=["channel", "channel"])


def test_period_on_a_metric_without_time_column_is_refused():
    v = MetricVersion(metric="customers", version=1, catalog="glue",
                      base_table="sales.customers", measure="COUNT(*)")
    with pytest.raises(MetricInputError):
        compile_metric(v, engine_catalog="c", dialect="athena", today=TODAY, period="last_month")
    assert "WHERE" not in compile_metric(v, engine_catalog="c", dialect="athena", today=TODAY).sql
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_compile.py -q`
Expected: collection error (`No module named 'app.semantic.compile'`).

- [ ] **Step 3: Implement `compile.py`**

```python
# backend/app/semantic/compile.py
"""Metric version + request -> one SQL statement. Deterministic, no I/O.

Built as a sqlglot tree and rendered in the engine dialect. Caller input reaches the
tree only as a registered dimension name (looked up, never spliced) or as a literal.
The measure and filters were validated when the version was saved (validate.py);
they are parsed again here only to re-point their columns at the base alias.
"""
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

import sqlglot
from sqlglot import exp

from app.semantic.model import Join, MetricInputError, MetricVersion
from app.semantic.periods import resolve_period

BASE = "b"
OPS = ("=", "!=", "in", ">", "<", "between")
_CMP = {"=": exp.EQ, "!=": exp.NEQ, ">": exp.GT, "<": exp.LT}


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    citation: dict


def _table(catalog: str, dotted: str, alias: str) -> exp.Table:
    schema, name = dotted.split(".", 1)
    return exp.Table(this=exp.to_identifier(name), db=exp.to_identifier(schema),
                     catalog=exp.to_identifier(catalog),
                     alias=exp.TableAlias(this=exp.to_identifier(alias)))


def _on_base(text: str, dialect: str) -> exp.Expression:
    tree = sqlglot.parse_one(text, dialect=dialect)
    for col in tree.find_all(exp.Column):
        col.set("table", exp.to_identifier(BASE))
    return tree


def _literal(value) -> exp.Expression:
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, (int, float)):
        return exp.Literal.number(value)
    if isinstance(value, str):
        return exp.Literal.string(value)
    raise MetricInputError("where values must be strings, numbers or booleans.")


def _where_term(target: exp.Expression, op: str, value) -> exp.Expression:
    if op == "in":
        if not isinstance(value, list) or not value:
            raise MetricInputError("'in' needs a non-empty list.")
        return exp.In(this=target, expressions=[_literal(v) for v in value])
    if op == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise MetricInputError("'between' needs [low, high].")
        return exp.Between(this=target, low=_literal(value[0]), high=_literal(value[1]))
    cls = _CMP.get(op)
    if cls is None:
        raise MetricInputError(f"Unknown op {op!r}.", {"op": list(OPS)})
    return cls(this=target, expression=_literal(value))


def compile_metric(v: MetricVersion, *, engine_catalog: str, dialect: str, today: date,
                   by: Sequence[str] = (), period: Optional[str] = None,
                   grain: Optional[str] = None, where: Sequence[dict] = ()) -> CompiledQuery:
    dims = [d.name for d in v.dimensions]
    joins: Dict[str, Tuple[str, Join]] = {}       # to_table -> (alias, join); first use wins

    def target_of(name: str) -> exp.Expression:
        d = v.dimension(name)
        if d is None:
            raise MetricInputError(f"Unknown dimension {name!r}.", {"dimensions": dims})
        if d.join is None:
            return exp.column(d.column, table=BASE)
        alias = joins.setdefault(d.join.to_table, (f"j{len(joins) + 1}", d.join))[0]
        return exp.column(d.column, table=alias)

    select: List[exp.Expression] = []
    if grain is not None:
        if v.time_column is None or grain not in v.grains:
            raise MetricInputError(f"Unknown grain {grain!r}.", {"grains": list(v.grains)})
        select.append(exp.Anonymous(this="DATE_TRUNC", expressions=[
            exp.Literal.string(grain), exp.column(v.time_column, table=BASE)]).as_(grain))
    if len(set(by)) != len(by):
        raise MetricInputError("A dimension appears twice in 'by'.", {"dimensions": dims})
    for name in by:
        select.append(target_of(name).as_(name))
    select.append(_on_base(v.measure, dialect).as_(v.metric))

    conds: List[exp.Expression] = []
    if v.filters:
        conds.append(exp.Paren(this=_on_base(v.filters, dialect)))
    start = end = None
    if v.time_column is not None:
        if period is None:
            raise MetricInputError("period is required for this metric.",
                                   {"max_period_days": v.max_period_days})
        start, end = resolve_period(period, today)
        if (end - start).days > v.max_period_days:
            raise MetricInputError(f"period is longer than {v.max_period_days} days.",
                                   {"max_period_days": v.max_period_days})
        conds.append(exp.GTE(this=exp.column(v.time_column, table=BASE),
                             expression=exp.cast(exp.Literal.string(start.isoformat()), "DATE")))
        conds.append(exp.LT(this=exp.column(v.time_column, table=BASE),
                            expression=exp.cast(exp.Literal.string(end.isoformat()), "DATE")))
    elif period is not None:
        raise MetricInputError("This metric has no time column; omit period.")
    for term in where or ():
        if not isinstance(term, dict) or set(term) != {"dimension", "op", "value"}:
            raise MetricInputError("Each where term is {dimension, op, value}.",
                                   {"op": list(OPS), "dimensions": dims})
        conds.append(_where_term(target_of(term["dimension"]), term["op"], term["value"]))

    q = exp.select(*select).from_(_table(engine_catalog, v.base_table, BASE))
    for to_table, (alias, join) in joins.items():
        on = exp.and_(*[exp.EQ(this=exp.column(a, table=BASE), expression=exp.column(b, table=alias))
                        for a, b in join.on])
        q = q.join(_table(engine_catalog, to_table, alias), on=on, join_type="left")
    if conds:
        q = q.where(exp.and_(*conds))
    n_dims = len(select) - 1
    if n_dims:
        q = q.group_by(*[exp.Literal.number(i) for i in range(1, n_dims + 1)])
        q = q.order_by(*[exp.Literal.number(i) for i in range(1, n_dims + 1)])

    sql = q.sql(dialect=dialect, identify=True)
    return CompiledQuery(sql=sql, citation={
        "metric": v.metric, "version": v.version, "approved_by": v.approved_by,
        "approved_at": v.approved_at, "sql": sql,
        "period": [start.isoformat(), end.isoformat()] if start else None})
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_compile.py -q`
Expected: all pass. If a golden string differs only in sqlglot's rendering (for example `<>` vs `!=`), print the actual SQL and update the expected string. Do not change the generator to match a guess.

- [ ] **Step 5: Add an RLS round-trip test** to the same file. It proves the compiled SQL is rewritable by the real RLS engine (filter on a base alias that has a join):

```python
def test_rls_engine_rewrites_the_compiled_sql():
    from app.rls.engine import RlsPolicy, UserContext, enforce
    sql = _c(by=["region"]).sql
    pol = RlsPolicy(id="p1", catalog="awsdatacatalog", schema="sales", table="orders",
                    filter_expression="region = 'KR'", role_map={"business_analyst": False})
    r = enforce(sql, UserContext(user_id="u", username="ana", roles=["business_analyst"]),
                [pol], [], dialect="athena")
    assert r.applied_policy_ids == ["p1"]
    assert "WHERE (region = 'KR')) AS b" in r.sql
```

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_compile.py -q` → all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/semantic/compile.py backend/tests/test_semantic_compile.py
git commit -m "feat(semantic): deterministic metric compiler on the sqlglot AST"
```

---

### Task 4: Execution hooks in `queries.py`

The service needs to know whether RLS or masks rewrote the statement. Metric statements must also not be counted as observed join history.

**Files:**
- Modify: `backend/app/api/queries.py`
  - after the `_note_resolved` definition (~line 68)
  - `_ALLOWED_ORIGINS` (~line 185)
  - the RLS block in `_execute_query_impl` (~line 386–391)
  - the relationships query filter (~line 852)
- Modify: `backend/app/schemas/query.py` (origin description)
- Test: `backend/tests/test_semantic_query_hooks.py`

**Interfaces:**
- Produces:
  - `queries._rls_holder: ContextVar[Optional[list]]`. When set to a list, `_execute_query_impl` appends every applied policy id and mask id.
  - `queries.rls_applied_ids() -> contextmanager yielding list`, a helper the service uses.
  - Origin `"metric"` is accepted.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_semantic_query_hooks.py
"""What the metric service needs from the governed execution path."""
from app.api import queries


def test_metric_is_an_allowed_origin():
    assert "metric" in queries._ALLOWED_ORIGINS

    class R:
        origin = "metric"
    assert queries._safe_origin(R()) == "metric"


def test_rls_holder_collects_applied_ids():
    with queries.rls_applied_ids() as ids:
        queries._note_rls(["p1"], ["m1"])
        assert ids == ["p1", "m1"]
    queries._note_rls(["p2"], [])          # outside the block: nowhere to write, no error


def test_relationships_exclude_metric_statements():
    import inspect
    src = inspect.getsource(queries.catalog_relationships)
    assert '"metric"' in src
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_query_hooks.py -q`
Expected: FAIL (`"metric" not in _ALLOWED_ORIGINS`, `AttributeError: rls_applied_ids`).

- [ ] **Step 3: Implement.** Below `_note_resolved` add:

```python
# Which RLS policies and masks rewrote the statement, for a caller that must say so
# (the metric service's citation: the same definition can give different numbers to
# different callers). Same holder pattern as _resolved_holder.
_rls_holder: contextvars.ContextVar[Optional[list]] = \
    contextvars.ContextVar("query_rls_applied", default=None)


def _note_rls(policy_ids, mask_ids) -> None:
    holder = _rls_holder.get()
    if holder is not None:
        holder.extend(list(policy_ids or []) + list(mask_ids or []))


from contextlib import contextmanager


@contextmanager
def rls_applied_ids():
    ids: list = []
    token = _rls_holder.set(ids)
    try:
        yield ids
    finally:
        _rls_holder.reset(token)
```

Change `_ALLOWED_ORIGINS = ("ui", "ai_sql", "internal")` to `_ALLOWED_ORIGINS = ("ui", "ai_sql", "internal", "metric")`.

In `_execute_query_impl`, directly after `result = enforce(effective_query, ctx, policies, masks, dialect=engine.rls_dialect)`, add:

```python
            _note_rls(result.applied_policy_ids, result.applied_mask_ids)
```

In `catalog_relationships`, replace

```python
        if not include_ai:
            query = query.filter(QueryHistory.origin != "ai_sql")
```

with

```python
        # A metric statement is built from joins an admin already approved; counting
        # it would let the library vote for itself.
        query = query.filter(QueryHistory.origin != "metric")
        if not include_ai:
            query = query.filter(QueryHistory.origin != "ai_sql")
```

In `backend/app/schemas/query.py`, change the origin description to `"Who wrote this SQL: ui | ai_sql | internal | metric"`.

- [ ] **Step 4: Run the new tests and the query test suites**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_query_hooks.py tests/test_tool_call_log_routes_query.py tests/test_catalog_grants_query.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/queries.py backend/app/schemas/query.py backend/tests/test_semantic_query_hooks.py
git commit -m "feat(queries): report applied RLS ids; metric origin; keep metric SQL out of join history"
```

---

### Task 5: Store and service — visibility, query, audit

**Files:**
- Create: `backend/app/semantic/store.py`
- Create: `backend/app/semantic/service.py`
- Test: `backend/tests/test_semantic_service.py`
- Test: `backend/tests/test_semantic_store_pg.py` (opt-in)

**Interfaces:**
- Consumes: Task 3 `compile_metric`; Task 4 `queries.rls_applied_ids`, origin `"metric"`; `catalog_access.for_caller`; `tool_call_log.record`; `app.api.auth.is_delegated_credential`.
- Produces (store; every function takes `pool` first):
  - `get_metric(pool, name) -> dict | None`. Keys: `id, name, label, description, synonyms, owner_name, status, current_version, updated_at`.
  - `list_metrics(pool) -> list[dict]` (same keys, plus `catalog` of the current version or of the latest version).
  - `get_version(pool, metric_id: int, metric_name: str, version: int) -> MetricVersion | None`
  - `latest_version_number(pool, metric_id) -> int` (0 when none)
  - `list_versions(pool, metric_id) -> list[dict]`. Keys: version fields plus `created_by_name, change_note, created_at, approved_by_name, approved_at`.
  - `create_metric(pool, *, name, label, description, synonyms, owner_id, owner_name) -> int`
  - `insert_version(pool, *, metric_id, fields: dict, created_by, created_by_name, change_note) -> int`
  - `approve_version(pool, *, metric_id, version, approver_id, approver_name) -> None`
  - `retire_metric(pool, metric_id) -> None`
  - `list_joins(pool, catalog: str | None = None) -> list[dict]`
  - `get_join(pool, join_id) -> dict | None`
  - `insert_join(pool, *, catalog, from_table, to_table, on_columns, source, approver_id, approver_name) -> int`
  - `row_to_version(metric_name: str, row) -> MetricVersion`
- Produces (service):
  - `class MetricNotFound(Exception)`
  - `today_local() -> date`
  - `async def resolve_visible(user, name: str, version: int | None = None) -> tuple[dict, MetricVersion, CatalogEntry]`. Raises `MetricNotFound`.
  - `async def run_metric_query(user: dict, *, metric: str, by=(), period=None, grain=None, where=(), version: int | None = None) -> dict`. Returns `{columns, rows, row_count, truncated, citation}`. Raises `HTTPException(404|400)`, or whatever `_execute_query_impl` raises.
  - `async def list_visible(user) -> list[dict]`
  - `async def describe_visible(user, name: str) -> dict`

- [ ] **Step 1: Write the failing service tests (fake store, fake executor)**

```python
# backend/tests/test_semantic_service.py
"""metric.query: visibility, compile, governed execution, one audit row."""
import asyncio
from datetime import date

import pytest
from fastapi import HTTPException

from app.semantic import service
from app.semantic.model import Dimension, MetricVersion

ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
ANA = {"id": "00000000-0000-0000-0000-000000000002", "username": "ana", "role": "business_analyst"}
KEY_ON_ADMIN = dict(ADMIN, auth_method="service", permissions=["query:run", "catalog:read"])

V3 = MetricVersion(metric="revenue", version=3, catalog="glue", base_table="sales.orders",
                   measure="SUM(amount)", time_column="ordered_at", grains=("month",),
                   dimensions=(Dimension("channel", "channel"),), approved_by="root",
                   approved_at="2026-10-15T00:00:00+00:00", created_by=ADMIN["id"])
V4_DRAFT = MetricVersion(metric="revenue", version=4, catalog="glue", base_table="sales.orders",
                         measure="SUM(amount)", time_column="ordered_at",
                         created_by=ADMIN["id"])
META = {"id": 7, "name": "revenue", "label": "매출", "description": "", "synonyms": ["sales"],
        "owner_name": "root", "status": "approved", "current_version": 3}


class _Entry:
    name = "glue"
    engine_catalog = "AwsDataCatalog"


class _Access:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def allows(self, e):
        return self.allowed

    def resolve(self, name=None):
        return _Entry()


@pytest.fixture
def env(monkeypatch):
    state = {"audit": [], "executed": [], "allowed": True, "meta": dict(META), "rls": []}

    async def get_metric(pool, name):
        return state["meta"] if name == "revenue" else None

    async def get_version(pool, metric_id, metric_name, version):
        return {3: V3, 4: V4_DRAFT}.get(version)

    async def for_caller(user):
        return _Access(state["allowed"])

    async def record(**kw):
        state["audit"].append(kw)

    async def execute(sql, user):
        from app.api import queries
        queries._note_rls(state["rls"], [])
        state["executed"].append(sql)
        return {"columns": ["revenue"], "rows": [[10]], "row_count": 1, "truncated": False,
                "pii_masked": 0}

    async def pool():
        return None

    monkeypatch.setattr(service.store, "get_metric", get_metric)
    monkeypatch.setattr(service.store, "get_version", get_version)
    monkeypatch.setattr(service.catalog_access, "for_caller", for_caller)
    monkeypatch.setattr(service.tool_call_log, "record", record)
    monkeypatch.setattr(service, "_execute", execute)
    monkeypatch.setattr(service, "_pool", pool)
    monkeypatch.setattr(service, "today_local", lambda: date(2026, 10, 15))
    monkeypatch.setattr(service, "_dialect", lambda: "athena")
    return state


def _run(coro):
    return asyncio.run(coro)


def test_query_returns_rows_and_a_citation(env):
    out = _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    assert out["rows"] == [[10]]
    c = out["citation"]
    assert (c["metric"], c["version"], c["approved_by"]) == ("revenue", 3, "root")
    assert c["rls_applied"] is False and c["sql"] == env["executed"][0]


def test_one_audit_row_with_the_citation(env):
    _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    (row,) = env["audit"]
    assert row["tool"] == "metric.query" and row["resource_kind"] == "metric"
    assert row["resource"] == ["revenue"]
    assert row["citation_sources"] == ["metric:revenue@v3"]
    assert row["outcome"] == "ok" and row["response_text"] == env["executed"][0]


def test_rls_applied_is_reported(env):
    env["rls"] = ["p1"]
    out = _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    assert out["citation"]["rls_applied"] is True


def test_hidden_catalog_is_the_same_404_as_missing(env):
    env["allowed"] = False
    with pytest.raises(HTTPException) as hidden:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    env["allowed"] = True
    with pytest.raises(HTTPException) as missing:
        _run(service.run_metric_query(ANA, metric="nope", period="last_month"))
    assert hidden.value.status_code == missing.value.status_code == 404
    assert hidden.value.detail.replace("revenue", "X") == missing.value.detail.replace("nope", "X")
    assert [r["outcome"] for r in env["audit"]] == ["refused", "refused"]
    assert env["executed"] == []


def test_retired_or_unapproved_metric_is_404(env):
    env["meta"] = dict(META, status="retired")
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    assert e.value.status_code == 404
    env["meta"] = dict(META, status="draft", current_version=None)
    with pytest.raises(HTTPException):
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))


def test_bad_input_is_400_with_allowed_values_and_audited(env):
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", by=["country"], period="last_month"))
    assert e.value.status_code == 400 and "channel" in e.value.detail
    assert env["audit"][0]["outcome"] == "refused" and env["executed"] == []


def test_author_or_signed_in_admin_can_preview_a_draft(env):
    out = _run(service.run_metric_query(ADMIN, metric="revenue", period="last_month", version=4))
    assert out["citation"]["version"] == 4 and out["citation"]["approved_by"] is None


def test_others_cannot_preview_a_draft(env):
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month", version=4))
    assert e.value.status_code == 404


def test_delegated_admin_key_cannot_preview_draft(env):
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(KEY_ON_ADMIN, metric="revenue", period="last_month", version=4))
    assert e.value.status_code == 404


def test_an_engine_failure_is_audited_as_error_and_reraised(env, monkeypatch):
    async def boom(sql, user):
        raise HTTPException(status_code=400, detail="Table not found: sales.orders")
    monkeypatch.setattr(service, "_execute", boom)
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    assert "re-validat" in e.value.detail
    assert env["audit"][0]["outcome"] == "error"


def test_an_execution_refusal_is_audited_as_refused(env, monkeypatch):
    async def denied(sql, user):
        raise HTTPException(status_code=403, detail="RLS 차단: x")
    monkeypatch.setattr(service, "_execute", denied)
    with pytest.raises(HTTPException) as e:
        _run(service.run_metric_query(ANA, metric="revenue", period="last_month"))
    assert e.value.status_code == 403
    assert env["audit"][0]["outcome"] == "refused"
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_service.py -q`
Expected: collection error (`cannot import name 'service'`).

- [ ] **Step 3: Implement `store.py`**

```python
# backend/app/semantic/store.py
"""The three semantic tables, read and written with asyncpg. Nothing here decides who
may do what — that is service.py and the router."""
import json
from typing import List, Optional

from app.semantic.model import Dimension, Join, MetricVersion

_METRIC_COLS = ("id, name, label, description, synonyms, owner_name, status, "
                "current_version, updated_at")


def row_to_version(metric_name: str, r) -> MetricVersion:
    dims = r["dimensions"]
    if isinstance(dims, str):
        dims = json.loads(dims)
    return MetricVersion(
        metric=metric_name, version=r["version"], catalog=r["catalog"],
        base_table=r["base_table"], measure=r["measure"], filters=r["filters"],
        time_column=r["time_column"], grains=tuple(r["grains"] or ()),
        max_period_days=r["max_period_days"],
        dimensions=tuple(
            Dimension(d["name"], d["column"],
                      Join(d["join"]["to_table"], tuple(tuple(p) for p in d["join"]["on"]))
                      if d.get("join") else None)
            for d in dims),
        approved_by=r["approved_by_name"],
        approved_at=r["approved_at"].isoformat() if r["approved_at"] else None,
        created_by=str(r["created_by"]) if r["created_by"] else None)


async def get_metric(pool, name: str) -> Optional[dict]:
    async with pool.acquire() as c:
        r = await c.fetchrow(f"SELECT {_METRIC_COLS} FROM semantic_metrics WHERE name = $1", name)
    return dict(r) if r else None


async def list_metrics(pool) -> List[dict]:
    async with pool.acquire() as c:
        rows = await c.fetch(f"""
            SELECT {', '.join('m.' + x.strip() for x in _METRIC_COLS.split(','))},
                   (SELECT v.catalog FROM semantic_metric_versions v
                     WHERE v.metric_id = m.id
                     ORDER BY (v.version = m.current_version) DESC, v.version DESC
                     LIMIT 1) AS catalog
              FROM semantic_metrics m ORDER BY m.name""")
    return [dict(r) for r in rows]


async def get_version(pool, metric_id: int, metric_name: str, version: int) -> Optional[MetricVersion]:
    async with pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM semantic_metric_versions "
                             "WHERE metric_id = $1 AND version = $2", metric_id, version)
    return row_to_version(metric_name, r) if r else None


async def latest_version_number(pool, metric_id: int) -> int:
    async with pool.acquire() as c:
        return int(await c.fetchval("SELECT COALESCE(MAX(version), 0) FROM "
                                    "semantic_metric_versions WHERE metric_id = $1", metric_id))


async def list_versions(pool, metric_id: int) -> List[dict]:
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT * FROM semantic_metric_versions WHERE metric_id = $1 "
                             "ORDER BY version DESC", metric_id)
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d["dimensions"], str):
            d["dimensions"] = json.loads(d["dimensions"])
        for k in ("created_by", "approved_by"):
            d[k] = str(d[k]) if d[k] else None
        for k in ("created_at", "approved_at"):
            d[k] = d[k].isoformat() if d[k] else None
        out.append(d)
    return out


async def create_metric(pool, *, name, label, description, synonyms, owner_id, owner_name) -> int:
    async with pool.acquire() as c:
        return await c.fetchval(
            "INSERT INTO semantic_metrics (name, label, description, synonyms, owner_id, owner_name) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            name, label, description, list(synonyms), owner_id, owner_name)


async def insert_version(pool, *, metric_id: int, fields: dict, created_by, created_by_name,
                         change_note: str) -> int:
    async with pool.acquire() as c:
        async with c.transaction():
            # Serialise version numbering per metric.
            await c.execute("SELECT id FROM semantic_metrics WHERE id = $1 FOR UPDATE", metric_id)
            n = 1 + int(await c.fetchval("SELECT COALESCE(MAX(version), 0) FROM "
                                         "semantic_metric_versions WHERE metric_id = $1", metric_id))
            await c.execute(
                """INSERT INTO semantic_metric_versions
                     (metric_id, version, catalog, base_table, measure, filters, time_column,
                      grains, max_period_days, dimensions, created_by, created_by_name, change_note)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13)""",
                metric_id, n, fields["catalog"], fields["base_table"], fields["measure"],
                fields.get("filters"), fields.get("time_column"), list(fields.get("grains") or ()),
                int(fields.get("max_period_days") or 366), json.dumps(fields.get("dimensions") or []),
                created_by, created_by_name, change_note or "")
            await c.execute("UPDATE semantic_metrics SET updated_at = now() WHERE id = $1", metric_id)
    return n


async def approve_version(pool, *, metric_id: int, version: int, approver_id, approver_name) -> None:
    async with pool.acquire() as c:
        async with c.transaction():
            await c.execute(
                "UPDATE semantic_metric_versions SET approved_by = $3, approved_by_name = $4, "
                "approved_at = now() WHERE metric_id = $1 AND version = $2 AND approved_at IS NULL",
                metric_id, version, approver_id, approver_name)
            await c.execute(
                "UPDATE semantic_metrics SET status = 'approved', current_version = $2, "
                "updated_at = now() WHERE id = $1", metric_id, version)


async def retire_metric(pool, metric_id: int) -> None:
    async with pool.acquire() as c:
        await c.execute("UPDATE semantic_metrics SET status = 'retired', updated_at = now() "
                        "WHERE id = $1", metric_id)


async def list_joins(pool, catalog: Optional[str] = None) -> List[dict]:
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT id, catalog, from_table, to_table, on_columns, source, approved_by_name, "
            "approved_at FROM semantic_joins WHERE $1::text IS NULL OR lower(catalog) = lower($1) "
            "ORDER BY from_table, to_table, id", catalog)
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d["on_columns"], str):
            d["on_columns"] = json.loads(d["on_columns"])
        d["approved_at"] = d["approved_at"].isoformat() if d["approved_at"] else None
        out.append(d)
    return out


async def get_join(pool, join_id: int) -> Optional[dict]:
    for j in await list_joins(pool):
        if j["id"] == join_id:
            return j
    return None


async def insert_join(pool, *, catalog, from_table, to_table, on_columns, source,
                      approver_id, approver_name) -> int:
    async with pool.acquire() as c:
        return await c.fetchval(
            """INSERT INTO semantic_joins (catalog, from_table, to_table, on_columns, source,
                                           approved_by, approved_by_name)
               VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7)
               ON CONFLICT (catalog, from_table, to_table, on_columns)
               DO UPDATE SET source = semantic_joins.source
               RETURNING id""",
            catalog, from_table, to_table, json.dumps(on_columns), source, approver_id, approver_name)
```

- [ ] **Step 4: Implement `service.py`**

```python
# backend/app/semantic/service.py
"""Who may see which metric, and running one through the governed path.

Visibility: an approved metric whose catalog the caller may use. Anything else — a
missing name, a hidden catalog, a retired or never-approved metric, someone else's
draft — is the same 404, so the answer does not reveal what exists.

Execution goes through queries._execute_query_impl, the body of /queries/execute:
write classifier, hidden-catalog refusal, RLS, masking, PII guard and LIMIT apply
exactly as to any statement. The wrapper is not used, so its `query.execute` audit row
is not written; this module writes one `metric.query` row instead.
"""
import json
import os
import time
from datetime import date, datetime
from typing import Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app import catalog_access, tool_call_log
from app.semantic import store
from app.semantic.compile import compile_metric
from app.semantic.model import MetricInputError, MetricVersion

TOOL = "metric.query"


class MetricNotFound(Exception):
    pass


def _not_found(name: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Unknown metric {name!r}.")


def today_local() -> date:
    return datetime.now(ZoneInfo(os.getenv("SEMANTIC_TIMEZONE", "Asia/Seoul"))).date()


def _dialect() -> str:
    from app.api.query_engine import get_engine
    return get_engine().rls_dialect


async def _pool():
    from app.api.connectors import get_db_pool
    return await get_db_pool()


def _may_preview(user: dict, v: MetricVersion) -> bool:
    from app.api.auth import is_delegated_credential
    if is_delegated_credential(user):
        return False
    return user.get("role") == "admin" or (v.created_by and v.created_by == str(user.get("id")))


async def resolve_visible(user: dict, name: str, version: Optional[int] = None):
    pool = await _pool()
    meta = await store.get_metric(pool, name)
    if not meta or meta["status"] == "retired":
        raise MetricNotFound(name)
    if version is None:
        if meta["status"] != "approved" or not meta["current_version"]:
            raise MetricNotFound(name)
        v = await store.get_version(pool, meta["id"], name, meta["current_version"])
    else:
        v = await store.get_version(pool, meta["id"], name, version)
        if v is None or (v.approved_at is None and not _may_preview(user, v)):
            raise MetricNotFound(name)
    if v is None:
        raise MetricNotFound(name)
    access = await catalog_access.for_caller(user)
    if not access.allows(v.catalog):
        raise MetricNotFound(name)
    return meta, v, access.resolve(v.catalog)


async def _execute(sql: str, user: dict) -> dict:
    from app.api.queries import QueryExecuteRequest, _execute_query_impl
    from app.database.connection import SessionLocal
    db = SessionLocal()
    try:
        r = await _execute_query_impl(
            QueryExecuteRequest(query=sql, save_history=True, origin="metric"), db, user)
    finally:
        db.close()
    return {"columns": r.columns, "rows": r.rows, "row_count": r.row_count,
            "truncated": r.truncated, "pii_masked": r.pii_masked}


async def run_metric_query(user: dict, *, metric: str, by: Sequence[str] = (),
                           period: Optional[str] = None, grain: Optional[str] = None,
                           where: Sequence[dict] = (), version: Optional[int] = None) -> dict:
    from app.api.queries import rls_applied_ids
    started = time.perf_counter()
    request_text = tool_call_log.masked_for_log(json.dumps(
        {"metric": metric, "by": list(by), "period": period, "grain": grain,
         "where": list(where or []), "version": version}, ensure_ascii=False, default=str))

    async def audit(outcome, *, cite=None, sql=None, hits=0, pii=0):
        await tool_call_log.record(
            actor=user, tool=TOOL, resource_kind="metric", resource=[metric],
            request_text=request_text, hit_count=hits, citation_sources=cite,
            pii_masked=pii, outcome=outcome, response_text=sql,
            duration_ms=int((time.perf_counter() - started) * 1000))

    try:
        _meta, v, entry = await resolve_visible(user, metric, version)
    except MetricNotFound:
        await audit("refused")
        raise _not_found(metric)
    try:
        compiled = compile_metric(v, engine_catalog=entry.engine_catalog, dialect=_dialect(),
                                  today=today_local(), by=list(by), period=period,
                                  grain=grain, where=list(where or []))
    except MetricInputError as e:
        await audit("refused")
        allowed = f" Allowed: {json.dumps(e.allowed, ensure_ascii=False)}" if e.allowed else ""
        raise HTTPException(status_code=400, detail=f"{e}{allowed}")

    cite = [f"metric:{v.metric}@v{v.version}"]
    try:
        with rls_applied_ids() as applied:
            result = await _execute(compiled.sql, user)
    except HTTPException as e:
        refused = e.status_code in (401, 403)
        await audit("refused" if refused else "error", cite=cite, sql=compiled.sql)
        if refused:
            raise
        raise HTTPException(status_code=e.status_code,
                            detail=f"{e.detail} The metric definition may need re-validation "
                                   "against the current table.")
    except Exception:
        await audit("error", cite=cite, sql=compiled.sql)
        raise
    await audit("ok", cite=cite, sql=compiled.sql, hits=int(result["row_count"] or 0),
                pii=int(result.get("pii_masked") or 0))
    citation = dict(compiled.citation, rls_applied=bool(applied),
                    pii_masked=int(result.get("pii_masked") or 0))
    return {"columns": result["columns"], "rows": result["rows"],
            "row_count": result["row_count"], "truncated": result["truncated"],
            "citation": citation}


def _public(meta: dict, v: Optional[MetricVersion]) -> dict:
    out = {"name": meta["name"], "label": meta["label"], "description": meta["description"],
           "synonyms": list(meta["synonyms"] or [])}
    if v is not None:
        out.update({"version": v.version, "catalog": v.catalog, "base_table": v.base_table,
                    "measure": v.measure, "filters": v.filters, "time_column": v.time_column,
                    "grains": list(v.grains), "max_period_days": v.max_period_days,
                    "dimensions": [d.name for d in v.dimensions],
                    "approved_by": v.approved_by, "approved_at": v.approved_at})
    return out


async def list_visible(user: dict, catalog: Optional[str] = None) -> list:
    pool = await _pool()
    access = await catalog_access.for_caller(user)
    out = []
    for m in await store.list_metrics(pool):
        if m["status"] != "approved" or not m["current_version"] or not m.get("catalog"):
            continue
        if not access.allows(m["catalog"]):
            continue
        if catalog and m["catalog"].lower() != catalog.lower():
            continue
        out.append({"name": m["name"], "label": m["label"], "description": m["description"],
                    "synonyms": list(m["synonyms"] or [])})
    return out


async def describe_visible(user: dict, name: str) -> dict:
    try:
        meta, v, _entry = await resolve_visible(user, name)
    except MetricNotFound:
        raise _not_found(name)
    return _public(meta, v)
```

- [ ] **Step 5: Run the service tests and confirm they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_service.py -q`
Expected: all pass. (`is_delegated_credential`, `app/api/auth.py:414`, marks a key by `auth_method == "service"` and an IdP token by `oauth`.)

- [ ] **Step 6: Write the opt-in store test**

```python
# backend/tests/test_semantic_store_pg.py
"""store.py against real PostgreSQL (opt-in: DATAPOND_TEST_PG_DSN)."""
import asyncio
import os
from pathlib import Path

import pytest

DSN = os.environ.get("DATAPOND_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="DATAPOND_TEST_PG_DSN not set")
SQL = (Path(__file__).resolve().parents[1] / "migrations" / "versions"
       / "0023_semantic_metrics.sql").read_text()


def test_create_version_approve_read_back():
    import asyncpg
    from app.semantic import store

    async def go():
        pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
        async with pool.acquire() as c:
            await c.execute("DROP TABLE IF EXISTS public.semantic_metric_versions, "
                            "public.semantic_joins, public.semantic_metrics CASCADE")
            await c.execute(SQL)
        mid = await store.create_metric(pool, name="revenue", label="매출", description="",
                                        synonyms=["sales"], owner_id=None, owner_name="root")
        fields = {"catalog": "glue", "base_table": "sales.orders", "measure": "SUM(amount)",
                  "time_column": "ordered_at", "grains": ["month"],
                  "dimensions": [{"name": "region", "column": "region",
                                  "join": {"to_table": "sales.customers", "on": [["customer_id", "id"]]}}]}
        n1 = await store.insert_version(pool, metric_id=mid, fields=fields, created_by=None,
                                        created_by_name="root", change_note="first")
        n2 = await store.insert_version(pool, metric_id=mid, fields=fields, created_by=None,
                                        created_by_name="root", change_note="second")
        assert (n1, n2) == (1, 2)
        await store.approve_version(pool, metric_id=mid, version=1, approver_id=None,
                                    approver_name="root")
        meta = await store.get_metric(pool, "revenue")
        assert (meta["status"], meta["current_version"]) == ("approved", 1)
        v = await store.get_version(pool, mid, "revenue", 1)
        assert v.approved_by == "root" and v.dimensions[0].join.on == (("customer_id", "id"),)
        assert [r["version"] for r in await store.list_versions(pool, mid)] == [2, 1]
        (listed,) = await store.list_metrics(pool)
        assert listed["catalog"] == "glue"
        jid = await store.insert_join(pool, catalog="glue", from_table="sales.orders",
                                      to_table="sales.customers", on_columns=[["customer_id", "id"]],
                                      source="manual", approver_id=None, approver_name="root")
        again = await store.insert_join(pool, catalog="glue", from_table="sales.orders",
                                        to_table="sales.customers", on_columns=[["customer_id", "id"]],
                                        source="history", approver_id=None, approver_name="root")
        assert jid == again
        await pool.close()
    asyncio.run(go())
```

Run: `cd backend && DATAPOND_TEST_PG_DSN=postgresql://localhost/dp_semantic_test .venv/bin/python -m pytest tests/test_semantic_store_pg.py -q`
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/semantic/store.py backend/app/semantic/service.py backend/tests/test_semantic_service.py backend/tests/test_semantic_store_pg.py
git commit -m "feat(semantic): store and service — visible metrics, governed execution, one cited audit row"
```

---

### Task 6: The three actions (MCP: 26 → 29)

**Files:**
- Create: `backend/app/chat/analysis/metrics.py`
- Modify: `backend/app/chat/analysis/__init__.py` (import + `_MODULES`)
- Modify: `backend/tests/test_chat_executor_wiring.py` (`_params_for` and `_EXPLICITLY_BOUND_PARAMS`)
- Test: `backend/tests/test_semantic_actions.py`

**Interfaces:**
- Consumes: Task 5 `service.list_visible(user, catalog)`, `service.describe_visible(user, name)`, `service.run_metric_query(user, *, metric, by, period, grain, where)`.
- Produces: action ids `metric.list`, `metric.describe`, `metric.query`; MCP names `metric_list`, `metric_describe`, `metric_query`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_semantic_actions.py
from app.chat.actions import ActionKind
from app.chat.analysis import ACTIONS, EXECUTORS
from app.mcp import tools

BY_ID = {a.id: a for a in ACTIONS}


def test_three_read_actions_with_their_permissions():
    assert BY_ID["metric.list"].permission == "catalog:read"
    assert BY_ID["metric.describe"].permission == "catalog:read"
    assert BY_ID["metric.query"].permission == "query:run"
    for i in ("metric.list", "metric.describe", "metric.query"):
        assert BY_ID[i].kind is ActionKind.READ and BY_ID[i].capability == "query"
        assert i in EXECUTORS


def test_mcp_now_exposes_29_read_tools():
    assert sum(1 for a in ACTIONS if a.kind is ActionKind.READ) == 29
    names = {tools.mcp_name(a.id) for a in ACTIONS}
    assert {"metric_list", "metric_describe", "metric_query"} <= names


def test_query_params_reject_unknown_fields():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BY_ID["metric.query"].params.model_validate({"metric": "revenue", "sql": "DROP"})


def test_query_executor_passes_everything_through(monkeypatch):
    import asyncio
    from app.chat.analysis import metrics
    seen = {}

    async def fake(user, **kw):
        seen.update(kw)
        return {"ok": True}
    monkeypatch.setattr(metrics.service, "run_metric_query", fake)
    asyncio.run(metrics.query_metric({"metric": "revenue", "by": ["channel"],
                                      "period": "last_month", "grain": None, "where": None},
                                     {"id": "u"}))
    assert seen == {"metric": "revenue", "by": ["channel"], "period": "last_month",
                    "grain": None, "where": []}
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_actions.py -q`
Expected: FAIL (`KeyError: 'metric.list'`).

- [ ] **Step 3: Implement `metrics.py`**

```python
# backend/app/chat/analysis/metrics.py
"""Metric actions: governed metric definitions, queried deterministically.

`metric.query` is READ, unlike `query.run` (CREATE, approval card). query.run runs a
statement nobody approved against a table the model chose; a metric runs an
admin-approved expression over an admin-approved table, its period is mandatory and
capped (max_period_days), and the per-key rate limit applies. Residual risk — an
unpartitioned table scanned in full within the period — is shown to the admin who
approves the definition. See the semantic-layer spec §3.
"""
from typing import Any, Callable, Dict, List, Optional

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r
from app.semantic import service


class MetricList(_Strict):
    catalog: Optional[str] = Field(
        default=None, description="Only metrics over this data catalog. Omit for all you may use.")


class MetricName(_Strict):
    metric: str = Field(description="The metric's name, as metric_list returns it (e.g. revenue).")


class MetricQuery(_Strict):
    metric: str = Field(description="The metric's name, as metric_list returns it (e.g. revenue).")
    by: List[str] = Field(
        default_factory=list,
        description="Dimension names to group by, from metric_describe. Not column names.")
    period: Optional[str] = Field(
        default=None,
        description="Required when the metric has a time column. One of this_month, last_month, "
                    "this_quarter, last_quarter, this_year, last_year, last_n_days:N, or "
                    "YYYY-MM-DD..YYYY-MM-DD (inclusive).")
    grain: Optional[str] = Field(
        default=None, description="Group by time: one of the metric's grains (day, week, month, "
                                  "quarter, year).")
    where: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description='Filters as [{"dimension": "...", "op": "=|!=|in|>|<|between", "value": ...}]. '
                    "in takes a list; between takes [low, high].")


async def list_metrics(params: dict, user: dict) -> dict:
    return {"metrics": await service.list_visible(user, params.get("catalog"))}


async def describe_metric(params: dict, user: dict) -> dict:
    return await service.describe_visible(user, params["metric"])


async def query_metric(params: dict, user: dict) -> dict:
    return await service.run_metric_query(
        user, metric=params["metric"], by=params.get("by") or [],
        period=params.get("period"), grain=params.get("grain"),
        where=params.get("where") or [])


ACTIONS = (
    Action("metric.list", "List metrics",
           "Approved business metrics you may query, with their names and synonyms. Use before "
           "writing SQL for a KPI: a metric gives a cited, reproducible number.",
           ("*",), "catalog:read", ActionKind.READ, MetricList, capability="query"),
    Action("metric.describe", "Describe metric",
           "One metric's definition: expression, filters, dimensions, grains, period cap, "
           "version and approver.",
           ("*",), "catalog:read", ActionKind.READ, MetricName, capability="query"),
    Action("metric.query", "Query metric",
           "Compute an approved metric by dimensions over a period. Deterministic SQL from the "
           "approved definition; the result carries a citation (metric, version, approver, SQL).",
           ("*",), "query:run", ActionKind.READ, MetricQuery, capability="query"),
)

EXECUTORS: Dict[str, Callable] = {
    "metric.list": list_metrics,
    "metric.describe": describe_metric,
    "metric.query": query_metric,
}

RESOLVERS: Dict[str, Callable] = {
    "metric.list": _r("app.semantic.service", "list_visible"),
    "metric.describe": _r("app.semantic.service", "describe_visible"),
    "metric.query": _r("app.semantic.service", "run_metric_query"),
}

PREVIEWERS: Dict[str, Callable] = {}
```

In `backend/app/chat/analysis/__init__.py`, add `metrics` to the import list and append it to `_MODULES` after `query`:

```python
from app.chat.analysis import (audit, catalog, connectors, dashboards, governance,
                               knowledge, metrics, pipelines, platform, query, settings,
                               spend, users)

_MODULES = (catalog, query, metrics, dashboards, knowledge, governance, spend, connectors,
            platform, pipelines, audit, settings, users)
```

In `backend/tests/test_chat_executor_wiring.py`, add these entries to the dict in `_params_for`:

```python
        "metric.list": {},
        "metric.describe": {"metric": "revenue"},
        "metric.query": {"metric": "revenue", "period": "last_month"},
```

and to `_EXPLICITLY_BOUND_PARAMS`:

```python
    "metric.list": {"user", "catalog"},
    "metric.describe": {"user", "name"},
    "metric.query": {"user", "metric", "by", "period", "grain", "where"},
```

- [ ] **Step 4: Run the action, MCP and wiring tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_actions.py tests/test_mcp_tools.py tests/test_mcp_server.py tests/test_chat_executor_wiring.py tests/test_chat_analysis_assembly.py -q`
Expected: all pass. If a test elsewhere pins the read-action count at 26, update it to 29 in the same commit and name it in the commit body.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis/metrics.py backend/app/chat/analysis/__init__.py backend/tests/test_chat_executor_wiring.py backend/tests/test_semantic_actions.py
git commit -m "feat(semantic): metric.list/describe/query actions — 29 MCP read tools"
```

---

### Task 7: REST router for the console

**Files:**
- Create: `backend/app/api/semantic.py`
- Modify: `backend/main.py` (import + `app.include_router(semantic_router, prefix="/api")` next to `tool_call_router`)
- Test: `backend/tests/test_semantic_routes.py`

**Interfaces:**
- Consumes: Task 2 validators; Task 5 store, service; `catalog_access`; `get_catalog_reader(entry.name).get_columns(schema, table)`; `security_audit.record`.
- Produces routes (all under `/api`):
  - `GET /semantic/metrics` (`catalog:read`) → `{"metrics": [...], "viewer": {"can_author": bool, "can_approve": bool}}`. For authors and admins it includes drafts on visible catalogs, with `status` and `current_version`.
  - `GET /semantic/metrics/{name}` (`catalog:read`) → `{metric, versions: [...], broken: bool, broken_reason: str|None, example_sql: str|None, recent_queries: int}`
  - `POST /semantic/metrics` (`governance:write`, person) body `MetricCreate` → 201 `{name, version}`
  - `POST /semantic/metrics/{name}/versions` (`governance:write`, person) body `VersionBody` → 201 `{name, version}`
  - `POST /semantic/metrics/{name}/preview` (`governance:write`, person) body `PreviewBody` → `service.run_metric_query(..., version=)`
  - `POST /semantic/metrics/{name}/query` (`query:run`) body `QueryBody` → `service.run_metric_query(...)` on the approved version (SQL Lab's "Query as metric")
  - `POST /semantic/metrics/{name}/versions/{version}/approve` (`require_admin`) → `{name, version}`
  - `POST /semantic/metrics/{name}/retire` (`require_admin`) → `{name, status: "retired"}`
  - `GET /semantic/joins` (`catalog:read`) → `{"joins": [...]}` (visible catalogs only)
  - `POST /semantic/joins` (`require_admin`) body `JoinBody` → 201 `{id}` after the many-to-one check; 422 with `duplicates` when it fails
  - `GET /semantic/tables/{catalog}/{schema}/{table}/partitioned` is **not** added. The full-scan warning comes from `example_sql` plus a `partition_info: "unknown"` field in describe. The current catalog readers expose no partition keys, so describe always reports `"unknown"` and the UI always shows the warning on approval. This is an honest default until a reader exposes partition keys.

- [ ] **Step 1: Write the failing route tests** (FastAPI `TestClient`, store/service/validators monkeypatched, same style as `tests/test_catalog_admin.py`)

```python
# backend/tests/test_semantic_routes.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth
from app.api import semantic as api
from app.semantic.model import Dimension, MetricVersion

ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
ANALYST = {"id": "00000000-0000-0000-0000-000000000003", "username": "ana",
           "role": "business_analyst"}
KEY = dict(ADMIN, auth_method="service", permissions=["catalog:read", "governance:write"])
COLS = {"sales.orders": ["amount", "status", "channel", "ordered_at", "customer_id"],
        "sales.customers": ["id", "region"]}


class FakeStore:
    def __init__(self):
        self.metrics, self.versions, self.joins = {}, {}, []

    async def get_metric(self, pool, name):
        return self.metrics.get(name)

    async def list_metrics(self, pool):
        out = []
        for m in self.metrics.values():
            vs = self.versions.get(m["id"], {})
            cur = vs.get(m["current_version"]) or (vs[max(vs)] if vs else None)
            out.append(dict(m, catalog=cur.catalog if cur else None))
        return out

    async def get_version(self, pool, mid, name, version):
        return self.versions.get(mid, {}).get(version)

    async def list_versions(self, pool, mid):
        return [{"version": v.version, "approved_at": v.approved_at, "change_note": ""}
                for v in sorted(self.versions.get(mid, {}).values(), key=lambda v: -v.version)]

    async def create_metric(self, pool, *, name, label, description, synonyms, owner_id, owner_name):
        mid = len(self.metrics) + 1
        self.metrics[name] = {"id": mid, "name": name, "label": label, "description": description,
                              "synonyms": synonyms, "owner_name": owner_name, "status": "draft",
                              "current_version": None, "updated_at": None}
        return mid

    async def insert_version(self, pool, *, metric_id, fields, created_by, created_by_name, change_note):
        from app.semantic.store import row_to_version
        n = 1 + max(self.versions.get(metric_id, {}) or [0])
        name = next(m["name"] for m in self.metrics.values() if m["id"] == metric_id)
        row = dict(fields, version=n, filters=fields.get("filters"),
                   time_column=fields.get("time_column"), grains=fields.get("grains") or [],
                   max_period_days=fields.get("max_period_days") or 366,
                   approved_by_name=None, approved_at=None, created_by=created_by)
        self.versions.setdefault(metric_id, {})[n] = row_to_version(name, row)
        return n

    async def approve_version(self, pool, *, metric_id, version, approver_id, approver_name):
        import dataclasses
        v = self.versions[metric_id][version]
        self.versions[metric_id][version] = dataclasses.replace(
            v, approved_by=approver_name, approved_at="2026-10-15T00:00:00+00:00")
        m = next(m for m in self.metrics.values() if m["id"] == metric_id)
        m.update(status="approved", current_version=version)

    async def retire_metric(self, pool, mid):
        next(m for m in self.metrics.values() if m["id"] == mid)["status"] = "retired"

    async def list_joins(self, pool, catalog=None):
        return list(self.joins)

    async def get_join(self, pool, jid):
        return next((j for j in self.joins if j["id"] == jid), None)

    async def insert_join(self, pool, **kw):
        self.joins.append(dict(kw, id=len(self.joins) + 1,
                               on_columns=kw["on_columns"], approved_by_name=kw["approver_name"]))
        return len(self.joins)


@pytest.fixture
def client(monkeypatch):
    fs = FakeStore()
    for name in ("get_metric", "list_metrics", "get_version", "list_versions", "create_metric",
                 "insert_version", "approve_version", "retire_metric", "list_joins", "get_join",
                 "insert_join"):
        monkeypatch.setattr(api.store, name, getattr(fs, name))
    state = {"user": ADMIN, "unique": True, "audited": []}

    async def pool():
        return None
    monkeypatch.setattr(api, "_pool", pool)
    monkeypatch.setattr(api.service, "_pool", pool)
    monkeypatch.setattr(api, "_columns", lambda entry, table: COLS.get(table))

    async def target_unique(user, entry, to_table, columns):
        return (True, 0) if state["unique"] else (False, 3)
    monkeypatch.setattr(api, "_target_unique", target_unique)

    async def recent(name):
        return 0
    monkeypatch.setattr(api, "_recent_queries", recent)

    async def record(**kw):
        state["audited"].append(kw)
    monkeypatch.setattr(api.security_audit, "record", record)

    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    app.dependency_overrides[auth.require_user] = lambda: state["user"]
    c = TestClient(app)
    c.state, c.fs = state, fs
    return c


BODY = {"name": "revenue", "label": "매출", "synonyms": ["sales"],
        "version": {"catalog": "glue", "base_table": "sales.orders", "measure": "SUM(amount)",
                    "filters": "status = 'paid'", "time_column": "ordered_at", "grains": ["month"],
                    "dimensions": [{"name": "channel", "column": "channel"}],
                    "change_note": "first"}}


@pytest.fixture(autouse=True)
def _glue_catalog(monkeypatch):
    from app import catalog_registry as reg
    entry = reg.CatalogEntry(name="glue", kind="glue", engine_catalog="AwsDataCatalog",
                             config={}, is_default=True, enabled=True)
    reg.set_entries([entry])
    yield
    reg.reset()


def test_create_then_approve_then_listed(client):
    assert client.post("/api/semantic/metrics", json=BODY).status_code == 201
    assert client.post("/api/semantic/metrics/revenue/versions/1/approve").status_code == 200
    body = client.get("/api/semantic/metrics").json()
    assert [m["name"] for m in body["metrics"]] == ["revenue"]
    assert body["viewer"] == {"can_author": True, "can_approve": True}


def test_invalid_measure_is_422_with_field(client):
    bad = {**BODY, "version": {**BODY["version"], "measure": "SUM((SELECT 1))"}}
    r = client.post("/api/semantic/metrics", json=bad)
    assert r.status_code == 422 and r.json()["detail"]["field"] == "measure"


def test_unknown_column_is_422(client):
    bad = {**BODY, "version": {**BODY["version"], "time_column": "nope"}}
    assert client.post("/api/semantic/metrics", json=bad).status_code == 422


def test_dimension_join_must_be_an_approved_join(client):
    dims = [{"name": "region", "column": "region", "join_id": 99}]
    bad = {**BODY, "version": {**BODY["version"], "dimensions": dims}}
    r = client.post("/api/semantic/metrics", json=bad)
    assert r.status_code == 422 and r.json()["detail"]["field"] == "dimensions"


def test_join_is_copied_by_value_into_the_version(client):
    client.post("/api/semantic/joins", json={"catalog": "glue", "from_table": "sales.orders",
                                             "to_table": "sales.customers",
                                             "on_columns": [["customer_id", "id"]], "source": "manual"})
    dims = [{"name": "region", "column": "region", "join_id": 1}]
    client.post("/api/semantic/metrics", json={**BODY, "version": {**BODY["version"], "dimensions": dims}})
    v = client.fs.versions[1][1]
    assert v.dimensions[0].join.to_table == "sales.customers"
    assert v.dimensions[0].join.on == (("customer_id", "id"),)


def test_non_unique_join_target_is_422(client):
    client.state["unique"] = False
    r = client.post("/api/semantic/joins", json={"catalog": "glue", "from_table": "sales.orders",
                                                 "to_table": "sales.customers",
                                                 "on_columns": [["customer_id", "id"]], "source": "history"})
    assert r.status_code == 422 and r.json()["detail"]["duplicates"] == 3


def test_a_role_without_governance_write_cannot_author(client):
    client.state["user"] = ANALYST
    assert client.post("/api/semantic/metrics", json=BODY).status_code == 403
    assert client.get("/api/semantic/metrics").json()["viewer"] == {"can_author": False,
                                                                     "can_approve": False}


def test_a_key_cannot_author_even_with_governance_write(client):
    client.state["user"] = KEY
    assert client.post("/api/semantic/metrics", json=BODY).status_code == 403


def test_query_route_runs_the_approved_version_and_audits_metric_query(client, monkeypatch):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    rows, audit = [], []

    async def execute(sql, user):
        rows.append(sql)
        return {"columns": ["revenue"], "rows": [[1]], "row_count": 1, "truncated": False,
                "pii_masked": 0}

    async def record(**kw):
        audit.append(kw)
    from datetime import date
    monkeypatch.setattr(api.service, "_execute", execute)
    monkeypatch.setattr(api.service.tool_call_log, "record", record)
    monkeypatch.setattr(api.service, "today_local", lambda: date(2026, 10, 15))
    monkeypatch.setattr(api.service, "_dialect", lambda: "athena")
    r = client.post("/api/semantic/metrics/revenue/query", json={"period": "last_month"})
    assert r.status_code == 200 and r.json()["citation"]["version"] == 1
    assert audit[0]["tool"] == "metric.query" and len(rows) == 1


def test_a_key_cannot_approve_even_on_an_admin_account(client):
    client.post("/api/semantic/metrics", json=BODY)
    client.state["user"] = KEY
    assert client.post("/api/semantic/metrics/revenue/versions/1/approve").status_code in (401, 403)


def test_approving_twice_is_409(client):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    assert client.post("/api/semantic/metrics/revenue/versions/1/approve").status_code == 409


def test_definition_changes_are_audited(client):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    reasons = [a["reason"] for a in client.state["audited"]]
    assert any("revenue v1 created" in r for r in reasons)
    assert any("revenue v1 approved" in r for r in reasons)


def test_describe_reports_broken_when_column_missing(client, monkeypatch):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    monkeypatch.setattr(api, "_columns", lambda entry, table: ["status", "ordered_at"])
    body = client.get("/api/semantic/metrics/revenue").json()
    assert body["broken"] is True and "amount" in body["broken_reason"]


def test_hidden_catalog_metric_is_404_on_describe(client, monkeypatch):
    client.post("/api/semantic/metrics", json=BODY)
    client.post("/api/semantic/metrics/revenue/versions/1/approve")
    from app import catalog_access

    class Hidden:
        def allows(self, e):
            return False

        def resolve(self, name=None):
            raise AssertionError("not reached")

    async def for_caller(user):
        return Hidden()
    monkeypatch.setattr(catalog_access, "for_caller", for_caller)
    assert client.get("/api/semantic/metrics/revenue").status_code == 404
    assert client.get("/api/semantic/metrics").json()["metrics"] == []
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_routes.py -q`
Expected: collection error (`cannot import name 'semantic' from 'app.api'`). If `CatalogEntry(...)` takes different fields, read `app/catalog_registry.py:165` and adjust the fixture to match.

- [ ] **Step 3: Implement `backend/app/api/semantic.py`**

```python
# backend/app/api/semantic.py
"""Console routes for metric definitions (docs/superpowers/specs/2026-10-15-sql-semantic-layer-design.md).

Reading needs catalog:read and follows catalog grants. Authoring — a new metric, a new
version, a preview of a draft — needs governance:write. Approving, retiring and
approving a join need a signed-in administrator: require_admin refuses keys and IdP
tokens, so no agent can change what a metric means. Agents never reach these routes;
they use the metric.* actions.
"""
import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import catalog_access, catalog_registry, security_audit
from app.api.auth import require_admin, require_permission, require_user
from app.semantic import service, store
from app.semantic.compile import compile_metric
from app.semantic.model import DefinitionError, MetricInputError
from app.semantic.validate import check_name, validate_filters, validate_grains, validate_measure

logger = logging.getLogger(__name__)
router = APIRouter()


async def _pool():
    from app.api.connectors import get_db_pool
    return await get_db_pool()


# ── bodies ───────────────────────────────────────────────────────────────────

class DimensionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    column: str
    join_id: Optional[int] = None


class VersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog: str
    base_table: str
    measure: str
    filters: Optional[str] = None
    time_column: Optional[str] = None
    grains: List[str] = Field(default_factory=list)
    max_period_days: int = Field(default=366, ge=1, le=3660)
    dimensions: List[DimensionBody] = Field(default_factory=list)
    change_note: str = ""


class MetricCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    label: str
    description: str = ""
    synonyms: List[str] = Field(default_factory=list)
    version: VersionBody


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    by: List[str] = Field(default_factory=list)
    period: Optional[str] = None
    grain: Optional[str] = None
    where: List[dict] = Field(default_factory=list)


class JoinBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog: str
    from_table: str
    to_table: str
    on_columns: List[List[str]]
    source: str = Field(pattern="^(history|naming|manual)$")


# ── helpers ──────────────────────────────────────────────────────────────────

def _bad(field: str, message: str, status: int = 422, **extra):
    raise HTTPException(status_code=status, detail={"field": field, "message": message, **extra})


def _columns(entry, table: str) -> Optional[List[str]]:
    """Column names of schema.table in that catalog, or None if it cannot be read."""
    from app.api.catalog_backend import get_catalog_reader
    try:
        schema, name = table.split(".", 1)
        return [c["name"] for c in get_catalog_reader(entry.name).get_columns(schema, name)]
    except Exception as e:
        logger.info("[semantic] columns of %s unreadable: %s", table, e)
        return None


async def _entry_for(user: dict, catalog: str):
    access = await catalog_access.for_caller(user)
    try:
        return access.resolve(catalog)
    except catalog_registry.UnknownCatalog as e:
        _bad("catalog", str(e))


def _is_admin(user: dict) -> bool:
    from app.api.auth import is_delegated_credential
    return user.get("role") == "admin" and not is_delegated_credential(user)


def _can_author(user: dict) -> bool:
    from app.api.auth import is_delegated_credential
    from app.chat.authz import held_permissions
    return "governance:write" in held_permissions(user) and not is_delegated_credential(user)


def _require_person(user: dict) -> None:
    """Authoring is a person's act. A key or IdP token holding governance:write is still
    software, and software must not define what a number means."""
    from app.api.auth import is_delegated_credential
    if is_delegated_credential(user):
        raise HTTPException(403, "Metric definitions are written by a signed-in person, "
                                 "not by an API key or access token.")


async def _audit(user: dict, permission: str, route: str, reason: str) -> None:
    await security_audit.record(actor=user, permission=permission, route=route,
                                method="POST", outcome="allowed", reason=reason)


async def _checked_version(user: dict, body: VersionBody, metric_name: str) -> dict:
    """Validate a version body against the live table; return the row fields to store."""
    from app.api.query_engine import get_engine
    dialect = get_engine().rls_dialect
    entry = await _entry_for(user, body.catalog)
    if body.base_table.count(".") != 1:
        _bad("base_table", "Use schema.table.")
    cols = await asyncio.to_thread(_columns, entry, body.base_table)
    if cols is None:
        _bad("base_table", f"Cannot read the columns of {body.base_table} in {entry.name}.")
    try:
        validate_measure(body.measure, cols, dialect)
        validate_filters(body.filters, cols, dialect)
        grains = validate_grains(body.grains)
    except DefinitionError as e:
        _bad(e.field, str(e))
    lower = {c.lower() for c in cols}
    if body.time_column and body.time_column.lower() not in lower:
        _bad("time_column", f"Unknown column {body.time_column!r} on the base table.")
    if grains and not body.time_column:
        _bad("grains", "Grains need a time column.")
    pool = await _pool()
    dims, names = [], set()
    for d in body.dimensions:
        try:
            check_name(d.name)
        except DefinitionError:
            _bad("dimensions", f"Dimension name {d.name!r}: lowercase letters, digits and _.")
        if d.name in names or d.name in grains:
            _bad("dimensions", f"Dimension {d.name!r} is defined twice.")
        names.add(d.name)
        if d.join_id is None:
            if d.column.lower() not in lower:
                _bad("dimensions", f"Unknown column {d.column!r} on the base table.")
            dims.append({"name": d.name, "column": d.column})
            continue
        j = await store.get_join(pool, d.join_id)
        if (not j or j["catalog"].lower() != entry.name.lower()
                or j["from_table"].lower() != body.base_table.lower()):
            _bad("dimensions", f"Dimension {d.name!r}: join {d.join_id} is not an approved join "
                               f"from {body.base_table}.")
        target_cols = await asyncio.to_thread(_columns, entry, j["to_table"])
        if target_cols is None or d.column.lower() not in {c.lower() for c in target_cols}:
            _bad("dimensions", f"Unknown column {d.column!r} on {j['to_table']}.")
        dims.append({"name": d.name, "column": d.column,
                     "join": {"to_table": j["to_table"], "on": j["on_columns"]}})
    return {"catalog": entry.name, "base_table": body.base_table, "measure": body.measure,
            "filters": body.filters or None, "time_column": body.time_column or None,
            "grains": list(grains), "max_period_days": body.max_period_days, "dimensions": dims}


async def _target_unique(user: dict, entry, to_table: str, columns: List[str]):
    """(unique, duplicate_groups) — run as the approving admin through the governed path."""
    from sqlglot import exp
    from app.api.query_engine import get_engine
    schema, name = to_table.split(".", 1)
    keys = [exp.column(c) for c in columns]
    inner = (exp.select(*keys).from_(exp.Table(this=exp.to_identifier(name),
                                               db=exp.to_identifier(schema),
                                               catalog=exp.to_identifier(entry.engine_catalog)))
             .group_by(*[k.copy() for k in keys]).having("COUNT(*) > 1"))
    sql = exp.select("COUNT(*)").from_(inner.subquery("d")).sql(
        dialect=get_engine().rls_dialect, identify=True)
    result = await service._execute(sql, user)
    dupes = int(result["rows"][0][0]) if result["rows"] else 0
    return dupes == 0, dupes


async def _recent_queries(name: str) -> int:
    pool = await _pool()
    try:
        async with pool.acquire() as c:
            return int(await c.fetchval(
                "SELECT COUNT(*) FROM tool_call_log WHERE tool = 'metric.query' "
                "AND $1 = ANY(resource) AND occurred_at > now() - interval '30 days'", name))
    except Exception as e:
        logger.info("[semantic] recent query count unavailable: %s", e)
        return 0


# ── metrics ──────────────────────────────────────────────────────────────────

@router.get("/semantic/metrics", dependencies=[Depends(require_permission("catalog:read"))])
async def list_metrics(user: dict = Depends(require_user)):
    pool = await _pool()
    access = await catalog_access.for_caller(user)
    author, admin = _can_author(user), _is_admin(user)
    out = []
    for m in await store.list_metrics(pool):
        if not m.get("catalog") or not access.allows(m["catalog"]):
            continue
        if m["status"] != "approved" and not (author or admin):
            continue
        out.append({k: m[k] for k in ("name", "label", "description", "synonyms", "owner_name",
                                      "status", "current_version", "catalog")})
    return {"metrics": out, "viewer": {"can_author": author, "can_approve": admin}}


@router.get("/semantic/metrics/{name}", dependencies=[Depends(require_permission("catalog:read"))])
async def describe_metric(name: str, user: dict = Depends(require_user)):
    pool = await _pool()
    meta = await store.get_metric(pool, name)
    if not meta:
        raise HTTPException(404, f"Unknown metric {name!r}.")
    versions = await store.list_versions(pool, meta["id"])
    shown = meta["current_version"] or (versions[0]["version"] if versions else None)
    v = await store.get_version(pool, meta["id"], name, shown) if shown else None
    access = await catalog_access.for_caller(user)
    if v is None or not access.allows(v.catalog):
        raise HTTPException(404, f"Unknown metric {name!r}.")
    if meta["status"] != "approved" and not (_can_author(user) or _is_admin(user)):
        raise HTTPException(404, f"Unknown metric {name!r}.")
    entry = access.resolve(v.catalog)
    broken_reason = None
    cols = await asyncio.to_thread(_columns, entry, v.base_table)
    if cols is None:
        broken_reason = f"Cannot read {v.base_table}."
    else:
        from app.api.query_engine import get_engine
        try:
            validate_measure(v.measure, cols, get_engine().rls_dialect)
            validate_filters(v.filters, cols, get_engine().rls_dialect)
            for c in [v.time_column] + [d.column for d in v.dimensions if d.join is None]:
                if c and c.lower() not in {x.lower() for x in cols}:
                    raise DefinitionError("dimensions", f"Unknown column {c!r} on the base table.")
        except DefinitionError as e:
            broken_reason = str(e)
    example = None
    try:
        from app.api.query_engine import get_engine
        example = compile_metric(v, engine_catalog=entry.engine_catalog,
                                 dialect=get_engine().rls_dialect, today=service.today_local(),
                                 period="last_month" if v.time_column else None).sql
    except (MetricInputError, Exception) as e:
        logger.info("[semantic] example SQL for %s failed: %s", name, e)
    return {"metric": dict(service._public(meta, v), status=meta["status"],
                           owner_name=meta["owner_name"], current_version=meta["current_version"]),
            "versions": versions, "broken": broken_reason is not None,
            "broken_reason": broken_reason, "example_sql": example,
            "partition_info": "unknown", "recent_queries": await _recent_queries(name)}


@router.post("/semantic/metrics", status_code=201)
async def create_metric(body: MetricCreate, user: dict = Depends(require_permission("governance:write"))):
    _require_person(user)
    try:
        check_name(body.name)
    except DefinitionError as e:
        _bad("name", str(e))
    if not body.label.strip():
        _bad("label", "Required.")
    fields = await _checked_version(user, body.version, body.name)
    pool = await _pool()
    if await store.get_metric(pool, body.name):
        _bad("name", f"A metric named {body.name!r} exists.", 409)
    mid = await store.create_metric(pool, name=body.name, label=body.label.strip(),
                                    description=body.description, synonyms=body.synonyms,
                                    owner_id=user.get("id"), owner_name=user.get("username"))
    n = await store.insert_version(pool, metric_id=mid, fields=fields, created_by=user.get("id"),
                                   created_by_name=user.get("username"),
                                   change_note=body.version.change_note)
    await _audit(user, "governance:write", "/api/semantic/metrics", f"metric {body.name} v{n} created")
    return {"name": body.name, "version": n}


@router.post("/semantic/metrics/{name}/versions", status_code=201)
async def create_version(name: str, body: VersionBody,
                         user: dict = Depends(require_permission("governance:write"))):
    _require_person(user)
    pool = await _pool()
    meta = await store.get_metric(pool, name)
    if not meta or meta["status"] == "retired":
        raise HTTPException(404, f"Unknown metric {name!r}.")
    fields = await _checked_version(user, body, name)
    n = await store.insert_version(pool, metric_id=meta["id"], fields=fields,
                                   created_by=user.get("id"), created_by_name=user.get("username"),
                                   change_note=body.change_note)
    await _audit(user, "governance:write", f"/api/semantic/metrics/{name}/versions",
                 f"metric {name} v{n} created")
    return {"name": name, "version": n}


@router.post("/semantic/metrics/{name}/preview")
async def preview(name: str, body: PreviewBody,
                  user: dict = Depends(require_permission("governance:write"))):
    _require_person(user)
    return await service.run_metric_query(user, metric=name, by=body.by, period=body.period,
                                          grain=body.grain, where=body.where, version=body.version)


class QueryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: List[str] = Field(default_factory=list)
    period: Optional[str] = None
    grain: Optional[str] = None
    where: List[dict] = Field(default_factory=list)


@router.post("/semantic/metrics/{name}/query")
async def query(name: str, body: QueryBody, user: dict = Depends(require_permission("query:run"))):
    """The console's way to metric.query (SQL Lab's "Query as metric"). Same service,
    same single `metric.query` audit row as the MCP tool."""
    return await service.run_metric_query(user, metric=name, by=body.by, period=body.period,
                                          grain=body.grain, where=body.where)


@router.post("/semantic/metrics/{name}/versions/{version}/approve")
async def approve(name: str, version: int, admin: dict = Depends(require_admin)):
    pool = await _pool()
    meta = await store.get_metric(pool, name)
    v = await store.get_version(pool, meta["id"], name, version) if meta else None
    if v is None or meta["status"] == "retired":
        raise HTTPException(404, f"Unknown metric {name!r}.")
    if v.approved_at is not None:
        raise HTTPException(409, f"{name} v{version} is already approved.")
    await store.approve_version(pool, metric_id=meta["id"], version=version,
                                approver_id=admin.get("id"), approver_name=admin.get("username"))
    await _audit(admin, "admin", f"/api/semantic/metrics/{name}/versions/{version}/approve",
                 f"metric {name} v{version} approved")
    return {"name": name, "version": version}


@router.post("/semantic/metrics/{name}/retire")
async def retire(name: str, admin: dict = Depends(require_admin)):
    pool = await _pool()
    meta = await store.get_metric(pool, name)
    if not meta:
        raise HTTPException(404, f"Unknown metric {name!r}.")
    await store.retire_metric(pool, meta["id"])
    await _audit(admin, "admin", f"/api/semantic/metrics/{name}/retire", f"metric {name} retired")
    return {"name": name, "status": "retired"}


# ── joins ────────────────────────────────────────────────────────────────────

@router.get("/semantic/joins", dependencies=[Depends(require_permission("catalog:read"))])
async def list_joins(catalog: Optional[str] = None, user: dict = Depends(require_user)):
    access = await catalog_access.for_caller(user)
    return {"joins": [j for j in await store.list_joins(await _pool(), catalog)
                      if access.allows(j["catalog"])]}


@router.post("/semantic/joins", status_code=201)
async def approve_join(body: JoinBody, admin: dict = Depends(require_admin)):
    entry = await _entry_for(admin, body.catalog)
    for t in (body.from_table, body.to_table):
        if t.count(".") != 1:
            _bad("table", "Use schema.table.")
    if not body.on_columns or any(len(p) != 2 for p in body.on_columns):
        _bad("on_columns", "Give [from_column, to_column] pairs.")
    from_cols = await asyncio.to_thread(_columns, entry, body.from_table)
    to_cols = await asyncio.to_thread(_columns, entry, body.to_table)
    if from_cols is None or to_cols is None:
        _bad("table", "Cannot read the columns of one of the tables.")
    fl, tl = {c.lower() for c in from_cols}, {c.lower() for c in to_cols}
    for a, b in body.on_columns:
        if a.lower() not in fl or b.lower() not in tl:
            _bad("on_columns", f"Unknown column in pair [{a}, {b}].")
    unique, dupes = await _target_unique(admin, entry, body.to_table, [b for _, b in body.on_columns])
    if not unique:
        _bad("on_columns", f"{body.to_table} has {dupes} key value(s) that repeat; only "
                           "many-to-one joins are allowed.", duplicates=dupes)
    jid = await store.insert_join(await _pool(), catalog=entry.name, from_table=body.from_table,
                                  to_table=body.to_table, on_columns=body.on_columns,
                                  source=body.source, approver_id=admin.get("id"),
                                  approver_name=admin.get("username"))
    await _audit(admin, "admin", "/api/semantic/joins",
                 f"join {body.from_table} -> {body.to_table} approved")
    return {"id": jid}
```

Register it in `backend/main.py` next to `tool_call_router`, following that file's import style:

```python
from app.api.semantic import router as semantic_router
...
app.include_router(semantic_router, prefix="/api")
```

- [ ] **Step 4: Run route, inventory and uniqueness tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_routes.py tests/test_route_authorization_inventory.py tests/test_route_uniqueness.py -q`
Expected: all pass. If `test_route_authorization_inventory.py` fails on a new POST route, the route is missing its dependency. Fix the route; do not add an exception.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/semantic.py backend/main.py backend/tests/test_semantic_routes.py
git commit -m "feat(semantic): console routes — author, approve, retire, joins with many-to-one check"
```

---

### Task 8: `/ai/sql` integration

**Files:**
- Modify: `backend/app/api/ai_sql.py` (`_build_messages`, `AskResponse`, the route body around lines 490–520, and the audit rows at ~643/648)
- Create: `backend/app/semantic/context.py`
- Test: `backend/tests/test_semantic_ai_sql.py`

**Interfaces:**
- Consumes: Task 5 `service.list_visible`, `store.list_metrics`/`get_version`.
- Produces:
  - `context.metric_lines(metrics: list[dict], question: str, limit: int = 20) -> tuple[str, list[str]]`. Returns the prompt block text (empty string when no metrics) and the provided ids like `"revenue@v3"`. Each input dict has keys `name, label, synonyms, version, measure, filters, base_table, time_column`.
  - `context.suggest(metrics: list[dict], question: str) -> dict | None` (`{"name", "dimensions"}`)
  - `async context.for_caller(user, catalog) -> list[dict]` (approved, visible metrics with their current version fields)
  - `_build_messages(schema_ctx, question, context, metrics_block="")`
  - `AskResponse.metrics_provided: list[str] = []`
  - `AskResponse.suggested_metric: Optional[dict] = None`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_semantic_ai_sql.py
from app.semantic.context import metric_lines, suggest

M = [{"name": "revenue", "label": "매출", "synonyms": ["매출액", "sales"], "version": 3,
      "measure": "SUM(amount)", "filters": "status = 'paid'", "base_table": "sales.orders",
      "time_column": "ordered_at", "dimensions": ["channel", "region"]},
     {"name": "orders", "label": "주문 수", "synonyms": [], "version": 1,
      "measure": "COUNT(*)", "filters": None, "base_table": "sales.orders",
      "time_column": "ordered_at", "dimensions": ["channel"]}]


def test_block_lists_definitions_and_the_rule():
    block, ids = metric_lines(M, "지난달 매출")
    assert "Approved metric definitions" in block
    assert "revenue (매출; 매출액, sales): SUM(amount) FROM sales.orders WHERE status = 'paid'" in block
    assert "use its expression and filters exactly" in block
    assert ids == ["revenue@v3", "orders@v1"]


def test_question_matches_go_first_and_the_cap_holds():
    many = [dict(M[1], name=f"m{i:02d}", label=f"지표{i}", version=1) for i in range(30)]
    _, ids = metric_lines(many + [M[0]], "매출 알려줘", limit=20)
    assert ids[0] == "revenue@v3" and len(ids) == 20


def test_no_metrics_no_block():
    assert metric_lines([], "x") == ("", [])


def test_suggestion_is_a_verbatim_label_or_synonym_match():
    assert suggest(M, "지난달 매출액 지역별") == {"name": "revenue", "dimensions": ["channel", "region"]}
    assert suggest(M, "고객 이탈률") is None


def test_longest_match_wins():
    # "주문 수" must not lose to a shorter accidental match
    assert suggest(M, "채널별 주문 수")["name"] == "orders"


def test_build_messages_includes_the_block():
    from app.api.ai_sql import _build_messages
    system, _ = _build_messages("TABLES", "q", None, metrics_block="Approved metric definitions:\n- x")
    assert "Approved metric definitions" in system
    system2, _ = _build_messages("TABLES", "q", None)
    assert "Approved metric definitions" not in system2


def test_response_has_the_new_fields():
    from app.api.ai_sql import AskResponse
    r = AskResponse(sql="", explanation="", has_ai=False)
    assert r.metrics_provided == [] and r.suggested_metric is None
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_ai_sql.py -q`
Expected: collection error (`No module named 'app.semantic.context'`).

- [ ] **Step 3: Implement `context.py`**

```python
# backend/app/semantic/context.py
"""Approved metric definitions as /ai/sql prompt context.

What goes in the prompt is reported as `metrics_provided` — given, not used: nothing
here can tell whether the model followed a definition. `suggest` is a verbatim string
match, not a model call, so it is reproducible and cannot be talked into anything.
"""
from typing import List, Optional, Tuple

RULE = ("If the question asks for one of these metrics, use its expression and filters "
        "exactly.")


def _terms(m: dict) -> List[str]:
    return [t for t in [m["label"], *(m.get("synonyms") or [])] if t and t.strip()]


def _matches(m: dict, question: str) -> int:
    """Length of the longest label/synonym found in the question; 0 if none."""
    q = (question or "").lower()
    return max((len(t) for t in _terms(m) if t.lower() in q), default=0)


def metric_lines(metrics: List[dict], question: str, limit: int = 20) -> Tuple[str, List[str]]:
    if not metrics:
        return "", []
    ranked = sorted(metrics, key=lambda m: (-_matches(m, question), m["name"]))[:limit]
    lines = []
    for m in ranked:
        names = m["label"] + (f"; {', '.join(m['synonyms'])}" if m.get("synonyms") else "")
        where = f" WHERE {m['filters']}" if m.get("filters") else ""
        time = f" [time: {m['time_column']}]" if m.get("time_column") else ""
        lines.append(f"- {m['name']} ({names}): {m['measure']} FROM {m['base_table']}{where}{time}")
    block = "Approved metric definitions:\n" + "\n".join(lines) + "\n" + RULE
    return block, [f"{m['name']}@v{m['version']}" for m in ranked]


def suggest(metrics: List[dict], question: str) -> Optional[dict]:
    best = max(metrics or [], key=lambda m: _matches(m, question), default=None)
    if best is None or _matches(best, question) == 0:
        return None
    return {"name": best["name"], "dimensions": list(best.get("dimensions") or [])}


async def for_caller(user: dict, catalog: Optional[str] = None) -> List[dict]:
    """Approved metrics this caller may see, with their current version's fields."""
    from app.semantic import service, store
    visible = {m["name"] for m in await service.list_visible(user, catalog)}
    if not visible:
        return []
    pool = await service._pool()
    out = []
    for m in await store.list_metrics(pool):
        if m["name"] not in visible:
            continue
        v = await store.get_version(pool, m["id"], m["name"], m["current_version"])
        if v is None:
            continue
        out.append({"name": m["name"], "label": m["label"], "synonyms": list(m["synonyms"] or []),
                    "version": v.version, "measure": v.measure, "filters": v.filters,
                    "base_table": v.base_table, "time_column": v.time_column,
                    "dimensions": [d.name for d in v.dimensions]})
    return out
```

- [ ] **Step 4: Wire it into `ai_sql.py`**

`_build_messages` gains a parameter, and the block goes under the schema:

```python
def _build_messages(schema_ctx: str, question: str, context: Optional[str],
                    metrics_block: str = "") -> tuple[str, list]:
    from app.api.query_engine import get_engine
    eng = get_engine()
    metrics_part = f"\n{metrics_block}\n" if metrics_block else ""
    system = f"""You are an expert SQL assistant for DataPond, an AI Data Foundation.
{eng.ai_dialect_prompt}

{schema_ctx}
{metrics_part}
Rules:
...unchanged...
```

`AskResponse` gains:

```python
    # Metric definitions put in the prompt ("revenue@v3"). Given, not necessarily used.
    metrics_provided: List[str] = []
    # A metric whose label or synonym occurs verbatim in the question: the cited,
    # deterministic path (metric.query) for the same answer.
    suggested_metric: Optional[dict] = None
```

In the route body, before `system, messages = _build_messages(...)` (~line 519), add:

```python
    metrics_block, metrics_provided, suggested = "", [], None
    try:
        from app.semantic import context as metric_context
        visible_metrics = await metric_context.for_caller(user, req.catalog)
        metrics_block, metrics_provided = metric_context.metric_lines(visible_metrics, q_text)
        suggested = metric_context.suggest(visible_metrics, q_text)
    except Exception as e:      # the semantic tables are optional context, never a blocker
        logger.info("[ai_sql] metric context unavailable: %s", e)
    system, messages = _build_messages(schema_ctx, q_text, c_text or None, metrics_block)
```

Every place in the route that builds an `AskResponse` after this point must also pass `metrics_provided=metrics_provided, suggested_metric=suggested`. Find them with `grep -n "AskResponse(" backend/app/api/ai_sql.py`. The early returns before the block (empty catalog, no AI configured) keep the defaults.

Audit: in `generate_sql` (the wrapper at ~line 636), change the success `tool_call_log.record` to include

```python
                               citation_sources=[f"context:metric:{m}" for m in resp.metrics_provided] or None,
```

- [ ] **Step 5: Add route-level tests** to `backend/tests/test_semantic_ai_sql.py`. They reuse the patterns in `tests/test_catalog_grants_ai_sql.py` (prompt capture) and `tests/test_tool_call_log_routes_sql.py` (audit):

```python
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.ai_sql as m
from app import catalog_access, tool_call_log
from app import catalog_registry as reg
from app.api import auth
from app.catalog_registry import CatalogEntry

ENG = {"id": "11111111-1111-1111-1111-111111111111", "username": "eng", "role": "ai_engineer"}


def test_prompt_carries_the_block_and_the_response_reports_it(monkeypatch):
    from app.semantic import context as mc
    reg.set_entries([CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg",
                                  is_default=True)])
    catalog_access.set_grants({})
    monkeypatch.setenv("QUERY_ENGINE", "trino")
    prompts = []

    async def _record(**kw):
        return None
    monkeypatch.setattr(tool_call_log, "record", _record)
    monkeypatch.setattr(m, "_cfg", lambda: {"litellm_url": "http://litellm:4000",
                                            "litellm_model": "default", "master_key": ""})
    monkeypatch.setattr(m, "_get_schema_context",
                        lambda: "Available tables (catalog: iceberg):\n  iceberg.sales.orders: amount (double)")
    monkeypatch.setattr(m, "egress_policy", lambda: "allow-external")
    monkeypatch.setattr(m, "validate_sql", lambda sql: (True, None))

    def _llm(system, messages):
        prompts.append(system)
        return '{"sql": "SELECT SUM(amount) FROM iceberg.sales.orders", "explanation": "x"}'
    monkeypatch.setattr(m, "_call_litellm", _llm)

    async def fake_for_caller(user, catalog=None):
        return M
    monkeypatch.setattr(mc, "for_caller", fake_for_caller)
    try:
        res = asyncio.run(m.generate_sql(m.AskRequest(question="지난달 매출"), user=ENG))
    finally:
        reg.reset()
    assert "revenue (매출; 매출액, sales)" in prompts[0]
    assert res.metrics_provided == ["revenue@v3", "orders@v1"]
    assert res.suggested_metric["name"] == "revenue"


def test_audit_row_cites_provided_definitions_with_the_context_prefix(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(req, user):
        return m.AskResponse(sql="SELECT 1", explanation="", has_ai=True, provider="litellm",
                             metrics_provided=["revenue@v3"])
    monkeypatch.setattr(m, "_generate_sql_impl", _impl)
    app = FastAPI()
    app.include_router(m.router, prefix="/api")

    async def _override():
        return ENG
    app.dependency_overrides[auth.require_user] = _override
    assert TestClient(app).post("/api/ai/sql", json={"question": "매출"}).status_code == 200
    assert calls[0]["citation_sources"] == ["context:metric:revenue@v3"]
```

If `generate_sql` in this test returns before calling the model (for example because `_validation_enabled` or the PII guard changes the path), copy the extra monkeypatches from `test_the_prompt_and_the_validation_see_only_the_callers_catalogs` in `tests/test_catalog_grants_ai_sql.py`.

- [ ] **Step 6: Run the ai_sql suites**

Run: `cd backend && .venv/bin/python -m pytest tests/test_semantic_ai_sql.py tests/test_catalog_grants_ai_sql.py tests/test_tool_call_log_routes_sql.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/semantic/context.py backend/app/api/ai_sql.py backend/tests/test_semantic_ai_sql.py
git commit -m "feat(ai_sql): approved metric definitions as context; report provided, suggest the cited path"
```

---

### Task 9: Frontend pure helpers

**Files:**
- Create: `frontend/lib/metrics.ts`
- Test: `frontend/lib/metrics.test.ts`

**Interfaces:**
- Produces:
  - Types `MetricSummary`, `MetricDetail`, `MetricVersionRow`, `Viewer`, `AiSqlMetricInfo`.
  - `metricStatusBadge(m: {status, current_version}): {label: string; tone: "ok"|"draft"|"retired"}`
  - `versionDiff(prev: MetricVersionRow | undefined, next: MetricVersionRow): string[]`. Returns lines like `measure: SUM(a) → SUM(b)`.
  - `fieldError(detail: unknown): {field: string; message: string} | null`
  - `aiSqlMetricView(resp: {metrics_provided?: string[]; suggested_metric?: {name: string} | null}): {chips: string[]; suggestion: string | null}`
  - `approvalWarning(partitionInfo: string): string | null`

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/lib/metrics.test.ts
import test from "node:test"
import assert from "node:assert/strict"
import { aiSqlMetricView, approvalWarning, fieldError, metricStatusBadge, versionDiff } from "./metrics.ts"

test("status badge: approved with a version, draft, retired", () => {
  assert.deepEqual(metricStatusBadge({ status: "approved", current_version: 3 }), { label: "v3", tone: "ok" })
  assert.deepEqual(metricStatusBadge({ status: "draft", current_version: null }), { label: "draft", tone: "draft" })
  assert.deepEqual(metricStatusBadge({ status: "retired", current_version: 2 }), { label: "retired", tone: "retired" })
})

test("version diff names changed fields only", () => {
  const a = { version: 1, measure: "SUM(a)", filters: null, time_column: "t", grains: ["month"], max_period_days: 366, dimensions: [{ name: "c", column: "c" }], base_table: "s.o", catalog: "glue" }
  const b = { ...a, version: 2, measure: "SUM(b)", grains: ["month", "day"] }
  assert.deepEqual(versionDiff(a as any, b as any), ["measure: SUM(a) → SUM(b)", "grains: month → month, day"])
  assert.deepEqual(versionDiff(undefined, b as any), ["first version"])
})

test("field error reads the router's 422 detail", () => {
  assert.deepEqual(fieldError({ field: "measure", message: "SUBQUERY is not allowed here." }),
    { field: "measure", message: "SUBQUERY is not allowed here." })
  assert.equal(fieldError("plain string"), null)
  assert.equal(fieldError(undefined), null)
})

test("ai sql view: chips and a suggestion only when present", () => {
  assert.deepEqual(aiSqlMetricView({ metrics_provided: ["revenue@v3"], suggested_metric: { name: "revenue" } }),
    { chips: ["revenue v3"], suggestion: "revenue" })
  assert.deepEqual(aiSqlMetricView({}), { chips: [], suggestion: null })
})

test("approval warns unless partitioning is known", () => {
  assert.match(approvalWarning("unknown") ?? "", /full scan/i)
  assert.equal(approvalWarning("partitioned"), null)
})
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd frontend && node --test lib/metrics.test.ts`
Expected: FAIL (`Cannot find module './metrics.ts'`).

- [ ] **Step 3: Implement**

```ts
// frontend/lib/metrics.ts
/** Metric definitions in the console: view helpers with no React, so they are testable.
 *
 *  The server decides what a viewer may do (`viewer.can_author`, `viewer.can_approve`);
 *  nothing here infers a permission from a role name.
 */

export type MetricSummary = {
  name: string; label: string; description: string; synonyms: string[]
  owner_name: string | null; status: "draft" | "approved" | "retired"
  current_version: number | null; catalog: string | null
}
export type Viewer = { can_author: boolean; can_approve: boolean }
export type DimensionRow = { name: string; column: string; join?: { to_table: string; on: string[][] } }
export type MetricVersionRow = {
  version: number; catalog: string; base_table: string; measure: string; filters: string | null
  time_column: string | null; grains: string[]; max_period_days: number; dimensions: DimensionRow[]
  created_by_name?: string | null; change_note?: string; created_at?: string | null
  approved_by_name?: string | null; approved_at?: string | null
}
export type MetricDetail = {
  metric: MetricSummary & { version?: number; measure?: string; filters?: string | null; base_table?: string }
  versions: MetricVersionRow[]; broken: boolean; broken_reason: string | null
  example_sql: string | null; partition_info: string; recent_queries: number
}
export type AiSqlMetricInfo = { metrics_provided?: string[]; suggested_metric?: { name: string } | null }

export function metricStatusBadge(m: { status: string; current_version: number | null }) {
  if (m.status === "retired") return { label: "retired", tone: "retired" as const }
  if (m.status === "approved" && m.current_version) return { label: `v${m.current_version}`, tone: "ok" as const }
  return { label: "draft", tone: "draft" as const }
}

const show = (v: unknown): string =>
  Array.isArray(v) ? v.map(x => (typeof x === "object" ? (x as DimensionRow).name : String(x))).join(", ")
    : v === null || v === undefined ? "—" : String(v)

const FIELDS: (keyof MetricVersionRow)[] =
  ["catalog", "base_table", "measure", "filters", "time_column", "grains", "max_period_days", "dimensions"]

export function versionDiff(prev: MetricVersionRow | undefined, next: MetricVersionRow): string[] {
  if (!prev) return ["first version"]
  return FIELDS.filter(f => JSON.stringify(prev[f]) !== JSON.stringify(next[f]))
    .map(f => `${f}: ${show(prev[f])} → ${show(next[f])}`)
}

export function fieldError(detail: unknown): { field: string; message: string } | null {
  if (detail && typeof detail === "object" && "field" in detail && "message" in detail) {
    const d = detail as { field: unknown; message: unknown }
    return { field: String(d.field), message: String(d.message) }
  }
  return null
}

export function aiSqlMetricView(resp: AiSqlMetricInfo) {
  return {
    chips: (resp.metrics_provided ?? []).map(id => id.replace("@v", " v")),
    suggestion: resp.suggested_metric?.name ?? null,
  }
}

export function approvalWarning(partitionInfo: string): string | null {
  return partitionInfo === "partitioned" ? null
    : "Partitioning of the base table is unknown: a query may be a full scan within its period, billed by bytes scanned."
}
```

- [ ] **Step 4: Run tests, types and lint**

Run: `cd frontend && node --test lib/metrics.test.ts && npx tsc --noEmit && npm run lint`
Expected: pass, no type errors, no lint errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/metrics.ts frontend/lib/metrics.test.ts
git commit -m "feat(console): metric view helpers"
```

---

### Task 10: Console page, menu entry, SQL Lab chip

**Files:**
- Create: `frontend/app/metrics/page.tsx`
- Modify: `frontend/lib/nav-items.ts` (Data section)
- Modify: `frontend/app/query/page.tsx` (`handleAskAI` + the area that renders `aiExplanation`)

**Interfaces:**
- Consumes: Task 7 routes; Task 9 helpers; `useCapability("query")`; `toast`; `components/ui/*`.

- [ ] **Step 1: Add the menu entry.** In `frontend/lib/nav-items.ts`, in the "Data" section after Catalog:

```ts
      // Not /catalog/metrics: /catalog/[namespace] would shadow a namespace named
      // "metrics". Needs the query capability — a metric is computed by the engine.
      { title: "Metrics", url: "/metrics", capability: "query", permission: "catalog:read" },
```

If a nav test enumerates the Data items (`grep -rn "Analytics" frontend/lib/*.test.ts`), add "Metrics" there.

- [ ] **Step 2: Write the page.** The code below follows `app/governance/page.tsx`: `useConfirm`, `useToast`, relative `/api/...` fetches, `CapabilityGate`. It is split into a list/detail tab, an editor and a joins tab. Keep it in one file unless it passes ~600 lines. If it does, move `MetricEditor` and `JoinsTab` to `frontend/components/metrics/` with the same code.

```tsx
// frontend/app/metrics/page.tsx
"use client"

import { useCallback, useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CapabilityGate } from "@/lib/capabilities"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"
import { responseErrorMessage } from "@/lib/auth"
import {
  approvalWarning, fieldError, metricStatusBadge, versionDiff,
  type MetricDetail, type MetricSummary, type Viewer,
} from "@/lib/metrics"

type Join = { id: number; catalog: string; from_table: string; to_table: string; on_columns: string[][]; source: string; approved_by_name: string | null }
type Edge = { source: string; target: string; evidence: string; count: number; joins?: { left_column: string; right_column: string }[] }
const GRAINS = ["day", "week", "month", "quarter", "year"]
const TONE = { ok: "secondary", draft: "outline", retired: "destructive" } as const

async function jsonOrThrow(res: Response, fallback: string) {
  if (!res.ok) throw new Error(await responseErrorMessage(res, fallback))
  return res.json()
}

function MetricsPage() {
  const { toast } = useToast()
  const confirm = useConfirm()
  const [metrics, setMetrics] = useState<MetricSummary[]>([])
  const [viewer, setViewer] = useState<Viewer>({ can_author: false, can_approve: false })
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<MetricDetail | null>(null)
  const [editing, setEditing] = useState<"new" | "version" | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await jsonOrThrow(await fetch("/api/semantic/metrics"), "Could not load metrics")
      setMetrics(data.metrics); setViewer(data.viewer)
    } catch (e) { toast(e instanceof Error ? e.message : "Could not load metrics", "error") }
  }, [toast])

  const open = useCallback(async (name: string) => {
    setSelected(name); setDetail(null)
    try {
      setDetail(await jsonOrThrow(await fetch(`/api/semantic/metrics/${encodeURIComponent(name)}`), "Could not load metric"))
    } catch (e) { toast(e instanceof Error ? e.message : "Could not load metric", "error") }
  }, [toast])

  useEffect(() => { void load() }, [load])

  const newest = detail?.versions[0]
  const approve = async () => {
    if (!detail || !newest) return
    const warn = approvalWarning(detail.partition_info)
    if (!(await confirm({
      title: `Approve ${detail.metric.name} v${newest.version}`,
      message: `Agents will compute this metric from v${newest.version}.${warn ? ` ${warn}` : ""}`,
      confirmText: "Approve",
    }))) return
    try {
      await jsonOrThrow(await fetch(`/api/semantic/metrics/${detail.metric.name}/versions/${newest.version}/approve`, { method: "POST" }), "Approval failed")
      toast(`${detail.metric.name} v${newest.version} approved`, "success")
      await load(); await open(detail.metric.name)
    } catch (e) { toast(e instanceof Error ? e.message : "Approval failed", "error") }
  }
  const retire = async () => {
    if (!detail) return
    if (!(await confirm({ title: `Retire ${detail.metric.name}`, message: "Agents will no longer see or query it. Its versions stay, so past citations still resolve.", confirmText: "Retire", destructive: true }))) return
    try {
      await jsonOrThrow(await fetch(`/api/semantic/metrics/${detail.metric.name}/retire`, { method: "POST" }), "Retire failed")
      await load(); setSelected(null); setDetail(null)
    } catch (e) { toast(e instanceof Error ? e.message : "Retire failed", "error") }
  }

  return (
    <div className="flex-1 space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Metrics</h1>
          <p className="text-sm text-muted-foreground">Approved definitions agents compute with metric_query. Every result cites the version and its approver.</p>
        </div>
        {viewer.can_author && <Button onClick={() => { setEditing("new"); setSelected(null); setDetail(null) }}>New metric</Button>}
      </div>
      <Tabs defaultValue="metrics">
        <TabsList>
          <TabsTrigger value="metrics">Definitions</TabsTrigger>
          <TabsTrigger value="joins">Joins</TabsTrigger>
        </TabsList>
        <TabsContent value="metrics" className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <Card>
            <CardContent className="p-0">
              {metrics.length === 0 ? (
                <p className="p-6 text-sm text-muted-foreground">No metrics yet.</p>
              ) : (
                <ul className="divide-y">
                  {metrics.map(m => {
                    const b = metricStatusBadge(m)
                    return (
                      <li key={m.name}>
                        <button className={`w-full px-4 py-3 text-left hover:bg-muted ${selected === m.name ? "bg-muted" : ""}`} onClick={() => { setEditing(null); void open(m.name) }}>
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium">{m.label} <span className="font-mono text-xs text-muted-foreground">{m.name}</span></span>
                            <Badge variant={TONE[b.tone]}>{b.label}</Badge>
                          </div>
                          <div className="text-xs text-muted-foreground">{m.catalog} · {m.owner_name ?? "—"}</div>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </CardContent>
          </Card>
          {editing ? (
            <MetricEditor mode={editing} base={editing === "version" ? detail : null}
              onDone={async name => { setEditing(null); await load(); await open(name) }}
              onCancel={() => setEditing(null)} />
          ) : detail ? (
            <Card>
              <CardHeader className="flex flex-row items-start justify-between gap-2">
                <div>
                  <CardTitle>{detail.metric.label} <span className="font-mono text-sm text-muted-foreground">{detail.metric.name}</span></CardTitle>
                  <p className="text-xs text-muted-foreground">{detail.recent_queries} queries in 30 days</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {viewer.can_author && detail.metric.status !== "retired" && <Button size="sm" variant="outline" onClick={() => setEditing("version")}>New version</Button>}
                  {viewer.can_approve && newest && !newest.approved_at && <Button size="sm" onClick={approve}>Approve v{newest.version}</Button>}
                  {viewer.can_approve && detail.metric.status !== "retired" && <Button size="sm" variant="ghost" onClick={retire}>Retire</Button>}
                </div>
              </CardHeader>
              <CardContent className="space-y-4 text-sm">
                {detail.broken && <div className="rounded border border-destructive/40 bg-destructive/10 p-2 text-destructive">Broken: {detail.broken_reason}</div>}
                <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1">
                  <dt className="text-muted-foreground">Measure</dt><dd className="font-mono">{detail.metric.measure}</dd>
                  <dt className="text-muted-foreground">Table</dt><dd className="font-mono">{detail.metric.catalog}.{detail.metric.base_table}</dd>
                  <dt className="text-muted-foreground">Filters</dt><dd className="font-mono">{detail.metric.filters ?? "—"}</dd>
                  <dt className="text-muted-foreground">Synonyms</dt><dd>{detail.metric.synonyms.join(", ") || "—"}</dd>
                </dl>
                {detail.example_sql && <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">{detail.example_sql}</pre>}
                <div>
                  <h3 className="mb-1 font-medium">Versions</h3>
                  <ul className="space-y-2">
                    {detail.versions.map((v, i) => (
                      <li key={v.version} className="rounded border p-2">
                        <div className="flex justify-between text-xs">
                          <span>v{v.version} · {v.created_by_name ?? "—"} · {v.change_note || "no note"}</span>
                          <span>{v.approved_at ? `approved by ${v.approved_by_name}` : "not approved"}</span>
                        </div>
                        <ul className="mt-1 font-mono text-xs text-muted-foreground">
                          {versionDiff(detail.versions[i + 1], v).map(line => <li key={line}>{line}</li>)}
                        </ul>
                      </li>
                    ))}
                  </ul>
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card><CardContent className="p-6 text-sm text-muted-foreground">Select a metric.</CardContent></Card>
          )}
        </TabsContent>
        <TabsContent value="joins" className="mt-4">
          <JoinsTab canApprove={viewer.can_approve} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

type DimRow = { name: string; column: string; join_id: number | null }

function MetricEditor({ mode, base, onDone, onCancel }: {
  mode: "new" | "version"; base: MetricDetail | null
  onDone: (name: string) => void; onCancel: () => void
}) {
  const { toast } = useToast()
  const cur = base?.versions[0]
  const [name, setName] = useState(base?.metric.name ?? "")
  const [label, setLabel] = useState(base?.metric.label ?? "")
  const [synonyms, setSynonyms] = useState((base?.metric.synonyms ?? []).join(", "))
  const [catalog, setCatalog] = useState(cur?.catalog ?? "")
  const [table, setTable] = useState(cur?.base_table ?? "")
  const [measure, setMeasure] = useState(cur?.measure ?? "")
  const [filters, setFilters] = useState(cur?.filters ?? "")
  const [timeColumn, setTimeColumn] = useState(cur?.time_column ?? "")
  const [grains, setGrains] = useState<string[]>(cur?.grains ?? [])
  const [maxDays, setMaxDays] = useState(cur?.max_period_days ?? 366)
  const [dims, setDims] = useState<DimRow[]>((cur?.dimensions ?? []).filter(d => !d.join).map(d => ({ name: d.name, column: d.column, join_id: null })))
  const [note, setNote] = useState("")
  const [joins, setJoins] = useState<Join[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<{ columns: string[]; rows: unknown[][]; citation: { sql: string } } | null>(null)

  useEffect(() => {
    fetch("/api/semantic/joins").then(r => r.ok ? r.json() : { joins: [] }).then(d => setJoins(d.joins)).catch(() => setJoins([]))
  }, [])

  const version = () => ({
    catalog, base_table: table, measure, filters: filters || null, time_column: timeColumn || null,
    grains, max_period_days: maxDays, change_note: note,
    dimensions: dims.filter(d => d.name && d.column).map(d => (d.join_id ? d : { name: d.name, column: d.column })),
  })
  const save = async () => {
    setErrors({})
    const url = mode === "new" ? "/api/semantic/metrics" : `/api/semantic/metrics/${name}/versions`
    const body = mode === "new"
      ? { name, label, synonyms: synonyms.split(",").map(s => s.trim()).filter(Boolean), version: version() }
      : version()
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    if (res.ok) { const d = await res.json(); toast(`${d.name} v${d.version} saved as draft`, "success"); onDone(d.name); return }
    const data = await res.json().catch(() => ({}))
    const fe = fieldError(data.detail)
    if (fe) setErrors({ [fe.field]: fe.message })
    else toast(typeof data.detail === "string" ? data.detail : "Save failed", "error")
  }
  const runPreview = async () => {
    const latest = base?.versions[0]?.version
    if (!latest) return
    const res = await fetch(`/api/semantic/metrics/${name}/preview`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: latest, ...(base?.versions[0]?.time_column ? { period: "last_month" } : {}) }),
    })
    if (!res.ok) { toast(await responseErrorMessage(res, "Preview failed"), "error"); return }
    setPreview(await res.json())
  }
  const err = (f: string) => errors[f] && <p className="text-xs text-destructive">{errors[f]}</p>
  const usable = joins.filter(j => j.catalog.toLowerCase() === catalog.toLowerCase() && j.from_table.toLowerCase() === table.toLowerCase())

  return (
    <Card>
      <CardHeader><CardTitle>{mode === "new" ? "New metric" : `New version of ${name}`}</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        {mode === "new" && (<>
          <label className="block">Name <Input value={name} onChange={e => setName(e.target.value)} placeholder="revenue" />{err("name")}</label>
          <label className="block">Label <Input value={label} onChange={e => setLabel(e.target.value)} placeholder="매출" />{err("label")}</label>
          <label className="block">Synonyms <Input value={synonyms} onChange={e => setSynonyms(e.target.value)} placeholder="매출액, sales" /></label>
        </>)}
        <div className="grid grid-cols-2 gap-2">
          <label className="block">Catalog <Input value={catalog} onChange={e => setCatalog(e.target.value)} />{err("catalog")}</label>
          <label className="block">Base table <Input value={table} onChange={e => setTable(e.target.value)} placeholder="sales.orders" />{err("base_table")}</label>
        </div>
        <label className="block">Measure <Input className="font-mono" value={measure} onChange={e => setMeasure(e.target.value)} placeholder="SUM(amount)" />{err("measure")}</label>
        <label className="block">Filters <Input className="font-mono" value={filters} onChange={e => setFilters(e.target.value)} placeholder="status = 'paid'" />{err("filters")}</label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block">Time column <Input value={timeColumn} onChange={e => setTimeColumn(e.target.value)} />{err("time_column")}</label>
          <label className="block">Max period (days) <Input type="number" min={1} max={3660} value={maxDays} onChange={e => setMaxDays(Number(e.target.value))} /></label>
        </div>
        <div className="flex flex-wrap gap-3">
          {GRAINS.map(g => (
            <label key={g} className="flex items-center gap-1">
              <input type="checkbox" checked={grains.includes(g)} onChange={e => setGrains(e.target.checked ? [...grains, g] : grains.filter(x => x !== g))} /> {g}
            </label>
          ))}
          {err("grains")}
        </div>
        <div className="space-y-2">
          <div className="font-medium">Dimensions</div>
          {dims.map((d, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_1.2fr_auto] gap-2">
              <Input value={d.name} placeholder="name" onChange={e => setDims(dims.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
              <Input value={d.column} placeholder="column" onChange={e => setDims(dims.map((x, j) => j === i ? { ...x, column: e.target.value } : x))} />
              <select className="rounded border bg-background px-2" value={d.join_id ?? ""} onChange={e => setDims(dims.map((x, j) => j === i ? { ...x, join_id: e.target.value ? Number(e.target.value) : null } : x))}>
                <option value="">base table</option>
                {usable.map(j => <option key={j.id} value={j.id}>{j.to_table}</option>)}
              </select>
              <Button size="sm" variant="ghost" onClick={() => setDims(dims.filter((_, j) => j !== i))}>Remove</Button>
            </div>
          ))}
          <Button size="sm" variant="outline" onClick={() => setDims([...dims, { name: "", column: "", join_id: null }])}>Add dimension</Button>
          {err("dimensions")}
        </div>
        <label className="block">Change note <Textarea value={note} onChange={e => setNote(e.target.value)} /></label>
        <div className="flex gap-2">
          <Button onClick={save}>Save draft</Button>
          {mode === "version" && <Button variant="outline" onClick={runPreview}>Preview latest draft</Button>}
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
        {preview && (
          <div className="space-y-1">
            <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">{preview.citation.sql}</pre>
            <table className="text-xs"><thead><tr>{preview.columns.map(c => <th key={c} className="px-2 text-left">{c}</th>)}</tr></thead>
              <tbody>{preview.rows.slice(0, 20).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="px-2">{String(c)}</td>)}</tr>)}</tbody></table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function JoinsTab({ canApprove }: { canApprove: boolean }) {
  const { toast } = useToast()
  const [joins, setJoins] = useState<Join[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const load = useCallback(async () => {
    const [j, g] = await Promise.all([
      fetch("/api/semantic/joins").then(r => r.ok ? r.json() : { joins: [] }),
      fetch("/api/catalog/relationships").then(r => r.ok ? r.json() : { edges: [] }),
    ])
    setJoins(j.joins); setEdges(g.edges ?? [])
  }, [])
  useEffect(() => { void load().catch(() => undefined) }, [load])

  const approve = async (e: Edge) => {
    const pair = e.joins?.[0]
    if (!pair) return
    const [catalog, ...from] = e.source.split(".")
    const to = e.target.split(".").slice(1)
    const res = await fetch("/api/semantic/joins", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ catalog, from_table: from.join("."), to_table: to.join("."),
        on_columns: [[pair.left_column, pair.right_column]], source: e.evidence === "observed" ? "history" : "naming" }),
    })
    if (res.ok) { toast("Join approved", "success"); await load(); return }
    const data = await res.json().catch(() => ({}))
    toast(fieldError(data.detail)?.message ?? "Approval failed", "error")
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Approved joins</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          {joins.length === 0 ? <p className="text-muted-foreground">None yet.</p> : joins.map(j => (
            <div key={j.id} className="font-mono text-xs">{j.catalog}: {j.from_table} → {j.to_table} on {j.on_columns.map(p => p.join(" = ")).join(", ")} <span className="text-muted-foreground">({j.source}, {j.approved_by_name})</span></div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Candidates</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="text-xs text-muted-foreground">From query history (observed) and column naming (candidate). Only many-to-one joins can be approved; approval checks the target key is unique.</p>
          {edges.filter(e => e.joins?.length).map(e => (
            <div key={`${e.source}-${e.target}`} className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs">{e.source} → {e.target} on {e.joins![0].left_column} = {e.joins![0].right_column} <Badge variant="outline">{e.evidence === "observed" ? `history ×${e.count}` : "naming"}</Badge></span>
              {canApprove && <Button size="sm" variant="outline" onClick={() => approve(e)}>Approve</Button>}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

export default function Page() {
  return (
    <CapabilityGate capability="query">
      <MetricsPage />
    </CapabilityGate>
  )
}
```

  Two checks before committing:
  - Edge `source` and `target` are `catalog.schema.table` (`_visible_graph` in `backend/app/api/queries.py`). The catalog part is the **engine** name (for example `awsdatacatalog`), not the registry name. If the POST returns 422 "Unknown catalog", map the engine name to the registry entry with `GET /api/catalogs` (`engine_catalog` → `name`) before posting.
  - Naming candidates are emitted in alphabetical order (`catalog_graph.py` `_emit`), not in many-to-one direction. Give each candidate a second button, "Approve reversed", that swaps source/target and the column pair. The server's uniqueness check decides which direction is valid and answers 422 for the other.

- [ ] **Step 3: SQL Lab chip and button.** In `frontend/app/query/page.tsx`:
  - add state `const [aiMetrics, setAiMetrics] = useState<{ chips: string[]; suggestion: string | null }>({ chips: [], suggestion: null })`
  - in `handleAskAI` after `const data = await res.json()`, add `setAiMetrics(aiSqlMetricView(data))`, and reset it at the start of the handler
  - where `aiExplanation` is rendered, add:

```tsx
{aiMetrics.chips.length > 0 && (
  <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
    <span>Provided definitions:</span>
    {aiMetrics.chips.map(c => <Badge key={c} variant="outline">{c}</Badge>)}
  </div>
)}
{aiMetrics.suggestion && (
  <Button size="sm" variant="outline" onClick={() => runAsMetric(aiMetrics.suggestion!)}>
    Query as metric ({aiMetrics.suggestion})
  </Button>
)}
```

  `runAsMetric(name)` posts to the Task 7 route `POST /api/semantic/metrics/{name}/query` with `{period: "last_month"}`. The server answers 400 with the allowed values when the metric has no time column; on that 400, retry once with `{}`. It shows the returned rows in the existing results grid (`setResults({columns, rows, row_count, truncated, execution_time_ms: 0})`, the same shape `executeQuery` sets) and the citation SQL in the editor via `setQuery(citation.sql)`:

```tsx
const runAsMetric = async (name: string) => {
  const post = (body: object) => fetch(`/api/semantic/metrics/${encodeURIComponent(name)}/query`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  })
  let res = await post({ period: "last_month" })
  if (res.status === 400) res = await post({})
  if (!res.ok) { toast(await responseErrorMessage(res, "Metric query failed"), "error"); return }
  const data = await res.json()
  setQuery(data.citation.sql)
  setResults({ columns: data.columns, rows: data.rows, row_count: data.row_count,
               truncated: data.truncated, execution_time_ms: 0 })
  toast(`${name} v${data.citation.version} · approved by ${data.citation.approved_by}`, "success")
}
```

  Read `app/query/page.tsx` for the actual result-state setter name and shape before pasting. If it is not `setResults`, use the setter that `executeQuery` uses with the same fields. `responseErrorMessage` comes from `@/lib/auth`.

- [ ] **Step 4: Run frontend checks**

Run: `cd frontend && npm test && npx tsc --noEmit && npm run lint`
Expected: all pass.

- [ ] **Step 5: Check it in a browser** against the local dev stack, if one runs (`docs/DEVELOPMENT.md`). If none does, say so in the task report. Do not log in to the live host.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/metrics/page.tsx frontend/lib/nav-items.ts frontend/app/query/page.tsx
git commit -m "feat(console): Metrics page — definitions, versions, approval, joins; SQL Lab cites provided definitions"
```

---

### Task 11: Docs, full verification, PR

**Files:**
- Modify: `README.md` (26 → 29 in the two places; a Shipped bullet)
- Modify: `docs/MCP.md` (26 → 29; list the three tools)
- Modify: `docs/UPGRADING.md` (26 → 29; migration 0023 note)
- Modify: `CLAUDE.md` (Tool surface line: 29 read actions; one line on metrics)
- Modify: `docs/ARCHITECTURE.md` (one paragraph under governed SQL: metric definitions, citation, append-only limit)
- Modify: `docs/superpowers/specs/2026-10-15-sql-semantic-layer-design.md`. Correct it to match what was built:
  - `period` range form is `YYYY-MM-DD..YYYY-MM-DD`
  - the citation has `pii_masked` and `rls_applied`, not `masked_columns`
  - engine errors keep the engine's own status (400/403/504) with the re-validation hint, not 502
  - partition info is `"unknown"` for every current reader, so approval always warns

- [ ] **Step 1: Make the doc edits.** Use `grep -rn "26 read\|26 tools\|26 actions" README.md docs CLAUDE.md`. Edit every hit except files under `docs/superpowers/plans/` (historical records).
- [ ] **Step 2: Full backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/acceptance`
Expected: all pass (the previous baseline was 2599 passed, 7 skipped; expect more passes and +6 skipped for the opt-in PG tests). Report any failure by name.

- [ ] **Step 3: Opt-in PG tests once more**

Run: `cd backend && DATAPOND_TEST_PG_DSN=postgresql://localhost/dp_semantic_test .venv/bin/python -m pytest tests/test_semantic_migration_pg.py tests/test_semantic_store_pg.py -q`
Expected: 6 passed. Then `dropdb dp_semantic_test`.

- [ ] **Step 4: Full frontend checks**

Run: `cd frontend && npm test && npx tsc --noEmit && npm run lint`

- [ ] **Step 5: Commit, push, open PR**

```bash
git add README.md docs/MCP.md docs/UPGRADING.md CLAUDE.md docs/ARCHITECTURE.md docs/superpowers/specs/2026-10-15-sql-semantic-layer-design.md
git commit -m "docs: SQL semantic layer — 29 MCP read tools, metric citations, spec corrections"
git push -u origin HEAD
gh pr create --title "SQL semantic layer: governed metrics with cited SQL" --body-file <(printf '%s\n' "Implements docs/superpowers/specs/2026-10-15-sql-semantic-layer-design.md." "" "- metric.list/describe/query (MCP 26→29), deterministic sqlglot compiler, governed execution, one cited audit row" "- console Metrics page, joins with many-to-one check, /ai/sql context" "- migration 0023 (append-only versions; same strength as the audit tables)" "" "🤖 Generated with [Claude Code](https://claude.com/claude-code)")
```

Deploying to live is a separate step and needs the user's go-ahead. The post-deploy measurement (spec §5 step 2) runs after deploy and is recorded in the baseline file.
