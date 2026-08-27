"""Where a database is, in migration terms, and what to do about it.

This application creates its schema at startup: 44 tables from four SQL files and
thirty-odd CREATE/ALTER/INDEX statements in Python, each catching its own exception.
That is the thing versioned migrations replace, and replacing all of it in one change
is how a migration story breaks a production database.

The retrofit starts with the step that changes nothing. Alembic is installed, the
current schema is recorded as revision `0001_baseline`, and every existing bootstrap
keeps running. What that buys immediately is somewhere for the *next* schema change to
go; what it defers is converting the existing ones, which can then happen one at a
time.

The decision below is the whole safety property: a database that already has these
tables is stamped, never migrated. Running a baseline that creates tables against a
database that has them fails the deploy — and on this product the deploy is now
`--atomic`, so it would roll back a release for a reason nobody could see.
"""
from typing import Literal

BASELINE_REVISION = "0001_baseline"

Action = Literal["stamp", "upgrade"]
StartupState = Literal["ok", "stamp", "behind", "ahead"]


def baseline_action(has_tables: bool, has_version_table: bool) -> Action:
    """What the migration Job does with this database.

    `has_tables` — does the application schema already exist here.
    `has_version_table` — has Alembic been here before.

    An existing schema is **stamped**: it is already at the baseline, and running a
    baseline that creates 41 tables against a database that has them fails every
    deployment that has ever run.

    An empty database is **migrated**: the baseline builds the schema. This changed
    when the baseline stopped being a no-op — before, an empty database was stamped
    because the startup bootstraps created everything a moment later. They still do,
    and their CREATE TABLE IF NOT EXISTS makes them harmless either way, but the
    schema now has one definition that runs first.
    """
    if has_version_table:
        return "upgrade"
    return "stamp" if has_tables else "upgrade"


def _paths():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    return str(root / "alembic.ini"), str(root / "migrations")


async def apply(pool) -> str:
    """Bring this database's migration state up to date, and report what happened.

    Runs before the schema bootstraps so a converted migration lands before the
    bootstrap that used to do the same thing, and so a failure here is visible rather
    than mixed into thirty statements that each swallow their own error.

    Returns a short description for the log and for readiness.
    """
    import asyncio

    from alembic import command
    from alembic.config import Config

    async with pool.acquire() as c:
        has_version = await c.fetchval(
            "SELECT to_regclass('public.alembic_version') IS NOT NULL")
        has_tables = await c.fetchval("SELECT to_regclass('public.users') IS NOT NULL")

    ini, scripts = _paths()
    cfg = Config(ini)
    cfg.set_main_option("script_location", scripts)

    action = baseline_action(bool(has_tables), bool(has_version))
    if action == "stamp":
        await asyncio.to_thread(command.stamp, cfg, BASELINE_REVISION)
        return f"stamped {BASELINE_REVISION}"
    await asyncio.to_thread(command.upgrade, cfg, "head")
    return "upgraded to head"


def startup_check(current: "str | None", head: str) -> StartupState:
    """Where this database is relative to the image, without changing anything.

    The application does not migrate. A Helm pre-upgrade Job does that — one pod,
    before the new image starts — because the startup hook runs in every replica and
    Alembic does not lock, and because tying readiness to how long a migration takes
    means a slow one rolls back a release that was working.

    Deliberately has no way to fix what it finds. If it could, every replica could,
    which is the problem it exists to remove.
    """
    if current is None:
        # Never managed: a local run, or a first install the Job has not reached.
        # Stamping is what happens today, so keeping it leaves development alone.
        return "stamp"
    if current == head:
        return "ok"
    # Ahead means a rollback left the schema forward. Serving anyway is the
    # expand/contract mistake, and it should be loud here rather than a column error
    # at whichever endpoint touches the difference first.
    return "behind" if current < head else "ahead"


def head_revision() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini, scripts = _paths()
    cfg = Config(ini)
    cfg.set_main_option("script_location", scripts)
    return ScriptDirectory.from_config(cfg).get_current_head() or BASELINE_REVISION


async def current_revision(pool) -> "str | None":
    async with pool.acquire() as c:
        if not await c.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL"):
            return None
        return await c.fetchval("SELECT version_num FROM alembic_version LIMIT 1")


def main() -> int:
    """Entry point for the pre-upgrade Job: `python -m app.migrations`.

    Exits non-zero on failure so the Job fails, which stops the release before the
    new image is rolled out. That is the ordering the whole split exists for: the
    schema moves first, once, and if it cannot then nothing else happens.
    """
    import asyncio
    import logging
    import sys

    logging.basicConfig(level=logging.INFO, format="[migrate] %(message)s")
    log = logging.getLogger("migrate")

    async def run() -> int:
        from app.api.connectors import get_db_pool

        pool = await get_db_pool()
        try:
            outcome = await apply(pool)
        except Exception as e:
            log.error("failed: %s", e)
            return 1
        log.info("%s (head=%s)", outcome, head_revision())
        return 0

    return asyncio.run(run())


if __name__ == "__main__":
    import sys
    sys.exit(main())


# The tables the product cannot answer a request without. Deliberately short: listing
# all 41 would fail on any deployment with an optional feature switched off, and a
# check that cries wolf is a check nobody reads.
CORE_TABLES = (
    "users",
    "ai_collections",
    "ai_chunks",
    "api_keys",
    "auth_audit_log",
)


def missing_tables(present) -> list:
    """Which core tables are absent, sorted.

    alembic_version says migrations ran; it does not say the tables exist. A
    deployment where a bootstrap silently failed before this retrofit was stamped at
    the baseline anyway, because stamping records a decision rather than an
    inspection. This looks.
    """
    return sorted(set(CORE_TABLES) - set(present or ()))


async def present_tables(pool) -> set:
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
    return {r["tablename"] for r in rows}
