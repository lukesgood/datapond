"""PATCH /auth/me: a person renames themselves; an agent key cannot rename its account."""
import asyncio
import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.auth as auth

SESSION = {"id": "00000000-0000-0000-0000-000000000001", "username": "ada", "role": "viewer"}


class _Conn:
    def __init__(self):
        self.calls = []

    async def execute(self, q, *a):
        self.calls.append((q, a))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _pool(monkeypatch):
    conn = _Conn()
    pool = SimpleNamespace(acquire=lambda *a, **k: conn)

    async def get():
        return pool
    monkeypatch.setattr(auth, "_get_pool", get)
    return conn


def test_update_me_is_people_only():
    dep = inspect.signature(auth.update_me).parameters["user"].default
    assert dep.dependency is auth.require_human


def test_display_name_is_trimmed(monkeypatch):
    conn = _pool(monkeypatch)
    asyncio.run(auth.update_me({"display_name": "  Ada L  "}, SESSION))
    assert conn.calls[0][1][0] == "Ada L"


@pytest.mark.parametrize("name", ["", "   ", "x" * 101, None])
def test_blank_or_long_names_are_refused(monkeypatch, name):
    conn = _pool(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.update_me({"display_name": name}, SESSION))
    assert exc.value.status_code == 400
    assert conn.calls == []
