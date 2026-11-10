"""governance._source_catalog_users maps catalog grants to Trino usernames for the Layer 2
catalogs section. A grant naming nobody who exists must close the catalog, not open it
(review finding 4)."""
import asyncio

import pytest

from app.api import governance
from app.rls.engine import UserContext


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetch(self, sql, *args):
        return self.rows


class _Pool:
    def __init__(self, rows):
        self.rows = rows

    def acquire(self):
        return _Conn(self.rows)


@pytest.fixture
def grants(monkeypatch):
    holder = {"rows": []}

    async def _pool():
        return _Pool(holder["rows"])
    import app.api.connectors as connectors
    monkeypatch.setattr(connectors, "get_db_pool", _pool)
    return holder


USERS = [UserContext(user_id="U1", username="alice", roles=["analyst"]),
         UserContext(user_id="U2", username="bob", roles=["viewer"])]


def test_user_and_role_grants_resolve_to_usernames(grants):
    grants["rows"] = [{"engine_catalog": "src_crm", "principal_kind": "user", "principal": "u1"},
                      {"engine_catalog": "src_crm", "principal_kind": "role", "principal": "viewer"}]
    assert asyncio.run(governance._source_catalog_users(USERS)) == {"src_crm": ["alice", "bob"]}


def test_a_catalog_without_grant_rows_is_open(grants):
    grants["rows"] = [{"engine_catalog": "src_open", "principal_kind": None, "principal": None}]
    assert asyncio.run(governance._source_catalog_users(USERS)) == {"src_open": []}


def test_a_catalog_whose_grants_name_no_current_user_is_closed(grants):
    grants["rows"] = [{"engine_catalog": "src_gone", "principal_kind": "user", "principal": "deleted-id"},
                      {"engine_catalog": "src_gone", "principal_kind": "role", "principal": "no_such_role"}]
    assert asyncio.run(governance._source_catalog_users(USERS)) == {"src_gone": None}
