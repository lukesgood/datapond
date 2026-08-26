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


def baseline_action(has_tables: bool, has_version_table: bool) -> Action:
    """What to do with this database before the app serves traffic.

    `has_tables` — does the application schema already exist here.
    `has_version_table` — has Alembic been here before.

    Both paths without a version table stamp, for different reasons that reach the
    same place: an existing schema must not be recreated, and a fresh one is built by
    the bootstraps a moment later. Either way the version table ends up recording
    where the database actually is, which is the state every later migration relies
    on being true.
    """
    if has_version_table:
        return "upgrade"
    return "stamp"


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
