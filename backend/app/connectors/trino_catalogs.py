"""Project Trino-backed connections into the Secrets Trino reads, and restart it.

The vault (connector_connections.config_encrypted, Fernet under ENCRYPTION_KEY) is the
source of truth. This module computes what the two Secrets should hold from it —
one `<catalog>.properties` per Trino-backed connection in TRINO_SOURCE_CATALOGS_SECRET
and one `SRC_<SLUG>_PASSWORD` in TRINO_SOURCE_CREDENTIALS_SECRET — patches them only
when they differ, and bumps a restart annotation on the Trino Deployment so it reads the
new files (~1 min; the console shows it from `engine_status`). Running it twice changes
nothing the second time, so a backend restart, two replicas, or a crash between a Secret
patch and a registry insert all converge to the same state.

A row whose credentials no longer decrypt (a re-seeded ENCRYPTION_KEY, as on the live
node on 2026-11-10) is skipped with a warning naming the catalog; one bad row must not
take every source catalog down. The Sources page already shows that row as broken.

Nothing here logs a password or a ciphertext.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Mapping, Optional, Protocol, Sequence

from .base import ConnectorType
from . import trino_source as ts

logger = logging.getLogger(__name__)

RESTART_ANNOTATION = "datapond.io/source-catalogs-restarted-at"

# Task 4 wires this to source_catalog.ensure_rows so a connection that predates Phase 2
# gets its registry row (and therefore its catalog) before the projection is computed.
_ensure_rows: Optional[Callable[[object], Awaitable[int]]] = None


def enabled() -> bool:
    """Whether this profile projects source catalogs at all (the chart sets the env only
    when Trino is on)."""
    return bool(os.getenv("TRINO_SOURCE_CATALOGS_SECRET"))


def _names():
    return (os.environ["TRINO_SOURCE_CATALOGS_SECRET"],
            os.environ["TRINO_SOURCE_CREDENTIALS_SECRET"],
            os.getenv("TRINO_DEPLOYMENT", "trino"))


@dataclass(frozen=True)
class Desired:
    catalogs: Dict[str, str] = field(default_factory=dict)      # file name → properties text
    credentials: Dict[str, str] = field(default_factory=dict)   # env name → value


def desired_from_rows(rows: Sequence[Mapping]) -> Desired:
    """What the Secrets should hold for `rows` (each: catalog, connector_type, config —
    config already decrypted). Rows without a catalog or of a Python-engine type are
    not Trino's; a row that cannot render is skipped with a warning naming it."""
    catalogs: Dict[str, str] = {}
    credentials: Dict[str, str] = {}
    for row in rows:
        catalog = row.get("catalog")
        if not catalog:
            continue
        try:
            t = ConnectorType(str(row.get("connector_type")))
        except ValueError:
            continue
        if ts.engine_of(t) != "trino":
            continue
        try:
            t, config = ts.normalise_type_and_config(t, dict(row.get("config") or {}))
            text = ts.render_catalog_properties(t, catalog, config)
            value = ts.credential_value(t, config)
        except Exception as e:
            logger.warning("[source-catalogs] %s skipped: its configuration cannot be rendered "
                           "(%s)", catalog, type(e).__name__)
            continue
        catalogs[f"{catalog}.properties"] = text
        credentials[ts.credential_env(catalog)] = value
    return Desired(catalogs=catalogs, credentials=credentials)


class KubeClient(Protocol):
    def read_secret_data(self, name: str) -> Dict[str, str]: ...
    def patch_secret_data(self, name: str, data: Dict[str, Optional[str]]) -> None: ...
    def patch_deployment_annotation(self, name: str, key: str, value: str) -> None: ...
    def deployment_status(self, name: str) -> Dict: ...


class RealKube:
    """The Kubernetes API, in-cluster (kubeconfig for local development), namespace
    DATAPOND_NAMESPACE. Secret values cross this boundary decoded."""

    def __init__(self, namespace: Optional[str] = None):
        from kubernetes import client, config
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        self.ns = namespace or os.getenv("DATAPOND_NAMESPACE", "datapond")
        self.core = client.CoreV1Api()
        self.apps = client.AppsV1Api()

    def read_secret_data(self, name):
        data = self.core.read_namespaced_secret(name, self.ns).data or {}
        return {k: base64.b64decode(v).decode("utf-8") for k, v in data.items()}

    def patch_secret_data(self, name, data):
        encoded = {k: (None if v is None else base64.b64encode(v.encode("utf-8")).decode("ascii"))
                   for k, v in data.items()}
        self.core.patch_namespaced_secret(name, self.ns, {"data": encoded})

    def patch_deployment_annotation(self, name, key, value):
        self.apps.patch_namespaced_deployment(
            name, self.ns,
            {"spec": {"template": {"metadata": {"annotations": {key: value}}}}})

    def deployment_status(self, name):
        d = self.apps.read_namespaced_deployment(name, self.ns)
        ann = (d.spec.template.metadata.annotations or {}) if d.spec.template.metadata else {}
        return {"replicas": d.spec.replicas or 0,
                "ready_replicas": d.status.ready_replicas or 0,
                "updated_replicas": d.status.updated_replicas or 0,
                "annotations": dict(ann)}


def _patch_for(current: Mapping[str, str], wanted: Mapping[str, str]) -> Dict[str, Optional[str]]:
    patch: Dict[str, Optional[str]] = {k: v for k, v in wanted.items() if current.get(k) != v}
    patch.update({k: None for k in current if k not in wanted})
    return patch


def apply(desired: Desired, kube: KubeClient) -> bool:
    """Make the two Secrets hold exactly `desired`. Returns whether anything changed."""
    catalogs_secret, credentials_secret, _ = _names()
    changed = False
    for name, wanted in ((catalogs_secret, desired.catalogs),
                         (credentials_secret, desired.credentials)):
        patch = _patch_for(kube.read_secret_data(name), wanted)
        if patch:
            kube.patch_secret_data(name, patch)
            changed = True
    return changed


def restart(kube: KubeClient, now: Optional[str] = None) -> None:
    """Bump the restart annotation; the Deployment's Recreate strategy does the rest."""
    _, _, deployment = _names()
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kube.patch_deployment_annotation(deployment, RESTART_ANNOTATION, stamp)


def engine_status(kube: KubeClient) -> Dict:
    """{"engine", "ready", "restarting", "restarted_at"} — what the console polls."""
    if not enabled():
        return {"engine": "none", "ready": False, "restarting": False, "restarted_at": None}
    _, _, deployment = _names()
    st = kube.deployment_status(deployment)
    replicas = int(st.get("replicas") or 0)
    ready = int(st.get("ready_replicas") or 0) >= replicas and replicas > 0
    rolled = int(st.get("updated_replicas") or 0) >= replicas
    restarted_at = (st.get("annotations") or {}).get(RESTART_ANNOTATION)
    return {"engine": "trino", "ready": ready,
            "restarting": bool(restarted_at) and not (ready and rolled),
            "restarted_at": restarted_at}


_ROWS = """SELECT c.id, c.name, c.connector_type, c.config_encrypted,
                  d.engine_catalog AS catalog
             FROM connector_connections c
             LEFT JOIN data_catalogs d
               ON d.kind = 'trino_source' AND d.config->>'connection_id' = c.id::text
            ORDER BY c.created_at"""


async def load_rows(pool) -> List[dict]:
    """Every connection with its catalog (None when unregistered) and its decrypted
    config. A row the vault cannot open is skipped with a warning naming the catalog."""
    from .vault import CredentialVault
    vault = CredentialVault()
    async with pool.acquire() as conn:
        raw = await conn.fetch(_ROWS)
    rows = []
    for r in raw:
        try:
            config = vault.decrypt_credentials(r["config_encrypted"])
        except Exception:
            logger.warning("[source-catalogs] %s (connection %s) skipped: stored credentials "
                           "cannot be decrypted with the current ENCRYPTION_KEY",
                           r["catalog"] or r["name"], r["id"])
            continue
        rows.append({"id": str(r["id"]), "name": r["name"], "connector_type": r["connector_type"],
                     "catalog": r["catalog"], "config": config})
    return rows


async def project(pool, kube: Optional[KubeClient] = None, *,
                  restart_if_changed: bool = True) -> Dict:
    """The one entry point: registry rows for unregistered connections (Task 4 hook),
    desired state from the vault, Secrets patched, Trino restarted if anything changed.
    {"changed": bool, "catalogs": [names]}."""
    if not enabled():
        return {"changed": False, "catalogs": []}
    if _ensure_rows is not None:
        try:
            await _ensure_rows(pool)
        except Exception as e:
            logger.warning("[source-catalogs] registry rows not ensured: %s", e)
    rows = await load_rows(pool)
    desired = desired_from_rows(rows)
    kube = kube or RealKube()
    changed = await asyncio.to_thread(apply, desired, kube)
    if changed and restart_if_changed:
        await asyncio.to_thread(restart, kube)
    names = sorted(f[: -len(".properties")] for f in desired.catalogs)
    if changed:
        logger.info("[source-catalogs] projected %d catalog(s)%s: %s", len(names),
                    "; Trino restarting" if restart_if_changed else "", ", ".join(names))
    return {"changed": changed, "catalogs": names}


async def reconcile_on_startup(pool) -> None:
    """project(), never raising: a cluster without the Secrets or the RBAC must still
    start, and the warning says what is missing."""
    try:
        out = await project(pool)
        logger.info("[startup] source catalogs: %d (%s)", len(out["catalogs"]),
                    "changed, Trino restarting" if out["changed"] else "unchanged")
    except Exception as e:
        logger.warning("[startup] source catalogs not reconciled: %s", e)
