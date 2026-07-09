import importlib
import os
import ssl

# connectors.py instantiates a module-level CredentialVault() at import time,
# which requires ENCRYPTION_KEY. Set a throwaway-but-valid Fernet key so the
# module (and our reload in _fresh) imports cleanly in CI where it's unset.
# (urlsafe-b64 of 32 bytes "0123456789abcdef0123456789abcdef".)
os.environ.setdefault("ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")


def _fresh():
    import app.api.connectors as c
    return importlib.reload(c)


def test_ssl_require_encrypts_without_verify(monkeypatch):
    # sslmode=require (Aurora/RDS): TLS on, but do NOT verify the server cert — asyncpg
    # ssl=True would verify and fail on the RDS CA. Expect an explicit CERT_NONE context.
    monkeypatch.setenv("POSTGRES_HOST", "db.cluster-x.ap-northeast-2.rds.amazonaws.com")
    monkeypatch.setenv("POSTGRES_SSLMODE", "require")
    kw = _fresh()._pool_kwargs()
    assert isinstance(kw["ssl"], ssl.SSLContext)
    assert kw["ssl"].verify_mode == ssl.CERT_NONE
    assert kw["ssl"].check_hostname is False
    assert kw["host"].endswith("rds.amazonaws.com")
    assert kw["port"] == 5432


def test_ssl_verify_full_verifies(monkeypatch):
    # verify-ca/verify-full: full verification (ssl=True → CERT_REQUIRED). Needs the CA
    # bundle in the trust store; kept distinct from require.
    monkeypatch.setenv("POSTGRES_HOST", "db.example.com")
    monkeypatch.setenv("POSTGRES_SSLMODE", "verify-full")
    kw = _fresh()._pool_kwargs()
    assert kw["ssl"] is True


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
