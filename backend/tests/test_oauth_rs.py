"""OAuth resource-server mode: DataPond accepts access tokens from the customer's IdP.

Design: docs/superpowers/specs/2026-09-28-oauth-resource-server-design.md. The three
decisions the tests pin: community core, existing principals only (no JIT), and a
token without DataPond scopes is refused with insufficient_scope.
"""
import asyncio
import base64
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

from app import oauth_rs

ISSUER = "https://idp.example.com/oauth2/default"
BASE = "https://dp.example.com"
USER_ID = "11111111-1111-1111-1111-111111111111"
SVC_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(scope="module")
def keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    pub = key.public_key().public_numbers()

    def b64u(i, n):
        return base64.urlsafe_b64encode(i.to_bytes(n, "big")).rstrip(b"=").decode()
    jwks = {"keys": [{"kty": "RSA", "use": "sig", "kid": "k1", "alg": "RS256",
                      "n": b64u(pub.n, 256), "e": b64u(pub.e, 3)}]}
    return pem, jwks


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setenv("OAUTH_RS_ENABLED", "true")
    monkeypatch.setenv("OAUTH_RS_ISSUER", ISSUER)
    monkeypatch.setenv("APP_BASE_URL", BASE)
    monkeypatch.delenv("OAUTH_RS_AUDIENCES", raising=False)
    monkeypatch.delenv("OAUTH_RS_CLIENT_IDS", raising=False)
    monkeypatch.delenv("OAUTH_RS_SUBJECT_CLAIM", raising=False)
    monkeypatch.delenv("OAUTH_RS_SCOPE_PREFIX", raising=False)
    return oauth_rs.config()


def _token(pem, **claims):
    now = int(time.time())
    body = {"iss": ISSUER, "sub": "user-sub", "aud": f"{BASE}/api/mcp",
            "iat": now, "exp": now + 300,
            "scp": ["datapond:knowledge:read", "datapond:ai:generate"]}
    body.update(claims)
    body = {k: v for k, v in body.items() if v is not None}
    return jose_jwt.encode(body, pem, algorithm="RS256", headers={"kid": "k1"})


# ── configuration ─────────────────────────────────────────────────────────────

def test_off_unless_enabled_with_an_issuer(monkeypatch):
    monkeypatch.delenv("OAUTH_RS_ENABLED", raising=False)
    assert not oauth_rs.enabled()
    monkeypatch.setenv("OAUTH_RS_ENABLED", "true")
    monkeypatch.delenv("OAUTH_RS_ISSUER", raising=False)
    assert not oauth_rs.enabled()


def test_the_default_audiences_are_this_deployment_and_its_mcp_endpoint(cfg):
    assert set(cfg.audiences) == {BASE, f"{BASE}/api/mcp"}


# ── which tokens are external ─────────────────────────────────────────────────

def test_an_rs256_token_is_external_and_dataponds_own_hs256_is_not(keys):
    pem, _ = keys
    assert oauth_rs.looks_external(_token(pem))
    own = jose_jwt.encode({"sub": USER_ID}, "secret", algorithm="HS256")
    assert not oauth_rs.looks_external(own)
    assert not oauth_rs.looks_external("dp_sk_abc")
    assert not oauth_rs.looks_external("not.a.jwt")


# ── validation ────────────────────────────────────────────────────────────────

def test_a_valid_token_verifies(keys, cfg):
    pem, jwks = keys
    claims = oauth_rs.verify(_token(pem), jwks, cfg)
    assert claims["sub"] == "user-sub"


@pytest.mark.parametrize("over", [
    {"iss": "https://evil.example.com"},
    {"aud": "https://someone-else.example.com"},
    {"exp": int(time.time()) - 3600},
    {"token_use": "id"},
])
def test_a_token_not_for_us_is_refused(keys, cfg, over):
    pem, jwks = keys
    with pytest.raises(oauth_rs.InvalidToken):
        oauth_rs.verify(_token(pem, **over), jwks, cfg)


def test_a_token_signed_by_another_key_is_refused(keys, cfg):
    _, jwks = keys
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    with pytest.raises(oauth_rs.InvalidToken):
        oauth_rs.verify(_token(other), jwks, cfg)


def test_hs256_can_never_verify_as_external(keys, cfg):
    _, jwks = keys
    forged = jose_jwt.encode({"iss": ISSUER, "sub": "x", "aud": BASE,
                              "exp": int(time.time()) + 60}, "k", algorithm="HS256",
                             headers={"kid": "k1"})
    with pytest.raises(oauth_rs.InvalidToken):
        oauth_rs.verify(forged, jwks, cfg)


def test_a_token_without_aud_passes_only_for_a_configured_client(keys, cfg, monkeypatch):
    pem, jwks = keys
    tok = _token(pem, aud=None, client_id="agent-client")
    with pytest.raises(oauth_rs.InvalidToken):
        oauth_rs.verify(tok, jwks, cfg)
    monkeypatch.setenv("OAUTH_RS_CLIENT_IDS", "agent-client")
    assert oauth_rs.verify(tok, jwks, oauth_rs.config())["client_id"] == "agent-client"


# ── scopes ────────────────────────────────────────────────────────────────────

def test_scopes_come_from_scp_or_scope():
    assert oauth_rs.token_scopes({"scp": ["a", "b"]}) == {"a", "b"}
    assert oauth_rs.token_scopes({"scp": "a b"}) == {"a", "b"}
    assert oauth_rs.token_scopes({"scope": "openid a"}) == {"openid", "a"}
    assert oauth_rs.token_scopes({}) == set()


def test_only_prefixed_scopes_grant_and_never_beyond_the_role():
    granted = oauth_rs.granted_permissions(
        {"openid", "datapond:knowledge:read", "datapond:settings:write"},
        role="ai_engineer", service=False, prefix="datapond:")
    assert "knowledge:read" in granted
    assert "settings:write" not in granted          # not in the role


def test_a_service_account_never_gets_what_keys_never_get():
    granted = oauth_rs.granted_permissions(
        {"datapond:user:manage", "datapond:knowledge:read"},
        role="admin", service=True, prefix="datapond:")
    assert "user:manage" not in granted and "knowledge:read" in granted


# ── resolving to a principal ──────────────────────────────────────────────────

class _Conn:
    def __init__(self, by_subject=None, by_client=None):
        self.by_subject, self.by_client, self.queries = by_subject, by_client, []

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, args))
        if "auth_method = 'service'" in sql:
            return self.by_client
        return self.by_subject

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self, *a, **kw):
        return self.conn


def _install(monkeypatch, keys, conn):
    _, jwks = keys

    async def _jwks(cfg, force=False):
        return jwks

    async def _pool():
        return _Pool(conn)
    monkeypatch.setattr(oauth_rs, "fetch_jwks", _jwks)
    monkeypatch.setattr(oauth_rs, "_get_pool", _pool)


PERSON = {"id": USER_ID, "username": "ada", "role": "ai_engineer", "is_active": True,
          "pii_mode": None, "auth_method": "oidc"}
SERVICE = {"id": SVC_ID, "username": "svc-agent", "role": "ai_engineer", "is_active": True,
           "pii_mode": None, "auth_method": "service"}


def test_a_linked_person_resolves_with_role_narrowed_by_scopes(keys, cfg, monkeypatch):
    pem, _ = keys
    _install(monkeypatch, keys, _Conn(by_subject=PERSON))
    user = asyncio.run(oauth_rs.resolve(_token(pem)))
    assert user["id"] == USER_ID and user["oauth"] is True
    assert user["auth_method"] == "oidc"
    assert set(user["permissions"]) == {"knowledge:read", "ai:generate"}


def test_an_unknown_subject_is_not_created(keys, cfg, monkeypatch):
    pem, _ = keys
    conn = _Conn()
    _install(monkeypatch, keys, conn)
    assert asyncio.run(oauth_rs.resolve(_token(pem))) is None
    assert not any("INSERT" in sql for sql, _ in conn.queries)


def test_a_client_credentials_token_resolves_to_its_linked_service_account(keys, cfg, monkeypatch):
    pem, _ = keys
    _install(monkeypatch, keys, _Conn(by_client=SERVICE))
    user = asyncio.run(oauth_rs.resolve(_token(pem, sub="agent-client", client_id="agent-client")))
    assert user["id"] == SVC_ID and user["auth_method"] == "service"


def test_a_token_without_datapond_scopes_is_insufficient_scope(keys, cfg, monkeypatch):
    pem, _ = keys
    _install(monkeypatch, keys, _Conn(by_subject=PERSON))
    with pytest.raises(oauth_rs.InsufficientScope):
        asyncio.run(oauth_rs.resolve(_token(pem, scp=["openid", "profile"])))


def test_an_invalid_token_resolves_to_nothing(keys, cfg, monkeypatch):
    pem, _ = keys
    _install(monkeypatch, keys, _Conn(by_subject=PERSON))
    assert asyncio.run(oauth_rs.resolve(_token(pem, iss="https://evil"))) is None


def test_the_subject_claim_is_configurable_for_entra(keys, cfg, monkeypatch):
    pem, _ = keys
    conn = _Conn(by_subject=PERSON)
    _install(monkeypatch, keys, conn)
    monkeypatch.setenv("OAUTH_RS_SUBJECT_CLAIM", "oid")
    asyncio.run(oauth_rs.resolve(_token(pem, oid="entra-oid")))
    assert "entra-oid" in conn.queries[0][1]


# ── through the app ───────────────────────────────────────────────────────────

def _client(monkeypatch, resolved=None, raises=None):
    import main

    async def _resolve(token):
        if raises:
            raise raises
        return resolved
    monkeypatch.setattr(oauth_rs, "resolve", _resolve)
    return TestClient(main.app)


def test_a_401_tells_an_oauth_client_where_the_metadata_is(keys, cfg, monkeypatch):
    client = _client(monkeypatch, resolved=None)
    r = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Authorization": "Bearer " + _token(keys[0])})
    assert r.status_code == 401
    challenge = r.headers["WWW-Authenticate"]
    assert f'resource_metadata="{BASE}/.well-known/oauth-protected-resource/api/mcp"' in challenge
    assert "datapond:knowledge:read" in challenge


def test_insufficient_scope_is_a_403_with_the_challenge(keys, cfg, monkeypatch):
    client = _client(monkeypatch, raises=oauth_rs.InsufficientScope())
    r = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Authorization": "Bearer " + _token(keys[0])})
    assert r.status_code == 403
    assert 'error="insufficient_scope"' in r.headers["WWW-Authenticate"]


def test_a_permission_refusal_names_the_missing_scope(keys, cfg, monkeypatch):
    user = {**PERSON, "oauth": True, "permissions": ["knowledge:read"]}
    client = _client(monkeypatch, resolved=user)
    r = client.post("/api/ai/search", json={"collection": "c", "query": "q"},
                    headers={"Authorization": "Bearer " + _token(keys[0])})
    assert r.status_code == 403
    challenge = r.headers["WWW-Authenticate"]
    assert 'error="insufficient_scope"' in challenge and "datapond:ai:generate" in challenge


def test_the_protected_resource_metadata(cfg, monkeypatch):
    import main
    client = TestClient(main.app)
    root = client.get("/.well-known/oauth-protected-resource").json()
    mcp = client.get("/.well-known/oauth-protected-resource/api/mcp").json()
    assert root["resource"] == BASE and mcp["resource"] == f"{BASE}/api/mcp"
    assert mcp["authorization_servers"] == [ISSUER]
    assert "datapond:knowledge:read" in mcp["scopes_supported"]
    assert not any("offline_access" in s for s in mcp["scopes_supported"])
    assert mcp["bearer_methods_supported"] == ["header"]


def test_no_metadata_when_the_mode_is_off(monkeypatch):
    import main
    monkeypatch.delenv("OAUTH_RS_ENABLED", raising=False)
    assert TestClient(main.app).get("/.well-known/oauth-protected-resource").status_code == 404


def test_a_plain_bearer_challenge_when_the_mode_is_off(monkeypatch):
    import main
    monkeypatch.delenv("OAUTH_RS_ENABLED", raising=False)
    r = TestClient(main.app).post("/api/mcp", json={})
    assert r.status_code == 401 and r.headers["WWW-Authenticate"] == "Bearer"


# ── linking ───────────────────────────────────────────────────────────────────

def test_an_admin_links_a_client_id_to_a_service_account(cfg, monkeypatch):
    from app.api import service_account_routes as sar
    executed = []

    class _C:
        async def execute(self, sql, *args):
            executed.append((sql, args))
            return "UPDATE 1"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def _pool():
        return _Pool(_C())

    async def _event(*a, **kw):
        return None
    monkeypatch.setattr(sar, "_get_pool", _pool)
    monkeypatch.setattr(sar, "record_auth_event", _event)
    out = asyncio.run(sar.link_oauth_client(SVC_ID, sar.OAuthClientLink(client_id="agent-client"),
                                            admin={"id": USER_ID, "role": "admin"}))
    assert out["client_id"] == "agent-client"
    sql, args = executed[0]
    assert "external_id" in sql and "auth_method = 'service'" in sql
    assert args[1:] == ("agent-client", ISSUER)


def test_an_admin_can_set_a_persons_external_id(monkeypatch):
    from app.api import auth

    class _C:
        def __init__(self):
            self.executed = []

        async def fetchrow(self, *a):
            return None

        async def execute(self, sql, *args):
            self.executed.append((sql, args))
            return "UPDATE 1"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False
    conn = _C()

    async def _pool():
        return _Pool(conn)
    monkeypatch.setattr(auth, "_get_pool", _pool)
    asyncio.run(auth.update_user(USER_ID, {"external_id": "entra-oid"}, {"id": "a", "role": "admin"}))
    assert "external_id = $1" in conn.executed[0][0]
