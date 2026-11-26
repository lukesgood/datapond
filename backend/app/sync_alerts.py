"""Tell someone when a scheduled sync stops working.

A scheduled run writes its outcome to `connector_connections.schedule_last_status`
(app/sync_scheduler.py). Without this, that line on the Sources list was the only sign a
nightly sync had failed, and nobody opens the console to look at a sync they expect to
work. So when a run's status turns from working to not working, the person the schedule
runs as gets one email (the source's owner when that person is gone). A source that keeps
failing sends nothing more until it has worked again (a scheduled run, or any full
sync after the failed one), so a broken source is one email, not one a day.

Mail goes through app/email_util.py (Amazon SES). It is off when SES_FROM_EMAIL is unset
and never raises, so an install without SES runs schedules exactly as before. The
Overview page shows the same failures either way (app/ops_status.py).
"""
import asyncio
import logging
import os
from html import escape
from typing import Optional

logger = logging.getLogger(__name__)


# A fully successful sync of the source (any trigger) after the given scheduled run:
# someone fixed it by hand, so that run's failure is no longer current.
FIXED_SINCE_SQL = ("EXISTS (SELECT 1 FROM connector_sync_history h "
                   "WHERE h.metadata->>'connection_id' = {id}::text AND h.status = 'success' "
                   "AND h.started_at > ({anchor} AT TIME ZONE 'UTC'))")


async def fixed_since(c, connection_id, anchor) -> bool:
    if anchor is None:
        return False
    try:
        return bool(await c.fetchval("SELECT " + FIXED_SINCE_SQL.format(id="$1", anchor="$2::timestamptz"),
                                     str(connection_id), anchor))
    except Exception:
        return False


def is_failure(status: Optional[str]) -> bool:
    """A finished run that did not sync: failed tables, an error, or a skipped run."""
    s = (status or "").strip().lower()
    return bool(s) and not s.startswith("success") and s != "running"


def should_alert(previous: Optional[str], current: Optional[str]) -> bool:
    """Only the turn from working (or never run) to failing."""
    return is_failure(current) and not is_failure(previous)


def source_url(connection_id: str) -> Optional[str]:
    base = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
    return f"{base}/connectors/connections/{connection_id}" if base else None


def alert_email(source: str, status: str, url: Optional[str]):
    """(subject, text, html) for one failed scheduled run."""
    kind, _, detail = status.partition(":")
    kind = kind.strip().lower()
    detail = detail.strip() or status
    if kind == "skipped":
        headline = f"The scheduled sync of {source} did not run"
        why = f"It was skipped: {detail}."
        todo = "Ask someone who may change this source to save its schedule again, or turn the schedule off."
    else:
        headline = f"The scheduled sync of {source} failed"
        why = detail if detail.endswith(".") else f"{detail}."
        todo = "Open the source to see which tables failed and why. The next scheduled run tries again."
    later = "You will not get another email about this source until it syncs successfully again (a scheduled run, or a full sync started by hand)."
    subject = headline
    text = f"{headline}.\n\n{why}\n\n{todo}\n" + (f"\n{url}\n" if url else "") + f"\n{later}\n"
    link = (f'<p style="margin:20px 0;"><a href="{escape(url)}" style="display:inline-block;'
            'background:#2563eb;color:#ffffff;text-decoration:none;padding:9px 16px;'
            'border-radius:8px;font-size:14px;font-weight:600;">Open the source</a></p>') if url else ""
    html = ('<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;color:#0f172a;">'
            f'<h2 style="font-size:17px;margin-bottom:8px;">{escape(headline)}</h2>'
            f'<p style="font-size:14px;line-height:1.6;color:#334155;">{escape(why)}</p>'
            f'<p style="font-size:14px;line-height:1.6;color:#334155;">{escape(todo)}</p>'
            f'{link}<p style="font-size:12px;line-height:1.6;color:#64748b;">{escape(later)}</p></div>')
    return subject, text, html


async def recipient(c, run_as, owner_id) -> Optional[str]:
    """The email of the first active person of: who the schedule runs as, the owner."""
    for uid in (run_as, owner_id):
        if not uid:
            continue
        row = await c.fetchrow("SELECT email, is_active FROM users WHERE id = $1", uid)
        if row and row.get("is_active") and (row.get("email") or "").strip():
            return row["email"].strip()
    return None


async def notify(c, *, connection_id: str, source: str, status: str, run_as, owner_id, send=None) -> bool:
    """Email the failure; False when nobody could be told. Never raises."""
    try:
        to = await recipient(c, run_as, owner_id)
        if not to:
            return False
        if send is None:
            from app.email_util import send_email as send
        subject, text, html = alert_email(source, status, source_url(connection_id))
        return bool(await asyncio.to_thread(send, to, subject, text, html))
    except Exception as e:
        logger.warning("could not send the scheduled-sync alert for %s: %s", source, e)
        return False
