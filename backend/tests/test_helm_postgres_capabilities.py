"""postgres had no security context at all — root, every capability, no seccomp.

The image is the official `postgres`-derived `pgvector/pgvector` build, whose
`docker-entrypoint.sh` runs as root and steps down the same way valkey's does:

  find ... chown postgres  → CHOWN            (docker_create_db_directories(), only
                                               when `id -u` = 0, to take ownership of
                                               PGDATA / /var/run/postgresql so the
                                               postgres user can write them)
  exec gosu postgres ...   → SETUID, SETGID   (the actual privilege drop; gosu calls
                                               setresgid/setgroups/setresuid directly,
                                               no setpriv involved here)

The entrypoint also runs `chmod 00700 "$PGDATA" || :` and
`chmod 03775 /var/run/postgresql || :` — both suffixed `|| :`, so a chmod that fails
for lack of FOWNER is swallowed, not fatal (the mode is already correct after the
first init; this only matters on restart of an existing volume). `chmod 700` on a
custom WAL dir has no `|| :`, but nothing in this chart sets
POSTGRES_INITDB_WALDIR, so that path never runs. FOWNER and DAC_OVERRIDE are
therefore not in the keep list: they are not exercised by this deployment's
configuration, unlike CHOWN/SETUID/SETGID which run on every single start.

Same three capabilities as valkey, same reasoning: keep exactly what the documented
entrypoint uses to become non-root, nothing else.
"""
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "helm/datapond/templates"
TEMPLATE = TEMPLATES_DIR / "postgres-statefulset.yaml"

# Templates for workloads (Deployment/StatefulSet/Job) that carry neither
# datapond.podSecurity nor datapond.containerSecurity, as of this task. This is a
# known, written-down gap — not every one of these images has been checked against
# a real cluster the way valkey and postgres have — so the list is asserted exactly.
# Removing a name here without adding a security context is the regression this test
# exists to catch; adding a new such template without a context should fail it too.
KNOWN_WORKLOADS_WITHOUT_SECURITY_CONTEXT = {
    "airflow-deployment.yaml",
    "jupyter-deployment.yaml",
    "litellm-ollama-init-job.yaml",
    "litellm-vllm-init-job.yaml",
    "minio-bucket-init-job.yaml",
    "minio-deployment.yaml",
    "mlflow-deployment.yaml",
    "mock-model-deployment.yaml",
    "ollama-deployment.yaml",
    "openmetadata-deployment.yaml",
    "polaris-bootstrap-job.yaml",
    "polaris-catalog-init-job.yaml",
    "polaris-deployment.yaml",
    "risingwave-statefulset.yaml",
    "spark-statefulset.yaml",
    "trino-deployment.yaml",
    "vllm-deployment.yaml",
}


def test_postgres_carries_a_container_security_context():
    body = TEMPLATE.read_text()
    assert "datapond.containerSecurity" in body


def test_postgres_keeps_the_capabilities_its_entrypoint_uses():
    body = TEMPLATE.read_text()
    line = next(l for l in body.splitlines() if "datapond.containerSecurity" in l)
    for capability in ("SETUID", "SETGID", "CHOWN"):
        assert capability in line, f"postgres will CrashLoop without {capability}: {line}"


def test_nothing_else_is_kept():
    """The list is what the entrypoint needs, not a convenient allowance."""
    line = next(l for l in TEMPLATE.read_text().splitlines()
                if "datapond.containerSecurity" in l)
    for capability in ("NET_ADMIN", "SYS_ADMIN", "DAC_OVERRIDE", "FOWNER", "ALL"):
        assert capability not in line, f"{capability} is not needed to become non-root"


def test_postgres_does_not_claim_a_numeric_uid_here():
    """runAsNonRoot/runAsUser is datapond.podSecurity, not this task.

    The postgres image's UID has not been confirmed against the running image, so
    claiming one would be a guess dressed up as hardening. containerSecurity alone
    (no privilege escalation, capability drop, seccomp) is what can be justified
    without that confirmation.
    """
    body = TEMPLATE.read_text()
    assert "datapond.podSecurity" not in body
    assert "runAsUser" not in body


def test_the_remaining_gap_is_the_known_list_not_a_surprise():
    """Every add-on workload without a security context should be a named, reviewed
    gap — not something this test silently tolerates forever. If a template gains
    one, shrink the known list here in the same change. If a *new* templated
    workload appears without one, this fails until it's added to the list on
    purpose, so the gap can't grow unnoticed.
    """
    workload_globs = ("*deployment*.yaml", "*statefulset*.yaml", "*job*.yaml")
    found = set()
    for pattern in workload_globs:
        for path in TEMPLATES_DIR.glob(pattern):
            body = path.read_text()
            if "datapond.containerSecurity" not in body and "datapond.podSecurity" not in body:
                found.add(path.name)

    assert found == KNOWN_WORKLOADS_WITHOUT_SECURITY_CONTEXT
