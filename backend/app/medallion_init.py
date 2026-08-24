"""Iceberg medallion namespace bootstrap — Trino-only, gated on FEATURE_TRINO.

Creating `iceberg.{raw,refined,serving}` goes through a Trino coordinator. Profiles
that disable Trino (the AWS reference uses the Glue catalog + Athena engine) have no
coordinator to reach, so an unconditional attempt just logged three DNS-failure
warnings per boot and burned up to `request_timeout` seconds of startup time —
observed live on the single-node AWS deployment.

The gate uses the same `_feat` default as `/api/capabilities`, so the bootstrap and
the UI's capability view can never disagree about whether Trino exists.
"""
import os

from app.capabilities import _feat

NAMESPACES = ("raw", "refined", "serving")


def init_medallion_namespaces(logger) -> bool:
    """Create the medallion namespaces via Trino. No-op when Trino is disabled.

    Best-effort like the rest of startup — never raises. Returns True when the
    bootstrap was attempted, False when it was skipped as not applicable.
    """
    if not _feat(os.environ, "TRINO"):
        logger.info("[startup] Medallion init skipped: Trino is not enabled on this profile")
        return False
    try:
        import trino
        conn = trino.dbapi.connect(
            host=os.getenv("TRINO_SERVICE_HOST", "trino.datapond.svc.cluster.local"),
            port=int(os.getenv("TRINO_SERVICE_PORT", "8080")),
            user="datapond", catalog="iceberg", http_scheme="http", request_timeout=10,
        )
        cur = conn.cursor()
        for ns in NAMESPACES:
            try:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS iceberg.{ns}")
                logger.info(f"[startup] Iceberg namespace '{ns}' ready")
            except Exception as e:
                logger.warning(f"[startup] Schema '{ns}' skip: {e}")
    except Exception as e:
        logger.warning(f"[startup] Medallion init skipped: {e}")
    return True
