# DataPond Enterprise — Commercial License (see ee/LICENSE). Not covered by the root Apache-2.0 grant.
"""Router-level tests: role mapping + JIT upsert conflict semantics (mocked pool)."""
from ee.sso.router import _map_role, _upsert_oidc_user


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


def test_map_role_admin_when_group_present():
    claims = {"groups": ["datapond-admins", "everyone"]}
    assert _map_role(claims, group_claim="groups",
                     admin_group="datapond-admins", default_role="viewer") == "admin"


def test_map_role_default_when_group_absent():
    claims = {"groups": ["everyone"]}
    assert _map_role(claims, group_claim="groups",
                     admin_group="datapond-admins", default_role="viewer") == "viewer"


def test_map_role_default_when_claim_missing_or_not_list():
    assert _map_role({}, group_claim="groups", admin_group="g", default_role="viewer") == "viewer"
    assert _map_role({"groups": "not-a-list"}, group_claim="groups",
                     admin_group="g", default_role="viewer") == "viewer"


def test_map_role_no_admin_group_configured():
    assert _map_role({"groups": ["anything"]}, group_claim="groups",
                     admin_group="", default_role="data_engineer") == "data_engineer"


class _FakeConn:
    def __init__(self, row_after):
        self.row_after = row_after
        self.executed = []
    async def execute(self, sql, *args):
        self.executed.append((sql, args))
    async def fetchrow(self, sql, *args):
        return self.row_after
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _FakePool:
    def __init__(self, conn): self._conn = conn
    def acquire(self): return self._conn


def test_upsert_returns_row_for_oidc_user(monkeypatch):
    from ee.sso import router as r
    row = {"id": "u1", "username": "alice", "role": "viewer",
           "auth_method": "oidc", "is_active": True}
    conn = _FakeConn(row)
    async def fake_pool(): return _FakePool(conn)
    monkeypatch.setattr(r, "_pool", fake_pool)
    got = _run(_upsert_oidc_user({"email": "a@x", "username": "alice",
                                   "display_name": "Alice", "role": "viewer",
                                   "external_id": "sub-1"}))
    assert got["username"] == "alice"
    assert "WHERE users.auth_method = 'oidc'" in conn.executed[0][0]


def test_upsert_conflict_with_local_account_returns_none(monkeypatch):
    """Upsert WHERE-clause skips a local row; SELECT comes back auth_method='local' → None."""
    from ee.sso import router as r
    row = {"id": "u1", "username": "admin", "role": "admin",
           "auth_method": "local", "is_active": True}
    async def fake_pool(): return _FakePool(_FakeConn(row))
    monkeypatch.setattr(r, "_pool", fake_pool)
    got = _run(_upsert_oidc_user({"email": "a@x", "username": "admin",
                                   "display_name": "A", "role": "viewer",
                                   "external_id": "sub-1"}))
    assert got is None
