"""_s3_fileio_props: static creds when injected (MinIO/onprem), credential-chain when not (AWS/IRSA)."""
import importlib
import pytest


def _fresh(monkeypatch, env: dict):
    for k in ("S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_ENDPOINT", "S3_ENDPOINT_URL", "S3_REGION"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import app.connectors.iceberg_catalog as c
    return importlib.reload(c)


def test_static_creds_when_injected(monkeypatch):
    c = _fresh(monkeypatch, {"S3_ACCESS_KEY": "ak", "S3_SECRET_KEY": "sk",
                             "S3_ENDPOINT": "seaweedfs-s3:8333", "S3_REGION": "us-east-1"})
    p = c._s3_fileio_props()
    assert p["s3.access-key-id"] == "ak"
    assert p["s3.secret-access-key"] == "sk"
    assert p["s3.endpoint"] == "http://seaweedfs-s3:8333"   # scheme prefixed
    assert p["s3.path-style-access"] == "true"
    assert p["s3.region"] == "us-east-1"


def test_credential_chain_when_unset(monkeypatch):
    # AWS: empty endpoint, no keys → omit all static-cred/endpoint keys
    c = _fresh(monkeypatch, {"S3_ENDPOINT": "", "S3_REGION": "us-east-1"})
    p = c._s3_fileio_props()
    assert p == {"s3.region": "us-east-1"}
    for k in ("s3.access-key-id", "s3.secret-access-key", "s3.endpoint", "s3.path-style-access"):
        assert k not in p


def test_no_endpoint_no_http_fabrication(monkeypatch):
    # keys present but endpoint empty → no s3.endpoint key, no "http://" fabricated
    c = _fresh(monkeypatch, {"S3_ACCESS_KEY": "ak", "S3_SECRET_KEY": "sk", "S3_ENDPOINT": ""})
    p = c._s3_fileio_props()
    assert "s3.endpoint" not in p
    assert p["s3.access-key-id"] == "ak"


def test_region_default(monkeypatch):
    c = _fresh(monkeypatch, {})   # nothing set
    p = c._s3_fileio_props()
    assert p == {"s3.region": "us-east-1"}   # region defaults, nothing else
