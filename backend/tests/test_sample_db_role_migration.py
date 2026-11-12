"""0026: the restricted login role the SQL samples connect through.

Until Phase 2 the sample connectors carried the application's own PostgreSQL password,
so a sample source was a path to every table the backend can reach. Trino now reads
the samples as a catalog, with a role that may only SELECT from the sample databases.
"""
import importlib.util
import re
from pathlib import Path

import pytest

PY = Path(__file__).resolve().parents[1] / "migrations/versions/0026_sample_db_role.py"


def _load():
    spec = importlib.util.spec_from_file_location("m0026", PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_it_chains_from_0025_below_the_newest_revision():
    m = _load()
    assert m.revision == "0026_sample_db_role"
    assert m.down_revision == "0025_glue_engine_catalog_trino"
    stems = sorted(p.stem for p in PY.parent.glob("*.py") if re.fullmatch(r"\d{4}_[a-z0-9_]+", p.stem))
    assert stems[-1] == "0028_catalog_table_links"


def test_the_statement_creates_or_rotates_the_login_role():
    sql = _load().upgrade_statement("Abc123Abc123Abc123")
    assert "CREATE ROLE datapond_sample LOGIN PASSWORD 'Abc123Abc123Abc123'" in sql
    assert "ALTER ROLE datapond_sample WITH LOGIN PASSWORD 'Abc123Abc123Abc123'" in sql
    assert "pg_roles" in sql and "rolname = 'datapond_sample'" in sql.replace("rolname='", "rolname = '")
    assert "SUPERUSER" not in sql and "CREATEDB" not in sql


def test_an_unset_or_unsafe_password_is_refused_or_skipped():
    m = _load()
    assert m.sample_password({}) is None
    assert m.sample_password({"SAMPLE_DB_PASSWORD": ""}) is None
    assert m.sample_password({"SAMPLE_DB_PASSWORD": "Abc123Abc123Abc123"}) == "Abc123Abc123Abc123"
    for bad in ("x'; DROP ROLE datapond_app; --", "short", "a" * 65, "has space 1234567890"):
        with pytest.raises(ValueError):
            m.sample_password({"SAMPLE_DB_PASSWORD": bad})


def test_upgrade_runs_the_statement_only_with_a_password(monkeypatch):
    m = _load()
    ran = []
    monkeypatch.setattr(m, "run_sql", lambda bind, sql: ran.append(sql))
    monkeypatch.setattr(m.op, "get_bind", lambda: object(), raising=False)
    monkeypatch.delenv("SAMPLE_DB_PASSWORD", raising=False)
    m.upgrade()
    assert ran == []
    monkeypatch.setenv("SAMPLE_DB_PASSWORD", "Abc123Abc123Abc123")
    m.upgrade()
    assert len(ran) == 1 and "datapond_sample" in ran[0]
    m.downgrade()
    assert len(ran) == 1, "the role may own grants; downgrade leaves it"
