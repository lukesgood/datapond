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
