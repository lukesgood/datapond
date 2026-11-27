"""Problem reports and feature requests from the people using the console.

The Assistant panel's footer files them (frontend components/chat/feedback-form.tsx):
a kind (bug | feature), a title, what happened or what is wanted, and the page it was
filed from with the app version and browser, which is what a report usually lacks.
Administrators read and triage them in Settings → Feedback (open → planned → done, or
dismissed, with a note the reporter sees). Each person can see the status of their
own reports.

Anyone signed in as a person may file (agents have no console to report on). When SES
is configured (SES_FROM_EMAIL) every active administrator gets a short email per
report; without it the list is the only place they appear. Filing never fails because
mail did.
"""
import asyncio
import logging
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import _get_pool, require_admin, require_human
from app.timefmt import iso_utc

logger = logging.getLogger(__name__)
router = APIRouter(tags=["feedback"])

STATUSES = ("open", "planned", "done", "dismissed")
_tasks: set = set()   # keep notification tasks referenced until they finish


class FeedbackIn(BaseModel):
    kind: Literal["bug", "feature"]
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=5000)
    page: Optional[str] = Field(default=None, max_length=500)
    app_version: Optional[str] = Field(default=None, max_length=64)
    user_agent: Optional[str] = Field(default=None, max_length=300)


class FeedbackUpdate(BaseModel):
    status: Optional[Literal["open", "planned", "done", "dismissed"]] = None
    admin_note: Optional[str] = Field(default=None, max_length=2000)


def _row(r) -> dict:
    return {
        "id": str(r["id"]), "kind": r["kind"], "title": r["title"], "body": r["body"],
        "page": r["page"], "app_version": r["app_version"], "user_agent": r["user_agent"],
        "created_by": str(r["created_by"]) if r["created_by"] else None,
        "created_by_name": r["created_by_name"], "status": r["status"],
        "admin_note": r["admin_note"],
        "created_at": iso_utc(r["created_at"]), "updated_at": iso_utc(r["updated_at"]),
    }


def _clean_page(page: Optional[str]) -> Optional[str]:
    """A path on this site, never a full URL with someone's query string in it."""
    p = (page or "").strip()
    if not p.startswith("/") or p.startswith("//"):
        return None
    return p.split("?", 1)[0].split("#", 1)[0][:500]


def report_email(item: dict, url: Optional[str]):
    kind = "Problem report" if item["kind"] == "bug" else "Feature request"
    subject = f"[DataPond] {kind}: {item['title']}"
    lines = [f"{kind} from {item['created_by_name'] or 'someone'}", "", item["title"], ""]
    if item["body"]:
        lines += [item["body"], ""]
    lines += [f"Page: {item['page'] or '—'}", f"Version: {item['app_version'] or '—'}"]
    if url:
        lines += ["", url]
    return subject, "\n".join(lines)


async def _notify_admins(item: dict) -> None:
    try:
        import os
        if not (os.getenv("SES_FROM_EMAIL") or "").strip():
            return
        from app.email_util import send_email
        pool = await _get_pool()
        async with pool.acquire() as c:
            rows = await c.fetch(
                "SELECT email FROM users WHERE role = 'admin' AND is_active "
                "AND coalesce(auth_method::text, 'local') <> 'service'")
        base = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
        subject, text = report_email(item, f"{base}/settings?tab=feedback" if base else None)
        for r in rows:
            to = (r["email"] or "").strip()
            if to and not to.endswith("@datapond.local"):
                await asyncio.to_thread(send_email, to, subject, text)
    except Exception as e:                           # never fail a report over mail
        logger.warning("feedback notification failed: %s", e)


@router.post("/feedback", status_code=201)
async def file_feedback(body: FeedbackIn, user: dict = Depends(require_human)):
    """File a problem report or a feature request as the signed-in person."""
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Give it a title.")
    uid = user.get("id")
    name = user.get("display_name") or user.get("username") or user.get("email")
    pool = await _get_pool()
    async with pool.acquire() as c:
        r = await c.fetchrow(
            """INSERT INTO user_feedback (kind, title, body, page, app_version, user_agent,
                                         created_by, created_by_name)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *""",
            body.kind, title, body.body.strip(), _clean_page(body.page),
            (body.app_version or "").strip() or None, (body.user_agent or "").strip() or None,
            uuid.UUID(uid) if uid else None, name)
    item = _row(r)
    t = asyncio.create_task(_notify_admins(item))
    _tasks.add(t); t.add_done_callback(_tasks.discard)
    return item


@router.get("/feedback/mine")
async def my_feedback(user: dict = Depends(require_human)):
    """The caller's own reports, newest first, with their status and the note."""
    uid = user.get("id")
    if not uid:
        return {"items": []}
    pool = await _get_pool()
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM user_feedback WHERE created_by = $1 ORDER BY created_at DESC LIMIT 50",
            uuid.UUID(uid))
    return {"items": [_row(r) for r in rows]}


@router.get("/feedback")
async def list_feedback(status: Optional[str] = None, kind: Optional[str] = None,
                        _admin: dict = Depends(require_admin)):
    """Every report for triage, newest first, with counts per status."""
    where, args = [], []
    if status in STATUSES:
        args.append(status); where.append(f"status = ${len(args)}")
    if kind in ("bug", "feature"):
        args.append(kind); where.append(f"kind = ${len(args)}")
    sql = "SELECT * FROM user_feedback" + (" WHERE " + " AND ".join(where) if where else "") \
        + " ORDER BY created_at DESC LIMIT 500"
    pool = await _get_pool()
    async with pool.acquire() as c:
        rows = await c.fetch(sql, *args)
        counts = {r["status"]: r["n"] for r in await c.fetch(
            "SELECT status, count(*) AS n FROM user_feedback GROUP BY status")}
    return {"items": [_row(r) for r in rows],
            "counts": {s: int(counts.get(s, 0)) for s in STATUSES}}


@router.patch("/feedback/{feedback_id}")
async def update_feedback(feedback_id: str, body: FeedbackUpdate,
                          _admin: dict = Depends(require_admin)):
    """Move a report along (open → planned → done, or dismissed) and leave a note."""
    try:
        fid = uuid.UUID(feedback_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such report")
    sets, args = [], []
    if body.status is not None:
        args.append(body.status); sets.append(f"status = ${len(args)}")
    if body.admin_note is not None:
        args.append(body.admin_note.strip() or None); sets.append(f"admin_note = ${len(args)}")
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to change")
    args.append(fid)
    pool = await _get_pool()
    async with pool.acquire() as c:
        r = await c.fetchrow(
            f"UPDATE user_feedback SET {', '.join(sets)}, updated_at = now() "
            f"WHERE id = ${len(args)} RETURNING *", *args)
    if not r:
        raise HTTPException(status_code=404, detail="No such report")
    return _row(r)
