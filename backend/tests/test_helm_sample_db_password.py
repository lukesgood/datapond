"""The sample role's password is born in the chart and reaches the two places that need
it: the migration Job that creates the role and the backend that connects as it."""
import re

from tests.test_helm_trino_extra_catalogs import render, doc


def _job(out, label):
    for part in out.split("\n---"):
        if re.search(r"^kind: Job$", part, re.M) and label in part:
            return part
    raise AssertionError(f"no Job mentioning {label}")


def _env_of(part, container):
    """The env names of one container of a rendered pod spec (YAML-parsed, so an env
    on the init container does not pass for one on the application container — the
    first CI run of 2.5 had exactly that: the backend pod never saw the variable)."""
    import yaml
    spec = yaml.safe_load(part)["spec"]["template"]["spec"]
    for c in spec.get("containers", []) + spec.get("initContainers", []):
        if c["name"] == container:
            return {e["name"]: e for e in c.get("env", [])}
    raise AssertionError(f"no container {container}")


def test_the_password_is_generated_and_reaches_the_migration_job_and_the_backend(tmp_path):
    out = render(tmp_path)
    secret = doc(out, "Secret", "datapond-secrets")
    m = re.search(r'SAMPLE_DB_PASSWORD: "([A-Za-z0-9]+)"', secret)
    assert m and len(m.group(1)) == 32, "lookup-preserved randAlphaNum 32"
    for part, container in ((_job(out, "app.migrations"), "migrate"),
                            (doc(out, "Deployment", "backend"), "backend")):
        env = _env_of(part, container)
        assert "SAMPLE_DB_PASSWORD" in env, f"{container} container lacks SAMPLE_DB_PASSWORD"
        ref = dict(env["SAMPLE_DB_PASSWORD"]["valueFrom"]["secretKeyRef"])
        ref.pop("optional", None)
        assert ref == {"name": "datapond-secrets", "key": "SAMPLE_DB_PASSWORD"}


def test_an_explicit_value_wins(tmp_path):
    out = render(tmp_path, "postgres:\n  auth:\n    samplePassword: Explicit12345678\n")
    assert 'SAMPLE_DB_PASSWORD: "Explicit12345678"' in doc(out, "Secret", "datapond-secrets")


def test_the_aws_reference_profile_renders_it_too(tmp_path):
    out = render(tmp_path, values="values-prod-single.yaml")
    assert "SAMPLE_DB_PASSWORD" in doc(out, "Secret", "datapond-secrets")
