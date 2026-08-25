"""Postgres behind the gate's `InvocationStore` protocol.

The gate is written against the protocol so it can be tested without a database —
that is where the safety properties live and they hold or fail independently of
storage. This is the boring half.

No messages table. The transcript is not persisted; the request that produced an
action is kept on the invocation. See design §9.
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_COLUMNS = """id, conversation_id, user_id, action_id, page, params, preview,
              request_text, status::text AS status, approved_by, approved_at,
              executed_at, result, error, created_at"""


def _row(record) -> Optional[dict]:
    if record is None:
        return None
    out = dict(record)
    for key in ("id", "conversation_id", "user_id", "approved_by"):
        if out.get(key) is not None:
            out[key] = str(out[key])
    for key in ("params", "preview", "result"):
        value = out.get(key)
        if isinstance(value, str):
            try:
                out[key] = json.loads(value)
            except Exception:
                pass
    return out


class PostgresInvocationStore:
    """Implements InvocationStore. Constructed per request with an asyncpg pool."""

    def __init__(self, pool):
        self._pool = pool

    async def create(self, **fields) -> dict:
        async with self._pool.acquire() as conn:
            record = await conn.fetchrow(
                f"""INSERT INTO chat_action_invocations
                        (conversation_id, user_id, action_id, page, params, preview,
                         request_text, status)
                    VALUES ($1::uuid, $2::uuid, $3, $4, $5::jsonb, $6::jsonb, $7,
                            COALESCE($8, 'proposed')::chat_invocation_status)
                    RETURNING {_COLUMNS}""",
                fields.get("conversation_id"), fields.get("user_id"),
                fields["action_id"], fields.get("page"),
                json.dumps(fields.get("params") or {}),
                json.dumps(fields["preview"]) if fields.get("preview") is not None else None,
                fields.get("request_text"), fields.get("status"),
            )
        return _row(record)

    async def get(self, invocation_id: str) -> Optional[dict]:
        try:
            async with self._pool.acquire() as conn:
                record = await conn.fetchrow(
                    f"SELECT {_COLUMNS} FROM chat_action_invocations WHERE id = $1::uuid",
                    invocation_id)
        except Exception as e:
            # A malformed id is a not-found, not a 500.
            logger.debug(f"[chat] invocation lookup failed: {e}")
            return None
        return _row(record)

    async def update(self, invocation_id: str, **fields) -> dict:
        sets, values = [], []
        for key, value in fields.items():
            if key == "status":
                sets.append(f"status = ${len(values) + 1}::chat_invocation_status")
                values.append(value)
                if value == "executed":
                    sets.append("executed_at = NOW()")
                elif value == "approved":
                    sets.append("approved_at = NOW()")
            elif key == "result":
                sets.append(f"result = ${len(values) + 1}::jsonb")
                values.append(json.dumps(value) if value is not None else None)
            elif key == "approved_by":
                sets.append(f"approved_by = ${len(values) + 1}::uuid")
                values.append(value)
            else:
                sets.append(f"{key} = ${len(values) + 1}")
                values.append(value)
        async with self._pool.acquire() as conn:
            record = await conn.fetchrow(
                f"""UPDATE chat_action_invocations SET {', '.join(sets)}
                     WHERE id = ${len(values) + 1}::uuid RETURNING {_COLUMNS}""",
                *values, invocation_id)
        return _row(record)

    async def record_audit(self, event: str, user_id: Optional[str], details: dict) -> None:
        from app.api.auth import record_auth_event
        await record_auth_event(event, user_id=user_id, result="success", details=details)


async def ensure_conversation(pool, user_id: str, page: Optional[str],
                              conversation_id: Optional[str]) -> str:
    """Return an existing conversation belonging to this user, or open a new one.

    Ownership is checked rather than trusted: a conversation id is client-supplied,
    and attaching an invocation to someone else's conversation would put the wrong
    name beside a change.
    """
    async with pool.acquire() as conn:
        if conversation_id:
            owned = await conn.fetchval(
                "SELECT id FROM chat_conversations WHERE id = $1::uuid AND user_id = $2::uuid",
                conversation_id, user_id)
            if owned:
                await conn.execute(
                    "UPDATE chat_conversations SET last_activity_at = NOW() WHERE id = $1::uuid",
                    conversation_id)
                return str(owned)
        new_id = await conn.fetchval(
            """INSERT INTO chat_conversations (user_id, page)
               VALUES ($1::uuid, $2) RETURNING id""",
            user_id, page)
    return str(new_id)
