"""Purpose presets for a new agent, and the per-agent PII mode.

A preset fills in the narrowest role, key scopes and PII guardrail for what an agent
is for, and issues its first key. The PII mode is the caller's own guardrail
(`users.pii_mode`), now settable from the console — and, for the first time, applied
to requests an agent makes with its API key.
"""
import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.agent_presets import PII_MODES, PRESETS, get_preset, valid_pii_mode
from app.api import auth
from app.api import service_account_routes as sar
from app.permissions import ASSIGNABLE_ROLES, permissions_for
from app.service_accounts import NEVER_FOR_SERVICE_ACCOUNTS, effective_permissions, hash_key

ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "role": "admin"}
NEW_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


# ── the presets themselves ────────────────────────────────────────────────────

@pytest.mark.parametrize("p", PRESETS, ids=lambda p: p.id)
def test_a_preset_key_holds_exactly_its_scopes(p):
    """Every scope must be one the role holds. A scope outside the role would be
    dropped silently by the intersection, so the agent would get less than the card
    in the console says — the preset would describe something it does not do."""
    assert p.role in ASSIGNABLE_ROLES and p.role != "admin"
    assert set(p.scopes) <= permissions_for(p.role)
    assert not set(p.scopes) & NEVER_FOR_SERVICE_ACCOUNTS
    assert effective_permissions(p.role, list(p.scopes)) == set(p.scopes)
    assert valid_pii_mode(p.pii_mode)


@pytest.mark.parametrize("p", PRESETS, ids=lambda p: p.id)
def test_a_preset_key_is_narrower_than_its_role(p):
    """The point of a preset: a key with no scopes gets the whole role."""
    assert set(p.scopes) < permissions_for(p.role)


def test_preset_ids_are_unique_and_resolvable():
    ids = [p.id for p in PRESETS]
    assert len(ids) == len(set(ids))
    assert all(get_preset(i) is not None for i in ids) and get_preset("nope") is None


def test_pii_modes_match_the_column_check():
    assert PII_MODES == ("off", "mask", "block")
    assert valid_pii_mode(None) and not valid_pii_mode("blok") and not valid_pii_mode("")


# ── creating an agent from a preset ───────────────────────────────────────────

class _Tx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.tx_open = True
        return self

    async def __aexit__(self, *a):
        self.conn.tx_open = False
        return False


class _CreateConn:
    def __init__(self):
        self.inserts, self.keys, self.tx_open = [], [], False

    def transaction(self):
        return _Tx(self)

    async def fetchrow(self, sql, *args):
        assert self.tx_open, "the account is written inside the transaction"
        self.inserts.append((sql, args))
        return {"id": NEW_ID}

    async def fetchval(self, sql, *args):
        return datetime(2027, 2, 15, tzinfo=timezone.utc)

    async def execute(self, sql, *args):
        assert self.tx_open, "the key is written in the same transaction as the account"
        self.keys.append(args)
        return "INSERT 0 1"


class _Ctx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *a):
        return False


def _install(monkeypatch):
    conn = _CreateConn()

    class _Pool:
        def acquire(self):
            return _Ctx(conn)

    async def _pool():
        return _Pool()

    async def _event(*a, **k):
        return None

    monkeypatch.setattr(sar, "_get_pool", _pool)
    monkeypatch.setattr(sar, "record_auth_event", _event)
    return conn


def _create(**kw):
    return asyncio.run(sar.create_service_account(sar.ServiceAccountCreate(**kw), admin=ADMIN))


def test_a_preset_sets_role_and_pii_mode_and_issues_the_first_key(monkeypatch):
    conn = _install(monkeypatch)
    out = _create(name="support bot", preset="knowledge_assistant")
    p = get_preset("knowledge_assistant")

    sql, args = conn.inserts[0]
    assert "pii_mode" in sql
    assert args[3] == p.role and args[4] == "mask"
    assert out["role"] == p.role and out["pii_mode"] == "mask"

    assert len(conn.keys) == 1
    account_id, name, prefix, digest, scopes, expires = conn.keys[0]
    assert account_id == str(NEW_ID) and scopes == list(p.scopes)
    assert expires is not None, "a preset key expires like any console-issued key"
    key = out["key"]
    assert key["key"].startswith("dp_sk_") and hash_key(key["key"]) == digest
    assert set(key["permissions"]) == set(p.scopes)


def test_the_first_key_lifetime_can_be_chosen_or_left_open(monkeypatch):
    conn = _install(monkeypatch)
    _create(name="a", preset="metrics_reader", key_expires_in_days=None)
    assert conn.keys[0][5] is None, "null issues a key that never expires"
    with pytest.raises(Exception):
        sar.ServiceAccountCreate(name="b", preset="metrics_reader", key_expires_in_days=0)


def test_without_a_preset_nothing_changes(monkeypatch):
    conn = _install(monkeypatch)
    out = _create(name="custom", role="viewer")
    assert conn.keys == [] and "key" not in out
    assert conn.inserts[0][1][3] == "viewer" and conn.inserts[0][1][4] is None


def test_an_explicit_pii_mode_overrides_the_presets(monkeypatch):
    conn = _install(monkeypatch)
    _create(name="b", preset="knowledge_assistant", pii_mode="block")
    assert conn.inserts[0][1][4] == "block"
    conn = _install(monkeypatch)
    _create(name="c", preset="knowledge_assistant", pii_mode=None)
    assert conn.inserts[0][1][4] is None, "an explicit null inherits"


@pytest.mark.parametrize("kw, needle", [
    ({"preset": "nope"}, "Unknown preset"),
    ({"preset": "knowledge_assistant", "role": "data_engineer"}, "uses role"),
    ({"pii_mode": "blok"}, "pii_mode"),
])
def test_bad_requests_are_refused_before_anything_is_written(kw, needle, monkeypatch):
    conn = _install(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        _create(name="x", **kw)
    assert exc.value.status_code == 400 and needle in exc.value.detail
    assert conn.inserts == [] and conn.keys == []


def test_the_preset_role_may_be_restated(monkeypatch):
    _install(monkeypatch)
    assert _create(name="x", preset="metrics_reader", role="business_analyst")["role"] == "business_analyst"


# ── the agent's PII mode reaches requests made with its key ──────────────────

def test_an_api_key_identity_carries_the_accounts_pii_mode(monkeypatch):
    key = "dp_sk_" + "a" * 43
    row = {"key_id": uuid.uuid4(), "key_hash": hash_key(key), "status": "active",
           "scopes": ["knowledge:read"], "expires_at": None, "id": NEW_ID,
           "username": "svc-bot", "role": "ai_engineer", "is_active": True,
           "pii_mode": "block"}
    seen = {}

    class _Conn:
        async def fetchrow(self, sql, *a):
            seen["sql"] = sql
            return row

        async def execute(self, *a):
            return "UPDATE 1"

    class _Pool:
        def acquire(self):
            return _Ctx(_Conn())

    async def _pool():
        return _Pool()

    monkeypatch.setattr(auth, "_get_pool", _pool)
    auth._KEY_CACHE.clear()
    try:
        out = asyncio.run(auth._resolve_api_key(key))
        assert "pii_mode" in seen["sql"]
        assert out["pii_mode"] == "block"

        auth._KEY_CACHE.clear()
        row["pii_mode"] = None
        assert "pii_mode" not in asyncio.run(auth._resolve_api_key(key))
    finally:
        auth._KEY_CACHE.clear()


# ── setting it ────────────────────────────────────────────────────────────────

class _PatchConn:
    def __init__(self):
        self.sql = []

    def transaction(self):
        return _Tx(self)

    async def fetchrow(self, sql, *a):
        return {"auth_method": "service"}

    async def fetchval(self, *a):
        return None

    async def execute(self, sql, *a):
        self.sql.append((sql, a))
        return "UPDATE 1"


def _patch(monkeypatch, body):
    conn = _PatchConn()
    forgot = []

    class _Pool:
        def acquire(self):
            return _Ctx(conn)

    async def _pool():
        return _Pool()

    monkeypatch.setattr(auth, "_get_pool", _pool)
    monkeypatch.setattr(auth, "forget_cached_keys_for", lambda uid: forgot.append(uid) or 0)
    asyncio.run(auth.update_user(str(NEW_ID), body, admin=ADMIN))
    return conn, forgot


@pytest.mark.parametrize("mode", ["mask", "block", "off", None])
def test_patch_sets_the_mode_and_drops_cached_key_identities(mode, monkeypatch):
    conn, forgot = _patch(monkeypatch, {"pii_mode": mode})
    sql, args = conn.sql[0]
    assert "pii_mode = $1" in sql and args[0] == mode
    assert forgot == [str(NEW_ID)], "this replica must not keep the old mode for 30 s"


def test_patch_refuses_an_unknown_mode(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        _patch(monkeypatch, {"pii_mode": "blok"})
    assert exc.value.status_code == 400
