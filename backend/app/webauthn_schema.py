"""Idempotent webauthn_credentials migration — applied every startup (auth.sql is
sentinel-guarded and won't re-run on an existing DB). Mirrors app/rls/migrate.py."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS webauthn_credentials (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id BYTEA NOT NULL UNIQUE,
    public_key    BYTEA NOT NULL,
    sign_count    BIGINT NOT NULL DEFAULT 0,
    transports    TEXT[],
    aaguid        UUID,
    name          VARCHAR(128),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_webauthn_cred_user ON webauthn_credentials(user_id);
"""


async def ensure_webauthn_schema(pool):
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)
