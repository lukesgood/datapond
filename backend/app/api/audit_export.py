"""`GET /audit/export` — the security audit log, as NDJSON, without a database
credential.

Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (B4)

The point of this route is the "without a database credential" half: a SIEM (or an
auditor's laptop) can pull `security_audit_log` over HTTPS with an API token scoped
to `audit:read`, rather than the operator handing out a Postgres login just so a
log shipper can run `SELECT`. The streaming and pagination logic lives in
`app.audit_retention` (`security_audit_row_to_json`, `stream_security_audit_export`)
next to the retention code that shares its knowledge of the table's shape and its
reasoning about why the table cannot be assumed small — this module is only the
route: parameter parsing, the permission gate, and wiring the generator into a
`StreamingResponse` so a page of rows is written to the wire before the next page
is even fetched, the same pattern `app/api/storage.py`'s object download and
`app/api/connectors.py`'s SSE sync stream already use for "do not build the whole
response in memory."
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.auth import require_permission
from app.api.connectors import get_db_pool
from app.audit_retention import retention_days, stream_security_audit_export, utcnow

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/audit/export", dependencies=[Depends(require_permission("audit:read"))])
async def export_audit_log(
    since: Optional[datetime] = Query(
        None, description="ISO-8601, inclusive. Defaults to the retention floor "
                           "(app.audit_retention.retention_days())."),
    until: Optional[datetime] = Query(
        None, description="ISO-8601, inclusive. Defaults to now."),
):
    """`security_audit_log` between `since` and `until`, oldest first, one JSON
    object per line (NDJSON / `application/x-ndjson`).

    Unbounded on row count by design — a caller integrating with a SIEM wants the
    whole window, not a page they have to paginate through themselves — but never
    unbounded on memory: the body is generated lazily, page by page, by
    `app.audit_retention.stream_security_audit_export`.
    """
    now = utcnow()
    since_ts = since or (now - timedelta(days=retention_days()))
    until_ts = until or now
    for ts in (since_ts, until_ts):
        if ts.tzinfo is None:
            raise HTTPException(status_code=400, detail="since/until must include a timezone")
    if since_ts > until_ts:
        raise HTTPException(status_code=400, detail="since must not be after until")

    pool = await get_db_pool()
    return StreamingResponse(
        stream_security_audit_export(pool, since_ts, until_ts),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="security-audit-log.ndjson"'},
    )
