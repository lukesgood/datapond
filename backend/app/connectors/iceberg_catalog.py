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
    """pyiceberg catalog 싱글톤. 백엔드는 ICEBERG_CATALOG_BACKEND로 선택
    (glue = AWS Glue Data Catalog; polaris = 자체 REST, 기본값). 최초 1회 생성."""
    global _catalog
    if _catalog is None:
        with _lock:
            if _catalog is None:
                backend = os.getenv("ICEBERG_CATALOG_BACKEND", "polaris").strip().lower()
                _catalog = _build_glue_catalog() if backend == "glue" else _build_polaris_catalog()
    return _catalog


def _build_glue_catalog():
    """AWS Glue Data Catalog (서버리스). Glue/S3 모두 기본 자격증명 체인
    (노드 instance profile / IRSA) 사용 — _s3_fileio_props가 AWS에서 정적키를 생략."""
    from pyiceberg.catalog.glue import GlueCatalog
    props = {
        "warehouse":  os.getenv("GLUE_WAREHOUSE", ""),
        "glue.region": os.getenv("S3_REGION", "us-east-1"),
        **_s3_fileio_props(),
    }
    return GlueCatalog(name="datapond", **props)


def _build_polaris_catalog():
    """자체 호스팅 Polaris REST 카탈로그 (온프렘/full 프로파일). 기존 동작 그대로."""
    from pyiceberg.catalog.rest import RestCatalog
    client_id = os.getenv("POLARIS_CLIENT_ID", "polaris-client")
    client_secret = component_secret("POLARIS_CLIENT_SECRET", "changeme-polaris-secret", component="polaris")
    return RestCatalog(
        name="datapond",
        **{
            "uri":       os.getenv("POLARIS_URI", "http://polaris:8181/api/catalog"),
            "warehouse": os.getenv("POLARIS_WAREHOUSE", "iceberg"),
            "credential": f"{client_id}:{client_secret}",
            "scope":      "PRINCIPAL_ROLE:ALL",
            # S3 FileIO: static keys on MinIO, credential-chain on AWS (see _s3_fileio_props)
            **_s3_fileio_props(),
        },
    )


def _s3_fileio_props() -> dict:
    """S3 FileIO kwargs for pyiceberg's RestCatalog.

    MinIO/onprem: static keys are injected as env → pass them + the endpoint.
    AWS/IRSA: no keys, empty endpoint → omit static-cred/endpoint keys so
    pyiceberg's S3FileIO uses the default AWS credential chain (instance profile
    on K3s, projected web-identity token under IRSA)."""
    props = {"s3.region": os.getenv("S3_REGION", "us-east-1")}
    ak = os.getenv("S3_ACCESS_KEY", "").strip()
    sk = os.getenv("S3_SECRET_KEY", "").strip()
    if ak and sk:
        props["s3.access-key-id"] = ak
        props["s3.secret-access-key"] = sk
        props["s3.path-style-access"] = "true"
    ep = _s3_endpoint()
    if ep:
        props["s3.endpoint"] = ep
    return props


def _s3_endpoint() -> str:
    """Return an http-scheme'd endpoint, or '' when none is configured (AWS native S3)."""
    ep = (os.getenv("S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT", "")).strip()
    if not ep:
        return ""
    return ep if ep.startswith("http") else f"http://{ep}"


def reset_catalog():
    """테스트/설정 변경 시 싱글톤 무효화."""
    global _catalog
    with _lock:
        _catalog = None
