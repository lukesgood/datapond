"""0025: the glue catalog row's engine name becomes Trino's (`iceberg`), nothing else.

The 2.4 cutover keeps `AwsDataCatalog` as the registry name (stored policies, metrics,
joins and chunk sources carry it) and changes only what the engine is told to call the
catalog. The statement is built from TRINO_CATALOG, so it is pinned here as text.
"""
import importlib.util
import re
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "migrations/versions"
PY = VERSIONS / "0025_glue_engine_catalog_trino.py"


def _load():
    spec = importlib.util.spec_from_file_location("m0025", PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_highest_revision_is_known():
    stems = sorted(p.stem for p in VERSIONS.glob("*.py") if re.fullmatch(r"\d{4}_[a-z0-9_]+", p.stem))
    assert stems[-1] == "0028_catalog_table_links"      # the pin moves with the newest revision


def test_it_chains_from_0024():
    m = _load()
    assert m.down_revision == "0024_ai_budget_caps"


def test_only_the_engine_name_of_the_pre_24_glue_row_changes():
    m = _load()
    stmt = m.upgrade_statement(m.engine_catalog_name({}))
    assert stmt == ("UPDATE public.data_catalogs SET engine_catalog = 'iceberg' "
                    "WHERE kind = 'glue' AND engine_catalog = 'AwsDataCatalog'")
    assert "SET name" not in stmt  # the registry name is the alias and stays


def test_the_target_name_follows_trino_catalog():
    m = _load()
    assert m.engine_catalog_name({"TRINO_CATALOG": "lake"}) == "lake"
    assert "engine_catalog = 'lake'" in m.upgrade_statement("lake")


def test_a_non_identifier_catalog_name_is_refused_not_interpolated():
    m = _load()
    with pytest.raises(ValueError):
        m.engine_catalog_name({"TRINO_CATALOG": "x'; DROP TABLE data_catalogs; --"})


def test_downgrade_restores_only_the_row_it_changed():
    m = _load()
    stmt = m.downgrade_statement("iceberg")
    assert "SET engine_catalog = 'AwsDataCatalog'" in stmt
    assert "name = 'AwsDataCatalog' AND engine_catalog = 'iceberg'" in stmt
