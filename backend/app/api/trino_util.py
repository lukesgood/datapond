"""
Single source of truth for Trino DBAPI connections.

Previously connectors.py / quality.py / catalog.py / ai_sql.py each hardcoded the
host/port/user/scheme and their own TRINO_* constants, so a config change (cluster
DNS, timeout) had to be made in four places and drifted. Import from here instead.
"""
import os

import trino

TRINO_HOST = os.getenv("TRINO_SERVICE_HOST", "trino.datapond.svc.cluster.local")
TRINO_PORT = int(os.getenv("TRINO_SERVICE_PORT", "8080"))
TRINO_CATALOG = "iceberg"


def trino_conn(catalog: str = TRINO_CATALOG, timeout: int = 30):
    """Open a Trino connection. `timeout` is request_timeout in seconds; callers that
    were tuned differently (e.g. ai_sql=10s, catalog=15s) pass their own value."""
    return trino.dbapi.connect(
        host=TRINO_HOST, port=TRINO_PORT,
        user="datapond", catalog=catalog,
        http_scheme="http", request_timeout=timeout,
    )
