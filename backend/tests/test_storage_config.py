import importlib


def _fresh():
    import app.api.storage as s
    return importlib.reload(s)


def test_native_aws_when_endpoint_empty(monkeypatch):
    monkeypatch.delenv("S3_ENDPOINT", raising=False)
    monkeypatch.setenv("S3_REGION", "ap-northeast-2")
    cfg = _fresh()._s3_config()
    assert "endpoint_url" not in cfg          # native AWS S3
    assert cfg["region_name"] == "ap-northeast-2"
    assert "aws_access_key_id" not in cfg     # IAM role / default chain


def test_seaweedfs_when_endpoint_set(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT", "seaweedfs-s3:8333")
    monkeypatch.setenv("S3_ACCESS_KEY", "k")
    monkeypatch.setenv("S3_SECRET_KEY", "s")
    cfg = _fresh()._s3_config()
    assert cfg["endpoint_url"] == "http://seaweedfs-s3:8333"
    assert cfg["aws_access_key_id"] == "k"
    assert cfg["aws_secret_access_key"] == "s"


def test_endpoint_keeps_explicit_scheme(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT", "https://my-minio.example.com")
    cfg = _fresh()._s3_config()
    assert cfg["endpoint_url"] == "https://my-minio.example.com"
