"""Evidence that personal data did not reach the lake (design thinking D1): for each
synced table, the columns masked at sync time, and a sample of the lake table scanned for
values that still look like Korean identifiers, phone numbers, emails or cards."""
import asyncio

from app import pii_evidence as pe

SAMPLE = {
    "email": ["a***@example.com", "b***@example.com"],
    "phone": ["010-1234-5678", "010-****-5678"],
    "note": ["hello", None],
}


def test_masked_columns_and_raw_values_are_reported_per_column():
    r = pe.assess("iceberg.default.customers", configured=["email"], samples=SAMPLE)
    cols = {c["column"]: c for c in r["columns"]}
    assert cols["email"]["masked_at_sync"] is True and cols["email"]["raw_found"] == 0
    assert cols["phone"]["masked_at_sync"] is False and cols["phone"]["raw_found"] == 1
    assert cols["phone"]["types"] == ["휴대전화"]
    assert r["status"] == "raw_found" and r["raw_columns"] == ["phone"]
    assert "010-1234-5678" not in str(r), "the evidence never repeats the raw value"


def test_a_clean_table_is_ok_and_star_means_every_string_column():
    r = pe.assess("iceberg.default.t", configured=["*"], samples={"email": ["x***@y.com"], "note": ["hi"]})
    assert r["status"] == "ok" and all(c["masked_at_sync"] for c in r["columns"])


def test_a_table_that_could_not_be_sampled_is_unverified():
    r = pe.assess("iceberg.default.t", configured=[], samples=None, error="Table not found")
    assert r["status"] == "unverified" and "not found" in r["error"]


def test_the_route_returns_tables_and_an_ndjson_export(monkeypatch):
    async def _jobs():
        return [{"table": "iceberg.default.customers", "source": "Sample DB", "source_table": "public.customers",
                 "configured": ["email"], "last_run_at": "2026-11-13T08:10:00"}]
    monkeypatch.setattr(pe, "_load_jobs", _jobs)
    monkeypatch.setattr(pe, "_sample", lambda table: (SAMPLE, None))
    pe.reset_cache()
    out = asyncio.run(pe.collect())
    assert out["tables"][0]["status"] == "raw_found" and out["summary"] == {"tables": 1, "ok": 0, "raw_found": 1, "unverified": 0}
    lines = pe.to_ndjson(out).strip().split("\n")
    assert len(lines) == 1 and '"raw_columns": ["phone"]' in lines[0]
