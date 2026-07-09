"""_iceberg_sink_s3_props: static keys when injected (MinIO), omitted on AWS (credential chain)."""
import importlib


def _fresh(monkeypatch, env: dict):
    for k in ("S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_ENDPOINT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import app.api.streaming as s
    return importlib.reload(s)


def test_static_creds_when_injected(monkeypatch):
    s = _fresh(monkeypatch, {"S3_ACCESS_KEY": "ak", "S3_SECRET_KEY": "sk",
                             "S3_ENDPOINT": "seaweedfs-s3:8333"})
    p = s._iceberg_sink_s3_props()
    assert p["s3.access.key"] == "ak"
    assert p["s3.secret.key"] == "sk"
    assert p["s3.endpoint"] == "http://seaweedfs-s3:8333"


def test_credential_chain_when_unset(monkeypatch):
    # AWS: empty endpoint, no keys → omit all static-cred/endpoint keys (empty dict)
    s = _fresh(monkeypatch, {"S3_ENDPOINT": ""})
    p = s._iceberg_sink_s3_props()
    assert p == {}
    for k in ("s3.access.key", "s3.secret.key", "s3.endpoint"):
        assert k not in p


def test_partial_creds_omitted(monkeypatch):
    # only access key set → both omitted (no half-credential), endpoint still allowed
    s = _fresh(monkeypatch, {"S3_ACCESS_KEY": "ak", "S3_ENDPOINT": "minio:9000"})
    p = s._iceberg_sink_s3_props()
    assert "s3.access.key" not in p
    assert "s3.secret.key" not in p
    assert p["s3.endpoint"] == "http://minio:9000"


def test_no_bogus_literal_fallback(monkeypatch):
    # nothing set → NEVER the old "datapond"/"datapond_dev"/seaweedfs literals
    s = _fresh(monkeypatch, {})
    p = s._iceberg_sink_s3_props()
    assert "datapond" not in str(p)
    assert "seaweedfs" not in str(p)
