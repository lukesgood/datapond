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


def to_jsonable(value):
    """A value json.dumps can take, with pydantic models kept as their fields.

    Executors hand back whatever the route function they wrap returns, and fifteen of
    the forty return something other than a dict literal — `{"health": ServiceHealth(…)}`
    among them. json.dumps refused that, and because gate._execute wraps only the
    executor call and not the store write, the failure reached the user as a refusal
    with no answer: live, "서비스 상태 알려줘" chose the right tool, ran it, and rendered
    nothing.

    Models are dumped rather than stringified. `default=str` alone would stop the
    exception and store "ServiceHealth(service='backend'…)", which chat_routes then
    puts on screen — worse than the crash, because it looks like it worked.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return value.model_dump()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    return value


def _dumps(value) -> str:
    """Serialise for a jsonb column. `default=str` is this codebase's convention for
    the leftovers — datetimes and UUIDs — see app/audit_retention.py and app/mcp."""
    return json.dumps(to_jsonable(value), default=str)


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
                _dumps(fields.get("params") or {}),
                _dumps(fields["preview"]) if fields.get("preview") is not None else None,
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
                values.append(_dumps(value) if value is not None else None)
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

    async def claim_for_approval(self, invocation_id: str,
                                 approved_by: Optional[str]) -> Optional[dict]:
        """Take a proposed invocation for execution, or return None to the loser.

        `WHERE status = 'proposed'` is what makes this safe: PostgreSQL serialises the
        two UPDATEs on the row, the second sees `approved` and matches nothing, and
        RETURNING gives back no row. A read-then-update in the caller cannot do this —
        both readers see `proposed` and both proceed.
        """
        try:
            async with self._pool.acquire() as conn:
                record = await conn.fetchrow(
                    f"""UPDATE chat_action_invocations
                           SET status = 'approved'::chat_invocation_status,
                               approved_at = NOW(),
                               approved_by = $2::uuid
                         WHERE id = $1::uuid
                           AND status = 'proposed'::chat_invocation_status
                     RETURNING {_COLUMNS}""",
                    invocation_id, approved_by)
        except Exception as e:
            # A malformed id is a refusal, not a 500 — same rule as get().
            logger.debug(f"[chat] approval claim failed: {e}")
            return None
        return _row(record) if record else None

    async def record_audit(self, event: str, user_id: Optional[str],
                           user_email: Optional[str], details: dict) -> None:
        from app.api.auth import record_auth_event
        await record_auth_event(event, user_id=user_id, user_email=user_email,
                                result="success", details=details)


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
