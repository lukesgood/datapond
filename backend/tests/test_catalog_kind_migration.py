"""0027: the registry's kind check admits every kind the registry knows.

The first CI run of 2.5 registered a source catalog and PostgreSQL refused the row:
0018's CHECK listed three kinds and nothing had widened it (CI finding, Task 9)."""
import importlib.util
import re
from pathlib import Path

from app import catalog_registry

VERSIONS = Path(__file__).resolve().parents[1] / "migrations/versions"
PY = VERSIONS / "0027_catalog_kind_trino_source.py"
SQL = PY.with_suffix(".sql")


def _load():
    spec = importlib.util.spec_from_file_location("m0027", PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_it_chains_from_0026_below_the_newest_revision():
    m = _load()
    assert m.revision == "0027_catalog_kind_trino_source" and len(m.revision) <= 32
    assert m.down_revision == "0026_sample_db_role"
    stems = sorted(p.stem for p in VERSIONS.glob("*.py") if re.fullmatch(r"\d{4}_[a-z0-9_]+", p.stem))
    assert stems[-1] == "0029_more_audit_event_types"


def test_the_check_is_replaced_and_lists_every_registry_kind():
    sql = SQL.read_text()
    assert "DROP CONSTRAINT IF EXISTS data_catalogs_kind_check" in sql
    added = re.search(r"ADD CONSTRAINT data_catalogs_kind_check\s+CHECK \(kind IN \(([^)]*)\)\)", sql)
    assert added, sql
    assert set(re.findall(r"'([a-z_]+)'", added.group(1))) == set(catalog_registry.KINDS)
