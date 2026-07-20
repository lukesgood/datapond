"""Regression tests for the transform-name code-injection fix.

A transform name is interpolated into the generated Airflow DAG source, so it must
be validated to a safe charset AND sanitized before interpolation — otherwise a name
containing triple-quotes/newlines could break out of the docstring and inject Python
that the Airflow worker executes.
"""
from types import SimpleNamespace

import pytest

# transforms.py runs Base.metadata.create_all(bind=engine) at import time (a live
# DDL). Neutralize it so these pure-logic tests need no database.
import app.database.connection as _dbc
_dbc.Base.metadata.create_all = lambda *a, **k: None  # type: ignore[assignment]

from pydantic import ValidationError
from app.api import transforms


def _req(name):
    return transforms.TransformCreateRequest(
        name=name, source_namespace="raw", target_namespace="refined",
        target_table="t", sql="SELECT 1",
    )


def test_transform_name_rejects_injection_and_junk():
    injection = 'x\n"""\nimport os; os.system("touch /tmp/pwned")\n"""'
    for bad in (injection, 'a"""b', "back\\slash", "semi;colon", "", "x" * 65, "타이틀"):
        with pytest.raises(ValidationError):
            _req(bad)


def test_transform_name_accepts_normal_names():
    for ok in ("daily sales", "etl_job-1", "Refined Orders"):
        assert _req(ok).name == ok


def test_generated_dag_sanitizes_name_in_docstring_header():
    """Defense in depth: even a raw, unvalidated name must not break out of the
    generated DAG's leading docstring."""
    malicious = SimpleNamespace(
        name='evil\n"""\nINJECT_MARKER\n"""',
        description=None, source_namespace="raw", target_namespace="refined",
        target_table="t", sql="SELECT 1", schedule=None,
    )
    dag = transforms._generate_dag(malicious)
    # The name is interpolated into the header line of the leading docstring. After
    # sanitizing, that line must contain no triple-quote (which would close the
    # docstring early and let the rest run as code), and the payload stays inline
    # (newlines collapsed to spaces) rather than escaping onto its own line.
    header = next(l for l in dag.splitlines() if l.startswith("Auto-generated ELT transform DAG:"))
    assert '"""' not in header
    assert "INJECT_MARKER" in header
