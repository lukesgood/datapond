"""Who may use which data catalog: the rule itself (app/catalog_access.py).

A catalog nobody was granted stays open to everyone who passes today's checks. A
catalog with a grant is for the granted users and roles, plus signed-in admins — and
not for an API key or IdP token on an admin account, which its grants decide like
anyone else's. Grants that cannot be read hide every catalog from non-admins; a
database behind migration 0021 has no grants table, which means no grants.
"""
import asyncio

import pytest

from app import catalog_access as ca
from app import catalog_registry as reg
from app.catalog_registry import CatalogEntry

ALICE = {"id": "11111111-1111-1111-1111-111111111111", "username": "alice", "role": "viewer"}
BOB = {"id": "22222222-2222-2222-2222-222222222222", "username": "bob", "role": "business_analyst"}
ADMIN = {"id": "33333333-3333-3333-3333-333333333333", "username": "root", "role": "admin"}
ADMIN_KEY = {**ADMIN, "auth_method": "service"}
ADMIN_TOKEN = {**ADMIN, "oauth": True}
BOT = {"id": "44444444-4444-4444-4444-444444444444", "username": "bot", "role": "viewer",
       "auth_method": "service"}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def catalogs():
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="fin"),
        CatalogEntry(name="archive", kind="polaris", engine_catalog="archive", enabled=False),
    ])
    yield
    reg.reset()


def _access(user):
    return _run(ca.for_caller(user))


def test_a_catalog_nobody_was_granted_is_open_to_everyone():
    ca.set_grants({})
    a = _access(ALICE)
    assert [e.name for e in a.entries()] == ["iceberg", "finance"]
    assert a.hidden_sql_names() == set()


def test_a_granted_catalog_is_hidden_from_everyone_else():
    ca.set_grants({"finance": [("user", BOB["id"])]})
    a = _access(ALICE)
    assert [e.name for e in a.entries()] == ["iceberg"]
    assert not a.allows_sql_catalog("fin") and not a.allows_sql_catalog("FINANCE")
    assert a.allows_sql_catalog(None) and a.allows_sql_catalog("iceberg")


def test_a_direct_user_grant_opens_it():
    ca.set_grants({"finance": [("user", ALICE["id"].upper())]})
    assert _access(ALICE).allows_sql_catalog("fin")


def test_a_role_grant_opens_it_to_every_holder_of_the_role():
    ca.set_grants({"finance": [("role", "business_analyst")]})
    assert _access(BOB).allows_sql_catalog("fin")
    assert not _access(ALICE).allows_sql_catalog("fin")


def test_a_service_account_is_a_user_and_can_be_granted():
    ca.set_grants({"finance": [("user", BOT["id"])]})
    assert _access(BOT).allows_sql_catalog("fin")
    assert not _access(ALICE).allows_sql_catalog("fin")


def test_a_signed_in_admin_sees_every_catalog():
    ca.set_grants({"finance": [("user", BOB["id"])]})
    assert _access(ADMIN).allows_sql_catalog("fin")


@pytest.mark.parametrize("credential", [ADMIN_KEY, ADMIN_TOKEN])
def test_a_delegated_credential_on_an_admin_account_is_not_exempt(credential):
    ca.set_grants({"finance": [("user", BOB["id"])]})
    assert not _access(credential).allows_sql_catalog("fin")
    ca.set_grants({"finance": [("user", ADMIN["id"])]})
    assert _access(credential).allows_sql_catalog("fin")


def test_a_disabled_catalog_the_engine_still_knows_is_hidden_too():
    ca.set_grants({"archive": [("user", BOB["id"])]})
    assert "archive" in _access(ALICE).hidden_sql_names()


def test_a_hidden_catalog_resolves_as_unknown_and_is_not_named():
    ca.set_grants({"finance": [("user", BOB["id"])]})
    a = _access(ALICE)
    with pytest.raises(reg.UnknownCatalog) as hidden:
        a.resolve("finance")
    with pytest.raises(reg.UnknownCatalog) as unknown:
        a.resolve("nope")
    assert "finance" not in str(hidden.value).split("'")[2]
    assert str(unknown.value) == "Unknown catalog 'nope'. Known catalogs: iceberg."
    assert str(hidden.value) == "Unknown catalog 'finance'. Known catalogs: iceberg."


# ── reading the grants ───────────────────────────────────────────────────────

class _Conn:
    def __init__(self, result):
        self.result = result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetch(self, sql, *args):
        assert "FROM catalog_grants" in sql
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class _Pool:
    def __init__(self, result):
        self.result = result
        self.reads = 0

    def acquire(self, timeout=None):
        self.reads += 1
        return _Conn(self.result)


def _pool(monkeypatch, result):
    pool = _Pool(result)

    async def _get():
        return pool
    monkeypatch.setattr(ca, "_pool", _get)
    ca.reset()
    return pool


def test_grants_are_read_from_the_table_and_cached(monkeypatch):
    pool = _pool(monkeypatch, [{"catalog_name": "finance", "principal_kind": "role",
                                "principal": "business_analyst"}])
    assert _access(BOB).allows_sql_catalog("fin")
    assert not _access(ALICE).allows_sql_catalog("fin")
    assert pool.reads == 1


def test_a_grants_read_that_fails_hides_every_catalog(monkeypatch):
    _pool(monkeypatch, ConnectionError("database is gone"))
    a = _access(ALICE)
    assert a.entries() == []
    assert not a.allows_sql_catalog(None)
    with pytest.raises(reg.UnknownCatalog):
        a.resolve(None)
    # ... except from a signed-in admin, who needs no grant to be read.
    assert _access(ADMIN).allows_sql_catalog("fin")


def test_a_failed_read_is_not_cached(monkeypatch):
    pool = _pool(monkeypatch, ConnectionError("blip"))
    _access(ALICE)
    pool.result = []
    assert _access(ALICE).allows_sql_catalog("fin")


def test_a_database_before_migration_0021_is_open(monkeypatch):
    class UndefinedTableError(Exception):
        sqlstate = "42P01"
    _pool(monkeypatch, UndefinedTableError('relation "catalog_grants" does not exist'))
    a = _access(ALICE)
    assert [e.name for e in a.entries()] == ["iceberg", "finance"]


# ── statements ───────────────────────────────────────────────────────────────

def test_statements_name_their_catalogs_with_two_parts_meaning_the_default():
    cats = ca.referenced_catalogs(
        "WITH x AS (SELECT 1) SELECT * FROM sales.orders o JOIN fin.gl.entries e "
        "ON o.id = e.id JOIN x ON true", "trino")
    assert cats == {"iceberg", "fin"}


def test_a_statement_touching_a_hidden_catalog_is_caught():
    ca.set_grants({"finance": [("user", BOB["id"])]})
    a = _access(ALICE)
    assert ca.statement_uses_hidden(a, "SELECT * FROM fin.gl.entries", "trino")
    assert ca.statement_uses_hidden(a, "SELECT * FROM (SELECT * FROM FIN.gl.entries) t",
                                    "trino")
    assert not ca.statement_uses_hidden(a, "SELECT * FROM sales.orders", "trino")
    assert not ca.statement_uses_hidden(_access(BOB), "SELECT * FROM fin.gl.entries", "trino")


def test_an_unparseable_statement_is_refused_only_when_something_is_hidden():
    bad = "SELECT FROM WHERE (((("
    assert not ca.statement_uses_hidden(_access(ALICE), bad, "trino")
    ca.set_grants({"finance": [("user", BOB["id"])]})
    assert ca.statement_uses_hidden(_access(ALICE), bad, "trino")
