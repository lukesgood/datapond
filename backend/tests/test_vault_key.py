from cryptography.fernet import Fernet
from app.connectors.vault import _coerce_fernet_key, CredentialVault


def test_valid_fernet_key_passthrough():
    k = Fernet.generate_key()
    assert _coerce_fernet_key(k.decode()) == k


def test_arbitrary_string_derives_valid_key():
    kb = _coerce_fernet_key("any-random-helm-string-123")
    Fernet(kb)
    assert kb == _coerce_fernet_key("any-random-helm-string-123")


def test_roundtrip_with_derived_key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "some-random-string")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    v = CredentialVault()
    assert v.decrypt_credentials(v.encrypt_credentials({"a": "b"})) == {"a": "b"}


def test_prod_failclosed(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    import pytest
    with pytest.raises(Exception):
        CredentialVault()


def test_dev_fallback_ok(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    CredentialVault()
