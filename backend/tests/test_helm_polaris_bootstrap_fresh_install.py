"""The Polaris bootstrap runs on a fresh install.

It was a pre-install/pre-upgrade hook. A pre-install hook runs before any of the
release's ordinary resources exist, and this Job reads `datapond-secrets` and connects
to the in-cluster Postgres — both ordinary resources of the same release. On an
upgrade they were already there, so nothing noticed; a fresh install with Polaris on
(values-onprem, the base extended profile) sat in CreateContainerConfigError until
Helm timed out. The two-catalog CI job was the first fresh install with Polaris.

It is now an ordinary Job named per revision, like backend-migrate-<rev>: created with
the Secret and Postgres, waiting for Postgres itself, and idempotent (it short-circuits
on a realm that is already bootstrapped). Polaris waits for the schema, not the Job.
"""
import re
import subprocess
from pathlib import Path

CHART = Path(__file__).resolve().parents[2] / "helm/datapond"


def _bootstrap(values="values-onprem.yaml", revision=None):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond",
           "-f", str(CHART / values)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for part in r.stdout.split("\n---"):
        if "component: catalog-bootstrap" in part and "kind: Job" in part:
            return part
    raise AssertionError("polaris bootstrap Job not rendered")


def test_the_bootstrap_is_not_a_pre_install_hook():
    job = _bootstrap()
    assert "helm.sh/hook" not in job


def test_its_name_changes_per_revision_so_an_upgrade_can_create_it_again():
    job = _bootstrap()
    assert re.search(r"^  name: polaris-bootstrap-\d+$", job, re.M), job[:400]


def test_it_still_waits_for_postgres_and_short_circuits_when_bootstrapped():
    job = _bootstrap()
    assert "pg_isready" in job
    assert "principal_authentication_data" in job
