"""Collection PII mode and sensitivity: settable through the API, raising always
allowed, lowering only with governance:write."""
import asyncio
import uuid

import pytest
from fastapi import HTTPException

from app import collection_protection as cp
from app.api import ai_vectors as av

CID = uuid.uuid4()


def test_ordering():
    assert cp.lowers_pii("block", "mask") and cp.lowers_pii("mask", None)
    assert not cp.lowers_pii("mask", "block") and not cp.lowers_pii(None, "mask")
    assert cp.lowers_sensitivity("restricted", "internal") and cp.lowers_sensitivity("public", None)
    assert not cp.lowers_sensitivity("internal", "confidential")
    assert cp.valid_pii_mode(None) and not cp.valid_pii_mode("blok")
    assert cp.valid_sensitivity("restricted") and not cp.valid_sensitivity("secret")


class _Conn:
    def __init__(self, current):
        self.current, self.updates = current, []

    async def fetchrow(self, sql, *a):
        return self.current

    async def execute(self, sql, *a):
        self.updates.append((sql, a))
        return "UPDATE 1"


class _Ctx:
    def __init__(self, c):
        self.c = c

    async def __aenter__(self):
        return self.c

    async def __aexit__(self, *a):
        return False


def _patch(monkeypatch, body, user, current=None):
    conn = _Conn(current or {"pii_mode": "mask", "sensitivity": "confidential"})

    class _Pool:
        def acquire(self):
            return _Ctx(conn)

    async def _pool():
        return _Pool()

    async def _cid(c, name, user, write=False):
        return CID

    monkeypatch.setattr(av, "get_db_pool", _pool)
    monkeypatch.setattr(av, "_collection_id", _cid)
    out = asyncio.run(av.update_collection("kb", av.CollectionUpdate(**body), user=user))
    return out, conn


OWNER = {"id": str(uuid.uuid4()), "username": "ds", "role": "data_scientist"}
ADMIN = {"id": str(uuid.uuid4()), "username": "admin", "role": "admin"}


def test_raising_is_allowed_for_a_writer(monkeypatch):
    out, conn = _patch(monkeypatch, {"pii_mode": "block", "sensitivity": "restricted"}, OWNER)
    sql, args = conn.updates[0]
    assert "pii_mode" in sql and "sensitivity" in sql and args[1:] == ("block", "restricted")


@pytest.mark.parametrize("body", [{"pii_mode": "off"}, {"pii_mode": None}, {"sensitivity": "public"}])
def test_lowering_needs_governance_write(body, monkeypatch):
    with pytest.raises(HTTPException) as exc:
        _patch(monkeypatch, body, OWNER)
    assert exc.value.status_code == 403
    out, conn = _patch(monkeypatch, body, ADMIN)
    assert conn.updates


def test_invalid_values_are_refused(monkeypatch):
    for body in ({"pii_mode": "blok"}, {"sensitivity": "secret"}):
        with pytest.raises(HTTPException) as exc:
            _patch(monkeypatch, body, ADMIN)
        assert exc.value.status_code == 400


def test_a_key_is_judged_by_its_own_scopes(monkeypatch):
    key = {"id": str(uuid.uuid4()), "username": "svc", "role": "admin", "permissions": ["knowledge:write"]}
    with pytest.raises(HTTPException) as exc:
        _patch(monkeypatch, {"sensitivity": "internal"}, key)
    assert exc.value.status_code == 403
