"""What GET /api/capabilities tells a caller who has not signed in.

The endpoint is in main.py's AUTH_EXEMPT because the login page has to know whether
to render the SSO button and the passkey prompt before anyone holds a token. That
exemption is written for two feature flags; these tests hold the response to it, so
the adapter names, the profile, and the deployment namespace do not travel to an
anonymous caller just because the endpoint they live on had to be reachable.

Exercised through the real app rather than by re-deriving main.py's expression in a
helper: a test that mirrors the code cannot notice the code changing.
"""
import pytest
from fastapi.testclient import TestClient


# The two flags the login page reads (frontend/app/login/page.tsx) — the whole
# reason the endpoint is unauthenticated.
PUBLIC_KEYS = {"sso", "webauthn"}

# A sample of what the full map carries. Each one describes how this deployment is
# assembled, which is a reconnaissance answer, not a login-page answer.
PRIVATE_KEYS = [
    "query_engine",
    "catalog_backend",
    "storage_provider",
    "vector_store",
    "model_gateway",
    "profile_id",
    "profile_topology",
    "deployment_namespace",
]


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


def test_an_anonymous_caller_gets_only_the_login_page_flags(client):
    r = client.get("/api/capabilities")
    assert r.status_code == 200
    assert set(r.json()) == PUBLIC_KEYS


@pytest.mark.parametrize("key", PRIVATE_KEYS)
def test_an_anonymous_caller_learns_nothing_about_the_deployment(client, key):
    assert key not in client.get("/api/capabilities").json()


def test_a_signed_in_caller_gets_the_full_map(client, monkeypatch):
    import app.api.auth as auth

    async def _accept(creds):
        return {"id": "u1", "username": "someone", "role": "admin"}

    monkeypatch.setattr(auth, "get_current_user", _accept)
    body = client.get("/api/capabilities", headers={"Authorization": "Bearer good"}).json()
    assert PUBLIC_KEYS <= set(body)
    for key in PRIVATE_KEYS:
        assert key in body


def test_a_rejected_token_degrades_rather_than_failing(client, monkeypatch):
    """The endpoint's contract is that it never fails.

    A caller whose token expired mid-session must still be able to render the login
    page it is about to be bounced to, so a token this deployment will not accept
    answers like no token at all — not 401.
    """
    import app.api.auth as auth

    async def _reject(creds):
        raise ValueError("expired")

    monkeypatch.setattr(auth, "get_current_user", _reject)
    r = client.get("/api/capabilities", headers={"Authorization": "Bearer stale"})
    assert r.status_code == 200
    assert set(r.json()) == PUBLIC_KEYS


def test_a_malformed_authorization_header_is_not_a_token(client):
    for header in ("", "Bearer", "Basic abc", "bearer lowercase-scheme", "Bearer "):
        r = client.get("/api/capabilities", headers={"Authorization": header})
        assert r.status_code == 200, header
        assert set(r.json()) == PUBLIC_KEYS, header
