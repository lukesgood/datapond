"""The browser session rides in an HttpOnly cookie the backend sets, not in localStorage.

Until 2026-10 the console kept the JWT in `localStorage` (and copied it to a cookie
JavaScript could read) and attached it as a Bearer header itself. Any script that
ran on the page could read the session. Now `/auth/login` (and the passkey and SSO
sign-ins) set `datapond_token` as an HttpOnly, SameSite=Lax cookie, the browser
sends it by itself, and the API reads it when no Authorization header is present.
API clients and service-account keys keep the header; the login body still carries
the token for scripts.

A cookie is sent by the browser on a cross-site request too, so a cookie-borne
identity on a state-changing method is accepted only when the request's Origin (or
Referer) is this host. A Bearer header is never subject to that check.
"""
import asyncio

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app.api import auth

USER_ID = "00000000-0000-0000-0000-000000000001"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _req(method="GET", headers=None, cookies=None, scheme="https"):
    hdrs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    hdrs.append((b"host", b"datapond.example"))
    if cookies:
        hdrs.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    scope = {"type": "http", "method": method, "path": "/api/x", "headers": hdrs,
             "scheme": scheme, "query_string": b"", "server": ("datapond.example", 443),
             "client": ("10.0.0.1", 1234)}
    return Request(scope)


def _token():
    return auth._create_token(USER_ID, "alice", "admin")


# ── setting and clearing ──────────────────────────────────────────────────────

class _Conn:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, *a, **k):
        return self.row

    async def execute(self, *a, **k):
        return "UPDATE 1"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Pool:
    def __init__(self, row):
        self.row = row

    def acquire(self, *a, **k):
        return _Conn(self.row)


@pytest.fixture
def alice(monkeypatch):
    row = {"id": USER_ID, "username": "alice", "password_hash": "x", "role": "admin",
           "display_name": "Alice", "email": "alice@example.com", "auth_method": "local",
           "is_active": True, "require_password_change": False}

    async def _pool():
        return _Pool(row)

    async def _nothing(*a, **k):
        return None
    monkeypatch.setattr(auth, "_get_pool", _pool)
    monkeypatch.setattr(auth, "_ensure_admin_exists", _nothing)
    monkeypatch.setattr(auth, "record_auth_event", _nothing)
    monkeypatch.setattr(auth, "_verify_password", lambda password, hashed: password == "secret")
    monkeypatch.setattr(auth, "_login_throttle", None)


def test_login_sets_the_session_as_an_httponly_cookie_and_still_returns_the_token(alice):
    resp = Response()
    body = _run(auth.login(auth.LoginRequest(username="alice", password="secret"),
                           _req(headers={"x-forwarded-proto": "https"}, scheme="http"), resp))
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith(f"datapond_token={body.access_token};")
    low = cookie.lower()
    assert "httponly" in low
    assert "samesite=lax" in low
    assert "path=/" in low
    assert f"max-age={auth.TOKEN_EXPIRE_HOURS * 3600}" in low
    assert "secure" in low, "the deployment is reached over https (X-Forwarded-Proto)"


def test_the_cookie_is_not_marked_secure_over_plain_http(alice):
    """A development server on http://localhost would never see a Secure cookie back."""
    resp = Response()
    _run(auth.login(auth.LoginRequest(username="alice", password="secret"), _req(scheme="http"), resp))
    assert "secure" not in resp.headers["set-cookie"].lower()


def test_logout_clears_the_cookie():
    resp = Response()
    _run(auth.logout(_req(), resp))
    cookie = resp.headers["set-cookie"].lower()
    assert cookie.startswith('datapond_token=""') or cookie.startswith("datapond_token=;")
    assert "max-age=0" in cookie
    assert "path=/" in cookie


# ── reading ───────────────────────────────────────────────────────────────────

def test_a_cookie_is_read_on_a_safe_method_without_an_origin():
    creds = auth.session_cookie_credentials(_req(cookies={"datapond_token": "tok"}))
    assert creds is not None and creds.credentials == "tok"


def test_no_cookie_is_no_credentials():
    assert auth.session_cookie_credentials(_req()) is None


def test_a_service_account_key_in_the_cookie_is_ignored():
    """Keys go in the header; a cookie carries only a session."""
    assert auth.session_cookie_credentials(_req(cookies={"datapond_token": "dp_sk_abc"})) is None


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_state_changing_request_needs_a_same_origin_origin(method):
    cookie = {"datapond_token": "tok"}
    same = auth.session_cookie_credentials(
        _req(method, headers={"origin": "https://datapond.example"}, cookies=cookie))
    assert same is not None
    other = auth.session_cookie_credentials(
        _req(method, headers={"origin": "https://evil.example"}, cookies=cookie))
    assert other is None
    none = auth.session_cookie_credentials(_req(method, cookies=cookie))
    assert none is None, "a browser always sends Origin on these methods; its absence is not a browser"


def test_a_referer_stands_in_for_a_missing_origin():
    creds = auth.session_cookie_credentials(
        _req("POST", headers={"referer": "https://datapond.example/settings"},
             cookies={"datapond_token": "tok"}))
    assert creds is not None
    foreign = auth.session_cookie_credentials(
        _req("POST", headers={"referer": "https://evil.example/"}, cookies={"datapond_token": "tok"}))
    assert foreign is None


def test_get_current_user_falls_back_to_the_cookie(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_DB_RECHECK", False)
    user = _run(auth.get_current_user(None, _req(cookies={"datapond_token": _token()})))
    assert user and user["id"] == USER_ID
    assert _run(auth.get_current_user(None, _req())) is None


def test_the_header_wins_over_the_cookie(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_DB_RECHECK", False)
    from fastapi.security import HTTPAuthorizationCredentials
    header = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth._create_token(
        "00000000-0000-0000-0000-000000000002", "bob", "viewer"))
    user = _run(auth.get_current_user(header, _req(cookies={"datapond_token": _token()})))
    assert user["username"] == "bob"


def test_the_middleware_authenticates_a_cookie_only_request(monkeypatch):
    import main
    monkeypatch.setattr(auth, "AUTH_DB_RECHECK", False)
    seen = {}

    async def call_next(request):
        seen["user"] = request.state.user
        return Response("ok")
    mw = main.AuthMiddleware(app=None)
    resp = _run(mw.dispatch(_req(cookies={"datapond_token": _token()}), call_next))
    assert resp.status_code == 200 and seen["user"]["id"] == USER_ID


def test_the_middleware_refuses_a_cross_site_post_on_the_cookie(monkeypatch):
    import main
    monkeypatch.setattr(auth, "AUTH_DB_RECHECK", False)

    async def call_next(request):
        raise AssertionError("the route must not run")
    mw = main.AuthMiddleware(app=None)
    resp = _run(mw.dispatch(_req("POST", headers={"origin": "https://evil.example"},
                                 cookies={"datapond_token": _token()}), call_next))
    assert resp.status_code == 401
