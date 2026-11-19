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


def test_schedule_accepts_cron_and_presets_and_none():
    for ok, want in (("0 3 * * *", "0 3 * * *"), ("*/15  * * * *", "*/15 * * * *"),
                     ("@daily", "@daily"), ("", None), (None, None), ("None", None),
                     ("0 9 * * MON-FRI", "0 9 * * MON-FRI")):
        r = transforms.TransformCreateRequest(name="a", source_namespace="raw", target_namespace="refined",
                                              target_table="t", sql="SELECT 1", schedule=ok)
        assert r.schedule == want


def test_schedule_and_namespace_reject_quotes():
    """Both reach the generated DAG source: a quote would end the string."""
    for bad in ('0 3 * * *"\nimport os', "@daily'", "0 3 * *", "every day"):
        with pytest.raises(ValidationError):
            transforms.TransformUpdateRequest(schedule=bad)
    with pytest.raises(ValidationError):
        transforms.TransformUpdateRequest(source_namespace='raw"""\nimport os')


def test_generated_dag_quotes_schedule_and_namespace_safely():
    """Defense in depth for rows saved before validation."""
    row = SimpleNamespace(
        name="x", description=None, source_namespace='raw"""\nBAD_NS', target_namespace="refined",
        target_table="t", sql="SELECT 1", schedule='0 3 * * *"\nBAD_SCHEDULE = 1  #',
    )
    dag = transforms._generate_dag(row)
    compile(dag, "dag.py", "exec")  # still valid Python
    assert not any(l.startswith("BAD_SCHEDULE") or l.startswith("BAD_NS") for l in dag.splitlines())


def test_check_reports_bad_sql_as_ok_false(monkeypatch):
    import asyncio
    out = asyncio.run(transforms.check_transform(transforms.TransformCheckRequest(sql="DROP TABLE x")))
    assert out["ok"] is False and "SELECT" in out["error"]

    monkeypatch.setattr(transforms, "_output_columns", lambda sql: [{"name": "day", "type": "date"}])
    out = asyncio.run(transforms.check_transform(transforms.TransformCheckRequest(sql="SELECT 1 AS day")))
    assert out == {"ok": True, "error": None, "columns": [{"name": "day", "type": "date"}]}

    def boom(sql):
        raise RuntimeError("Table 'iceberg.refined.nope' does not exist")
    monkeypatch.setattr(transforms, "_output_columns", boom)
    out = asyncio.run(transforms.check_transform(transforms.TransformCheckRequest(sql="SELECT * FROM refined.nope")))
    assert out["ok"] is False and "does not exist" in out["error"]
