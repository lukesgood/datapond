"""Setup preview rows (POST /connectors/introspect include_sample) and who may test or
introspect a config — both connect to the host the request names."""
import asyncio

import pytest
from fastapi import HTTPException

from app.api import connectors as C


def test_sample_rows_are_json_safe_and_short():
    rows = C.sample_rows([{"id": 1, "name": "kim", "tags": ["a"], "meta": {"k": 1}, "x": float("nan"),
                           "long": "y" * 300, "ok": True, "none": None}] * 7)
    assert len(rows) == C.SAMPLE_ROWS
    r = rows[0]
    assert r["id"] == 1 and r["name"] == "kim" and r["ok"] is True and r["none"] is None
    assert r["tags"] == '["a"]' and r["meta"] == '{"k": 1}' and r["x"] is None
    assert len(r["long"]) == C.SAMPLE_CELL_CHARS + 1 and r["long"].endswith("…")
    assert C.sample_rows([3, "a"]) == [{"value": 3}, {"value": "a"}]
    assert C.sample_rows(None) == []


def _route(path):
    return next(r for r in C.router.routes if getattr(r, "path", None) == path and "POST" in r.methods)


@pytest.mark.parametrize("path", ["/connectors/test", "/connectors/introspect"])
def test_testing_and_introspecting_need_connector_write(path):
    """A viewer is refused before anything connects or any code runs."""
    deps = [d.call for d in _route(path).dependant.dependencies]
    assert "connector:write" in [getattr(d, "__datapond_authorization__", None) for d in deps]
    from app.permissions import has_permission
    assert not has_permission("viewer", "connector:write")


def test_stored_secrets_merge_only_for_someone_who_may_change_the_source(monkeypatch):
    async def deny(kind, cid, user, write=False):
        assert write is True
        raise HTTPException(status_code=404, detail="Connection not found")
    monkeypatch.setattr(C, "require_access", deny)

    async def no_pool():
        raise AssertionError("must not read stored credentials")
    monkeypatch.setattr(C, "get_db_pool", no_pool)
    with pytest.raises(HTTPException) as e:
        asyncio.run(C._merge_stored_secrets({"base_url": "https://evil.test", "auth_value": "••••••••"},
                                            "11111111-1111-1111-1111-111111111111", {"id": "u", "role": "data_engineer"}))
    assert e.value.status_code == 404
    # Nothing masked: nothing stored is read, so no check is needed.
    out = asyncio.run(C._merge_stored_secrets({"base_url": "https://x.test"}, "11111111-1111-1111-1111-111111111111", {}))
    assert out == {"base_url": "https://x.test"}


def test_introspect_returns_sample_rows_for_a_python_source(monkeypatch):
    code = "def fetch_data():\n    return [{'id': i, 'email': f'u{i}@x'} for i in range(9)]\n"
    req = C.ConnectionIntrospectRequest(connector_type="custom", config={"code": code, "table_name": "users"},
                                        include_sample=True)
    out = asyncio.run(C.introspect_connection(req, {"id": "u", "role": "admin"}))
    t = out["tables"][0]
    assert t["name"] == "users" and [c["name"] for c in t["columns"]] == ["id", "email"]
    assert t["sample"] == [{"id": i, "email": f"u{i}@x"} for i in range(5)]


def test_database_sources_get_no_sample(monkeypatch):
    assert C.ConnectorType.POSTGRESQL not in C.SAMPLE_TYPES
