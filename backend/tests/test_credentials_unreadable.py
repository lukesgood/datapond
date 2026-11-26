"""Stored credentials the encryption key cannot read (the 2026-11-10 rebuild): the API
says to enter them again (409) and the edit form can do that, instead of a 500."""
import asyncio
import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import connectors as C
from app.connectors.vault import CredentialVault, CredentialsUnreadable

CID = "11111111-1111-1111-1111-111111111111"
ADMIN = {"id": "u", "role": "admin"}


def _foreign_blob():
    return CredentialVault(Fernet.generate_key().decode()).encrypt_credentials({"host": "h", "password": "p"})


def test_a_foreign_key_raises_credentials_unreadable():
    with pytest.raises(CredentialsUnreadable) as e:
        CredentialVault(Fernet.generate_key().decode()).decrypt_credentials(_foreign_blob())
    assert isinstance(e.value, ValueError) and "enter the settings again" in str(e.value).lower()


class _Conn:
    def __init__(self, row):
        self.row, self.executed = row, []

    async def fetchrow(self, *a):
        return self.row

    async def execute(self, sql, *args):
        self.executed.append(args)


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


@pytest.fixture
def unreadable(monkeypatch):
    conn = _Conn({"name": "Shop", "connector_type": "rest_api", "description": None,
                  "config_encrypted": _foreign_blob()})

    async def pool():
        return _Pool(conn)

    async def allow(*a, **k):
        return None
    monkeypatch.setattr(C, "get_db_pool", pool)
    monkeypatch.setattr(C, "require_access", allow)
    return conn


def test_the_edit_form_opens_empty_with_the_reason(unreadable):
    out = asyncio.run(C.get_connection_config(CID, ADMIN))
    assert out["credentials_unreadable"] is True and out["config"] == {} and out["name"] == "Shop"


def test_saving_new_settings_replaces_the_unreadable_ones(unreadable, monkeypatch):
    async def no_check(cid):
        return None
    monkeypatch.setattr(C, "_check_connection", no_check)
    req = C.ConnectionUpdateRequest(config={"base_url": "https://api.test", "auth_value": "secret"})
    asyncio.run(C.update_connection(CID, req, ADMIN))
    stored = C.vault.decrypt_credentials(unreadable.executed[0][2])
    assert stored["base_url"] == "https://api.test" and stored["auth_value"] == "secret"


def test_keeping_an_unreadable_secret_is_refused_with_the_field(unreadable):
    req = C.ConnectionUpdateRequest(config={"base_url": "https://api.test", "auth_value": "••••••••"})
    with pytest.raises(HTTPException) as e:
        asyncio.run(C.update_connection(CID, req, ADMIN))
    assert e.value.status_code == 409 and "auth_value" in e.value.detail
    assert unreadable.executed == []


def test_test_with_masked_fields_says_to_reenter(unreadable):
    with pytest.raises(HTTPException) as e:
        asyncio.run(C._merge_stored_secrets({"auth_value": "••••••••"}, CID, ADMIN))
    assert e.value.status_code == 409


def test_anything_else_that_meets_it_answers_409_not_500():
    import main
    from fastapi import FastAPI
    app = FastAPI()
    app.exception_handlers.update(main.app.exception_handlers)

    @app.get("/x")
    async def x():
        raise CredentialsUnreadable("Decryption failed: InvalidToken")
    r = TestClient(app).get("/x")
    assert r.status_code == 409 and r.json()["code"] == "credentials_unreadable"
    assert "InvalidToken" not in r.text
