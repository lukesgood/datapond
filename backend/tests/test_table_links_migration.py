"""0028: the owner/mirror links between catalogs, and the catalog a sync writes into."""
import importlib.util
import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations/versions"
PY = VERSIONS / "0028_catalog_table_links.py"


def _load():
    spec = importlib.util.spec_from_file_location("m0028", PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_it_is_the_newest_revision_and_chains_from_0027():
    m = _load()
    assert m.revision == "0028_catalog_table_links" and len(m.revision) <= 32
    assert m.down_revision == "0027_catalog_kind_trino_source"
    stems = sorted(p.stem for p in VERSIONS.glob("*.py") if re.fullmatch(r"\d{4}_[a-z0-9_]+", p.stem))
    assert stems[-1] == "0028_catalog_table_links"


def test_the_links_table_keys_a_mirror_once_and_the_sync_target_is_nullable():
    sql = PY.with_suffix(".sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.catalog_table_links" in sql
    assert "PRIMARY KEY (mirror_catalog, mirror_schema, mirror_table)" in sql
    for col in ("owner_catalog", "owner_schema", "owner_table", "location", "mirror_metadata_file", "status"):
        assert col in sql
    assert re.search(r"ALTER TABLE public\.connector_sync_jobs\s+ADD COLUMN IF NOT EXISTS target_catalog text", sql)
