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
import os
from typing import Literal

BASELINE_REVISION = "0001_baseline"

# Only one replica may build an empty database. `apply()` is called from the startup
# hook, which runs in every replica, and Alembic takes no lock of its own — so two
# pods issuing the baseline's CREATE TABLEs at the same moment is a race the tooling
# does nothing about. Distinct from system_events.LOCK_KEY (…965),
# rag_scheduler.LOCK_KEY (…964) and audit_retention.LOCK_KEY (…971): two features
# sharing a key means one of them silently never runs.
MIGRATION_LOCK_KEY = 7233183143331076972

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
        # Recording where a database already is changes nothing in it, so it needs no
        # lock: two processes stamping the same revision write the same row.
        await asyncio.to_thread(command.stamp, cfg, BASELINE_REVISION)
        return f"stamped {BASELINE_REVISION}"

    # An upgrade issues DDL, and this function has two callers: the migration Job, and
    # the startup hook in every replica when the database has never been migrated.
    # Alembic takes no lock, so two of them at once is a race nothing else prevents.
    # Waiting rather than skipping, because the Job must never report success on a
    # migration it did not run — the loser waits, acquires, and finds the work already
    # done, which makes `upgrade head` a no-op rather than a silent no-migration.
    wait = float(os.getenv("MIGRATE_LOCK_WAIT_SECONDS", "300"))
    async with pool.acquire() as c:
        if not await _hold_migration_lock(c, wait):
            raise TimeoutError(
                f"another process has held the migration lock for {wait:.0f}s — "
                "not migrating on top of it")
        try:
            await asyncio.to_thread(command.upgrade, cfg, "head")
        finally:
            await c.execute("SELECT pg_advisory_unlock($1)", MIGRATION_LOCK_KEY)
    return "upgraded to head"


async def _hold_migration_lock(c, timeout: float) -> bool:
    """Take MIGRATION_LOCK_KEY, waiting up to `timeout` seconds. False if it timed out.

    Polling try-lock rather than the blocking `pg_advisory_lock`: a blocking call has
    no timeout of its own, so a holder that hangs takes the release with it and there
    is nothing in the logs to say what it is waiting for.
    """
    import asyncio as _asyncio
    import time as _time

    deadline = _time.monotonic() + timeout
    while True:
        if await c.fetchval("SELECT pg_try_advisory_lock($1)", MIGRATION_LOCK_KEY):
            return True
        if _time.monotonic() >= deadline:
            return False
        await _asyncio.sleep(1.0)


def state_after_apply(current: "str | None", head: str) -> "tuple[bool, str]":
    """(ready, detail) once `apply()` has run — the honest version of what it did.

    `apply()` stamps `BASELINE_REVISION`, not head, whenever the tables exist and
    Alembic has never been here: an installation that predates migrations is at 0001,
    and every revision since is still unapplied. The startup hook used to record
    `stamped {head}` and mark itself ready, which is two claims the database does not
    support — so a pod upgraded without the migration Job having run served traffic
    against a schema several revisions behind. That is not a slow failure: connector
    routes 500 on the missing column and authorization denials cannot write their
    audit row, which is the one record that must not be lost quietly.

    `CORE_TABLES` does not catch it either — those five tables all predate the gap.
    The revision is the only thing that knows, so it is what decides readiness, and
    unknown counts as behind: fail closed, exactly as the `behind` state already does.
    """
    if current is not None and current == head:
        return True, f"at {head}"
    return False, (
        f"database is at {current or 'no revision'}, this image expects {head} — "
        "run the migration job for this release"
    )


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


def should_keep_waiting(reachable: bool, elapsed: float, timeout: float) -> bool:
    """Whether to keep waiting for the database to accept connections.

    Waiting is not retrying. The migration itself gets one attempt — backoffLimit is 0,
    and a partial failure retried can leave a worse state than the first. But the Job
    is an ordinary manifest resource now, so it starts alongside Postgres rather than
    after it, and a closed socket is not a failed migration.

    It gives up rather than hanging: a Job that never exits is worse than one that
    fails, because nothing reports it and `helm --wait` sits there until its own
    timeout with no reason recorded.
    """
    return (not reachable) and elapsed <= timeout


def schema_ready(present) -> bool:
    """Whether the core tables are all there. See CORE_TABLES."""
    return not missing_tables(present)


async def open_pool(acquire=None, timeout: float = 300.0, interval: float = 3.0):
    """A connection pool, once the database will give one. None if it never does.

    The retry has to wrap the connect. The Job used to wait for the database *after*
    calling get_db_pool(), which raises on a refused connection — so with backoffLimit
    0 the Job went straight to Error, the schema was never created, and the backend's
    init container then waited out its whole timeout for something that would never
    arrive. One misplaced line, and every symptom pointed somewhere else.
    """
    import asyncio
    import logging
    import time

    if acquire is None:
        from app.api.connectors import get_db_pool as acquire
    log = logging.getLogger("migrate")
    started = time.monotonic()
    while True:
        try:
            return await acquire()
        except Exception as e:
            elapsed = time.monotonic() - started
            if not should_keep_waiting(reachable=False, elapsed=elapsed, timeout=timeout):
                log.error("database did not accept connections within %.0fs: %s",
                          timeout, str(e)[:200])
                return None
            log.info("waiting for the database (%.0fs): %s", elapsed, str(e)[:120])
        await asyncio.sleep(interval)


async def wait_for_schema(timeout: float = 600.0, interval: float = 3.0) -> int:
    """Block until the core tables exist. Used by the backend's init container.

    It waits; it never migrates. Every replica runs this, Alembic does not lock, and
    removing that race is the entire reason the migration lives in its own Job.

    Readiness records `base_schema` once, at startup. A backend that starts before the
    schema exists is therefore not merely slow — it is permanently NotReady until
    something restarts it. Waiting here is what makes the ordering hold without the
    application ever touching a migration.
    """
    import asyncio
    import logging
    import time

    from app.api.connectors import get_db_pool

    log = logging.getLogger("migrate")
    started = time.monotonic()
    reason = "not started"
    while True:
        elapsed = time.monotonic() - started
        try:
            pool = await get_db_pool()
            present = await present_tables(pool)
            if schema_ready(present):
                log.info("schema present after %.0fs", elapsed)
                return 0
            reason = f"missing {', '.join(missing_tables(present))}"
        except Exception as e:
            # Named, never swallowed. This loop once turned a NameError into "not yet"
            # and waited ten minutes in silence for a schema that was already there.
            reason = f"{type(e).__name__}: {e}"[:200]
        log.info("waiting for the schema (%.0fs): %s", elapsed, reason)
        if not should_keep_waiting(reachable=False, elapsed=elapsed, timeout=timeout):
            log.error("gave up after %.0fs: %s", elapsed, reason)
            return 1
        await asyncio.sleep(interval)


def main() -> int:
    """Entry point for the migration Job: `python -m app.migrations`.

    `--wait-for-schema` instead blocks until the tables exist and applies nothing —
    that mode is the backend's init container.

    Exits non-zero on failure so the Job fails, which stops the release before the new
    image serves anything. That is the ordering the whole split exists for: the schema
    moves first, once, and if it cannot then nothing else happens.
    """
    import asyncio
    import logging
    import sys

    logging.basicConfig(level=logging.INFO, format="[migrate] %(message)s")
    log = logging.getLogger("migrate")

    if "--wait-for-schema" in sys.argv:
        timeout = float(os.getenv("MIGRATE_WAIT_SECONDS", "600"))
        code = asyncio.run(wait_for_schema(timeout))
        log.info("schema wait %s", "satisfied" if code == 0 else "timed out")
        return code

    async def run() -> int:
        # Wait for the database, not for a second chance at the migration. The Job is
        # an ordinary manifest resource now, so Postgres may still be starting beside
        # it, and a refused connection is not a failed migration.
        pool = await open_pool(timeout=float(os.getenv("MIGRATE_DB_WAIT_SECONDS", "300")))
        if pool is None:
            return 1

        try:
            outcome = await apply(pool)
        except Exception as e:
            log.error("failed: %s", e)
            return 1
        log.info("%s (head=%s)", outcome, head_revision())
        return 0

    return asyncio.run(run())


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


# Last, and it has to stay last: run as `python -m app.migrations`, execution reaches
# this and calls main() before anything below it is defined. It used to sit in the
# middle of the file, so present_tables and missing_tables did not exist on the script
# path — and only on the script path, which is why importing the module looked fine.
if __name__ == "__main__":
    import sys

    sys.exit(main())
