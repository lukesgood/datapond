"""
PyIceberg ↔ Polaris REST 카탈로그 커넥션.

DataPond의 모든 compute 엔진(Trino/RisingWave)이 연결되는 동일한 Polaris REST
카탈로그에 PyIceberg로 직접 연결한다. 데이터 파일(Parquet)은 SeaweedFS S3에
PyIceberg가 직접 쓰고 단일 스냅샷으로 커밋한다.

자격/엔드포인트는 backend-deployment.yaml의 env로 주입된다 (Trino iceberg.properties와 동일 값).
"""
import os
import threading
from app.runtime import component_secret

_catalog = None
_lock = threading.Lock()


def get_catalog():
    """RestCatalog 싱글톤. 최초 호출 시 1회 생성."""
    global _catalog
    if _catalog is None:
        with _lock:
            if _catalog is None:
                from pyiceberg.catalog.rest import RestCatalog
                client_id = os.getenv("POLARIS_CLIENT_ID", "polaris-client")
                client_secret = component_secret("POLARIS_CLIENT_SECRET", "changeme-polaris-secret", component="polaris")
                _catalog = RestCatalog(
                    name="datapond",
                    **{
                        "uri":       os.getenv("POLARIS_URI", "http://polaris:8181/api/catalog"),
                        "warehouse": os.getenv("POLARIS_WAREHOUSE", "iceberg"),
                        "credential": f"{client_id}:{client_secret}",
                        "scope":      "PRINCIPAL_ROLE:ALL",
                        # SeaweedFS S3 — Polaris가 vended-credentials 미지원이므로 FileIO에 직접 주입
                        "s3.endpoint":          _s3_endpoint(),
                        "s3.access-key-id":     os.getenv("S3_ACCESS_KEY", "datapond"),
                        "s3.secret-access-key": component_secret("S3_SECRET_KEY", "datapond_dev", component="s3"),
                        "s3.path-style-access": "true",
                        "s3.region":            os.getenv("S3_REGION", "us-east-1"),
                    },
                )
    return _catalog


def _s3_endpoint() -> str:
    """S3_ENDPOINT는 'host:port' 형태로 주입되므로 scheme을 보정한다."""
    ep = os.getenv("S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT", "seaweedfs-s3:8333")
    if not ep.startswith("http"):
        ep = f"http://{ep}"
    return ep


def reset_catalog():
    """테스트/설정 변경 시 싱글톤 무효화."""
    global _catalog
    with _lock:
        _catalog = None
