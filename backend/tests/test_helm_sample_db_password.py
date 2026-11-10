"""The sample role's password is born in the chart and reaches the two places that need
it: the migration Job that creates the role and the backend that connects as it."""
import re

from tests.test_helm_trino_extra_catalogs import render, doc


def _job(out, label):
    for part in out.split("\n---"):
        if re.search(r"^kind: Job$", part, re.M) and label in part:
            return part
    raise AssertionError(f"no Job mentioning {label}")


def test_the_password_is_generated_and_reaches_the_migration_job_and_the_backend(tmp_path):
    out = render(tmp_path)
    secret = doc(out, "Secret", "datapond-secrets")
    m = re.search(r'SAMPLE_DB_PASSWORD: "([A-Za-z0-9]+)"', secret)
    assert m and len(m.group(1)) == 32, "lookup-preserved randAlphaNum 32"
    for part in (_job(out, "app.migrations"), doc(out, "Deployment", "backend")):
        assert re.search(r"name: SAMPLE_DB_PASSWORD\s*\n\s+valueFrom:\s*\n\s+secretKeyRef:"
                         r"\s*\n?\s*\{?\s*name: datapond-secrets,?\s*\n?\s*key: SAMPLE_DB_PASSWORD", part), part[:400]


def test_an_explicit_value_wins(tmp_path):
    out = render(tmp_path, "postgres:\n  auth:\n    samplePassword: Explicit12345678\n")
    assert 'SAMPLE_DB_PASSWORD: "Explicit12345678"' in doc(out, "Secret", "datapond-secrets")


def test_the_aws_reference_profile_renders_it_too(tmp_path):
    out = render(tmp_path, values="values-prod-single.yaml")
    assert "SAMPLE_DB_PASSWORD" in doc(out, "Secret", "datapond-secrets")
