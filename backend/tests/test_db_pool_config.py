import importlib
import os

# connectors.py instantiates a module-level CredentialVault() at import time,
# which requires ENCRYPTION_KEY. Set a throwaway-but-valid Fernet key so the
# module (and our reload in _fresh) imports cleanly in CI where it's unset.
# (urlsafe-b64 of 32 bytes "0123456789abcdef0123456789abcdef".)
os.environ.setdefault("ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")


def _fresh():
    import app.api.connectors as c
    return importlib.reload(c)


def test_ssl_enabled_for_aurora(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "db.cluster-x.ap-northeast-2.rds.amazonaws.com")
    monkeypatch.setenv("POSTGRES_SSLMODE", "require")
    kw = _fresh()._pool_kwargs()
    assert kw["ssl"] is True
    assert kw["host"].endswith("rds.amazonaws.com")
    assert kw["port"] == 5432


def test_no_ssl_in_cluster(monkeypatch):
    monkeypatch.delenv("POSTGRES_SSLMODE", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    kw = _fresh()._pool_kwargs()
    assert "ssl" not in kw
    assert kw["host"] == "postgres"


def test_custom_port(monkeypatch):
    monkeypatch.delenv("POSTGRES_SSLMODE", raising=False)
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    kw = _fresh()._pool_kwargs()
    assert kw["port"] == 5433


def test_port_strips_k8s_service_link(monkeypatch):
    monkeypatch.setenv("POSTGRES_PORT", "tcp://10.0.0.5:5432")
    kw = _fresh()._pool_kwargs()
    assert kw["port"] == 5432
