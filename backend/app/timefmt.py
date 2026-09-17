"""One way to put a timestamp on the wire.

Two wrong answers were live at once, and which one you got depended on the column.

    aware (timestamptz, what asyncpg returns)
        isoformat() already ends in "+00:00"; the code appended "Z" on top, so the
        browser received "2026-09-17T09:00:00+00:00Z" and new Date() rejected it.
        The user-management Joined column rendered "Invalid Date".

    naive (datetime.utcnow(), still used in places)
        isoformat() carries no offset at all, so dropping the "Z" leaves
        "2026-09-17T09:00:00" — which the browser reads as LOCAL time, silently
        shifting it by the viewer's offset.

Normalising first and emitting exactly one marker makes the caller's question
("is this column aware?") stop mattering, which is the only version of this that
stays correct when someone adds the next column.
"""
from datetime import datetime, timezone
from typing import Optional


def iso_utc(value: Optional[datetime]) -> Optional[str]:
    """UTC ISO-8601 ending in a single "Z", or None.

    A naive value is read as UTC rather than as local time: every naive datetime in
    this codebase comes from datetime.utcnow().
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
