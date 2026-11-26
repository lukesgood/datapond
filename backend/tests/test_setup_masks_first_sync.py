"""The setup page saves masked columns with the table choices (PUT /connectors/{id}/tables),
so the first sync, which it starts right after Create, already masks them. They could
only be set on the source page before, after that sync had run."""
import asyncio
import json

import pytest
from fastapi import HTTPException

from app.api import connectors as mod

CID = "6f1b8a2e-0000-4000-8000-000000000002"
USER = {"id": "6f1b8a2e-0000-4000-8000-0000000000aa", "username": "eng", "role": "data_engineer"}


class _Conn:
    def __init__(self, rows=()):
        self.rows, self.calls = list(rows), []

    async def fetch(self, sql, *args):
        return self.rows

    async def execute(self, sql, *args):
        self.calls.append((sql, args))

    def transaction(self):
        class _T:
            async def __aenter__(self): return None
            async def __aexit__(self, *a): return False
        return _T()


@pytest.fixture
def db(monkeypatch):
    conn = _Conn()

    class _Pool:
        def acquire(self):
            class _C:
                async def __aenter__(self): return conn
                async def __aexit__(self, *a): return False
            return _C()

    async def _pool(): return _Pool()
    async def _access(*a, **k): return None
    monkeypatch.setattr(mod, "get_db_pool", _pool)
    monkeypatch.setattr(mod, "require_access", _access)
    return conn


def test_a_new_table_is_saved_with_its_masked_columns(db):
    asyncio.run(mod.set_tables(CID, {"tables": [
        {"table": "customers", "enabled": True, "pii_columns": ["email", "phone"]},
        {"table": "orders", "enabled": True}]}, user=USER))
    (sql1, a1), (sql2, a2) = db.calls
    assert "pii_columns" in sql1 and json.loads(a1[-1]) == ["email", "phone"]
    assert a2[-1] is None


def test_an_existing_table_keeps_its_masks_unless_the_item_names_them(db):
    db.rows = [{"source_table": "customers", "target_table": "customers", "enabled": True}]
    asyncio.run(mod.set_tables(CID, {"tables": [{"table": "customers", "enabled": False}]}, user=USER))
    assert "pii_columns" not in db.calls[0][0]
    db.calls.clear()
    asyncio.run(mod.set_tables(CID, {"tables": [{"table": "customers", "pii_columns": ["*"]}]}, user=USER))
    assert "pii_columns" in db.calls[0][0] and json.loads(db.calls[0][1][-1]) == ["*"]


def test_masks_that_are_not_column_names_are_refused(db):
    with pytest.raises(HTTPException) as e:
        asyncio.run(mod.set_tables(CID, {"tables": [{"table": "t", "pii_columns": "email"}]}, user=USER))
    assert e.value.status_code == 400
