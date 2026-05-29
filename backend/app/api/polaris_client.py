"""
Polaris REST Catalog client — single governance gate for all catalog operations.
Authenticates via OAuth2 client_credentials and caches token.
"""
import os
import time
import logging
from typing import List, Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)

POLARIS_URL = os.getenv("POLARIS_URL", "http://polaris:8181")
POLARIS_CLIENT_ID = os.getenv("POLARIS_CLIENT_ID", "polaris-client")
POLARIS_CLIENT_SECRET = os.getenv("POLARIS_CLIENT_SECRET", "changeme-polaris-secret")

_token_cache: Dict[str, Any] = {"token": None, "expires_at": 0}


def _get_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 30:
        return _token_cache["token"]

    resp = requests.post(
        f"{POLARIS_URL}/api/catalog/v1/oauth/tokens",
        data={
            "grant_type": "client_credentials",
            "client_id": POLARIS_CLIENT_ID,
            "client_secret": POLARIS_CLIENT_SECRET,
            "scope": "PRINCIPAL_ROLE:ALL",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=5,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return _token_cache["token"]


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_get_token()}"}


def list_catalogs() -> List[Dict[str, Any]]:
    """List all catalogs registered in Polaris (management API)."""
    resp = requests.get(
        f"{POLARIS_URL}/api/management/v1/catalogs",
        headers=_headers(), timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("catalogs", [])


def list_namespaces(catalog: str) -> List[str]:
    """List namespaces in a Polaris catalog (Iceberg REST spec)."""
    resp = requests.get(
        f"{POLARIS_URL}/api/catalog/v1/{catalog}/namespaces",
        headers=_headers(), timeout=10,
    )
    resp.raise_for_status()
    # Polaris returns {"namespaces": [["ns1"], ["ns2"]]}
    return [ns[0] for ns in resp.json().get("namespaces", [])]


def list_tables(catalog: str, namespace: str) -> List[str]:
    """List tables in a namespace (Iceberg REST spec)."""
    resp = requests.get(
        f"{POLARIS_URL}/api/catalog/v1/{catalog}/namespaces/{namespace}/tables",
        headers=_headers(), timeout=10,
    )
    resp.raise_for_status()
    return [t["name"] for t in resp.json().get("identifiers", [])]


def get_catalog_type(catalog_props: Dict[str, Any]) -> str:
    """Determine catalog type: managed / external / foreign."""
    cat_type = catalog_props.get("type", "").upper()
    if cat_type == "INTERNAL":
        return "managed"
    elif cat_type == "EXTERNAL":
        return "external"
    return "foreign"
