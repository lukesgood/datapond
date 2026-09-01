"""How the schema gets there on a first install, without anything leaving the manifest.

The migration Job was a pre-install hook. That cannot work, for two reasons the
ephemeral install job found one after the other:

  1. `datapond-secrets`, which the Job reads its credentials from, is a main-phase
     resource — the Job pod sat in CreateContainerConfigError.
  2. With an in-cluster database there is no database yet. Hooks run before the
     Postgres the same release creates.

Moving it later does not work either: readiness records `base_schema` once, at
startup, so a backend that starts before the tables exist is not slow — it is
permanently NotReady until something restarts it.

So the Job is an ordinary manifest resource, and the backend waits for it in an init
container. Nothing leaves the manifest (see test_helm_namespace_ownership.py for what
that costs), the migration still runs exactly once in one pod, and the application
still never migrates.
"""
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "helm/datapond/templates"
JOB = (TEMPLATES / "migrate-job.yaml").read_text()
BACKEND = (TEMPLATES / "backend-deployment.yaml").read_text()


def test_the_migration_job_is_not_a_hook():
    assert "helm.sh/hook" not in JOB, (
        "a pre-install hook has no secret and no database; a post-install one is too "
        "late for a readiness check that runs once at startup")


def test_a_new_release_gets_a_new_job_rather_than_patching_an_immutable_one():
    """A Job's pod template cannot be patched. Without a name that moves, the second
    upgrade fails with `field is immutable` instead of migrating."""
    assert ".Release.Revision" in JOB


def test_the_migration_itself_is_still_attempted_once():
    """Waiting for a socket and retrying DDL are different things, and only one of
    them is dangerous. A partial migration retried can leave a worse state."""
    assert "backoffLimit: 0" in JOB


def test_the_backend_waits_for_the_schema_before_it_starts():
    assert "wait-for-schema" in BACKEND


def test_the_backend_init_container_waits_rather_than_migrating():
    """Every replica runs an init container. Alembic does not lock, and removing that
    race is the entire reason the Job exists."""
    block = BACKEND.split("wait-for-schema", 1)[1].split("containers:", 1)[0]
    assert "--wait-for-schema" in block
    for forbidden in ("alembic upgrade", "stamp"):
        assert forbidden not in block


def test_the_waiting_container_carries_the_same_database_credentials():
    """It reads the same database as the Job and the app. A wait against a different
    one would pass while the real schema was still missing."""
    block = BACKEND.split("wait-for-schema", 1)[1].split("containers:", 1)[0]
    assert "datapond-secrets" in block or "envFrom" in block


# ── TLS: the DDL connection has to obey the same setting as the app's ───────

def _database_urls() -> list:
    """Every DATABASE_URL these two templates build."""
    import re
    urls = []
    for text in (JOB, BACKEND):
        # Comment lines may sit between the name and the value; skip them rather than
        # matching only the shape this file happened to have on the day it was written.
        urls += re.findall(
            r'- name: DATABASE_URL\n(?:\s*#[^\n]*\n)*\s*value: "([^"]+)"', text)
    return urls


def test_the_migration_connection_carries_the_configured_sslmode():
    """POSTGRES_SSLMODE (default `require` for an external database) is read only by
    the application's asyncpg pool. Alembic connects through psycopg2 with
    DATABASE_URL, so a URL without sslmode silently falls back to libpq's `prefer` —
    the DDL connection to Aurora is then allowed to be plaintext while the operator
    asked for TLS, and nothing says so.

    Both templates build that URL, so both are checked: the Job that runs the
    migration and the init container that waits for it.
    """
    urls = _database_urls()
    assert len(urls) >= 2, "expected the Job and the wait-for-schema init container"
    for url in urls:
        assert "sslmode=$(POSTGRES_SSLMODE)" in url, (
            f"DATABASE_URL ignores POSTGRES_SSLMODE: {url}")
        # Only when there is an external database — the in-cluster Postgres branch
        # never defines POSTGRES_SSLMODE, and an unresolved $(…) would land in the
        # connection string verbatim.
        assert "externalDatabase.enabled" in url
