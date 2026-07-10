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
