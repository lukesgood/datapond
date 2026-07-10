import importlib, os


def _fresh(monkeypatch, env):
    for k in ("WEBAUTHN_RP_ID", "WEBAUTHN_ORIGIN", "WEBAUTHN_RP_NAME", "EXTERNAL_SCHEME", "APP_DOMAIN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import app.api.webauthn as w
    return importlib.reload(w)


def test_enabled_requires_https(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "datapond.example.com", "WEBAUTHN_ORIGIN": "https://datapond.example.com"})
    assert w.webauthn_enabled() is True


def test_disabled_on_http(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "datapond.example.com", "WEBAUTHN_ORIGIN": "http://datapond.example.com"})
    assert w.webauthn_enabled() is False


def test_localhost_allowed(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "localhost", "WEBAUTHN_ORIGIN": "http://localhost:3000"})
    assert w.webauthn_enabled() is True


def test_disabled_when_unconfigured(monkeypatch):
    w = _fresh(monkeypatch, {})
    assert w.webauthn_enabled() is False


def test_cfg_derives_origin_from_rp_id(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "d.example.com"})
    assert w._webauthn_cfg()["origin"] == "https://d.example.com"


def test_register_begin_returns_options_and_stores_challenge(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "localhost", "WEBAUTHN_ORIGIN": "http://localhost:3000"})
    import asyncio
    opts, nonce = asyncio.get_event_loop().run_until_complete(
        w._build_registration_options(user_id="00000000-0000-0000-0000-000000000001", username="admin", existing=[])
    )
    assert "challenge" in opts and "rp" in opts
    assert w._challenge_pop(nonce) is not None      # stored
    assert w._challenge_pop(nonce) is None           # single-use consumed


def test_sign_count_regression_rejected(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "localhost", "WEBAUTHN_ORIGIN": "http://localhost:3000"})
    assert w._sign_count_ok(stored=5, new=6) is True
    assert w._sign_count_ok(stored=5, new=5) is False   # no increase
    assert w._sign_count_ok(stored=5, new=4) is False   # regression
    assert w._sign_count_ok(stored=0, new=0) is True    # counter-less authenticator


class _FakeConn:
    def __init__(self, row):
        self._row = row

    async def fetchrow(self, *a, **k):
        return self._row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, row):
        self._row = row

    def acquire(self):
        return _FakeConn(self._row)


def _run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_authenticate_complete_rejects_inactive_user(monkeypatch):
    """Passkey login must honor is_active — a disabled user with a lingering credential
    is rejected with the same 'Unknown credential' 401 as an unknown credential (no oracle)."""
    from fastapi import HTTPException
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "localhost", "WEBAUTHN_ORIGIN": "http://localhost:3000"})
    # Valid, single-use challenge present so we get past the challenge gate.
    nonce = w._new_nonce()
    import base64
    w._challenge_store(nonce, base64.b64encode(b"x" * 32).decode())
    # Row exists (credential known) but the account is deactivated.
    inactive_row = {
        "cid": "c", "public_key": b"pk", "sign_count": 0,
        "uid": "00000000-0000-0000-0000-000000000001", "username": "ghost",
        "role": "user", "is_active": False,
    }
    monkeypatch.setattr(w, "_get_pool", _make_async(_FakePool(inactive_row)))
    req = w.AuthCompleteReq(nonce=nonce, credential={"id": "AAAA", "rawId": "AAAA"})
    try:
        _run(w.authenticate_complete(req))
        assert False, "expected HTTPException"
    except HTTPException as e:
        assert e.status_code == 401
        assert e.detail == "Unknown credential"   # uniform message, no active/inactive oracle


def test_authenticate_complete_malformed_credential(monkeypatch):
    """A credential dict missing rawId/id → 400 Malformed credential, not a 500."""
    from fastapi import HTTPException
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "localhost", "WEBAUTHN_ORIGIN": "http://localhost:3000"})
    nonce = w._new_nonce()
    import base64
    w._challenge_store(nonce, base64.b64encode(b"x" * 32).decode())
    req = w.AuthCompleteReq(nonce=nonce, credential={"nonsense": 1})
    try:
        _run(w.authenticate_complete(req))
        assert False, "expected HTTPException"
    except HTTPException as e:
        assert e.status_code == 400
        assert e.detail == "Malformed credential"


def _make_async(ret):
    async def _f(*a, **k):
        return ret
    return _f
