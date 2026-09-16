"""Idempotent webauthn_credentials migration. Mirrors app/rls/migrate.py.

NOT CURRENTLY CALLED — 0001_baseline.sql creates webauthn_credentials and the migrate
Job applies it as the owning credential. Left in place for the fresh-DB path, but the
runtime role is not granted DDL (see app/api/system_settings._ensure_table), and
CREATE INDEX needs table ownership, so calling this from a request path would fail."""

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
