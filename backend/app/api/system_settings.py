"""
System settings API — persist/retrieve configuration in DB.
Sensitive values (API keys, secrets) are encrypted with the same vault used by connectors.
"""
import os
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.connectors import get_db_pool
from app.connectors.vault import CredentialVault

logger = logging.getLogger(__name__)
router = APIRouter()
vault = CredentialVault(os.getenv("ENCRYPTION_KEY", "dev-key-32-bytes-padding-here!!"))

# Keys that must be stored encrypted
SENSITIVE_KEYS = {
    "ai.aws_access_key_id",
    "ai.aws_secret_access_key",
    "ai.anthropic_api_key",
}

# All allowed settings keys and their env-var names for runtime apply
AI_ENV_MAP = {
    "ai.provider":              "AI_PROVIDER",
    "ai.litellm_url":           "LITELLM_URL",
    "ai.litellm_model":         "LITELLM_MODEL",
    "ai.aws_bedrock_region":    "AWS_BEDROCK_REGION",
    "ai.aws_access_key_id":     "AWS_ACCESS_KEY_ID",
    "ai.aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
    "ai.bedrock_model_id":      "BEDROCK_MODEL_ID",
    "ai.anthropic_api_key":     "ANTHROPIC_API_KEY",
}


class SettingsPatch(BaseModel):
    settings: dict[str, Any]


_DDL = """CREATE TABLE IF NOT EXISTS system_settings (
             key        TEXT PRIMARY KEY,
             value      TEXT,
             updated_at TIMESTAMPTZ DEFAULT NOW()
         )"""


async def _ensure_table(conn) -> None:
    """Create system_settings if absent — no schema/migration file defines it, so a
    fresh deploy would otherwise 500 on the first settings query."""
    await conn.execute(_DDL)


@router.get("/settings/system")
async def get_system_settings():
    """Return all stored system settings (sensitive values masked)."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _ensure_table(conn)
        rows = await conn.fetch("SELECT key, value FROM system_settings")

    result: dict[str, Any] = {}
    for row in rows:
        k, v = row["key"], row["value"]
        if k in SENSITIVE_KEYS:
            try:
                decrypted = vault.decrypt_credentials(v)
                result[k] = "••••••••" if decrypted.get("v") else ""
            except Exception:
                result[k] = ""
        else:
            try:
                result[k] = json.loads(v)
            except Exception:
                result[k] = v
    return {"settings": result}


@router.patch("/settings/system")
async def update_system_settings(body: SettingsPatch):
    """Save settings and apply to runtime env vars immediately."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _ensure_table(conn)
        for k, v in body.settings.items():
            if k not in AI_ENV_MAP and not k.startswith("ai."):
                raise HTTPException(400, f"Unknown setting key: {k}")

            if k in SENSITIVE_KEYS:
                if v and not v.startswith("•"):
                    stored = vault.encrypt_credentials({"v": str(v)})
                else:
                    continue  # masked — don't overwrite
            else:
                stored = json.dumps(v)

            await conn.execute(
                """INSERT INTO system_settings (key, value, updated_at)
                   VALUES ($1, $2, NOW())
                   ON CONFLICT (key) DO UPDATE
                   SET value = EXCLUDED.value, updated_at = NOW()""",
                k, stored,
            )

    # Apply to runtime
    await _apply_ai_settings_to_env(pool)
    return {"success": True}


@router.get("/settings/system/ai")
async def get_ai_settings():
    """Return AI provider config with real values for testing (keys partially masked)."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _ensure_table(conn)
        rows = await conn.fetch(
            "SELECT key, value FROM system_settings WHERE key LIKE 'ai.%'"
        )

    result: dict[str, str] = {}
    for row in rows:
        k, v = row["key"], row["value"]
        if k in SENSITIVE_KEYS:
            try:
                dec = vault.decrypt_credentials(v)
                raw = dec.get("v", "")
                result[k] = (raw[:4] + "••••" + raw[-4:]) if len(raw) > 8 else ("••••" if raw else "")
            except Exception:
                result[k] = ""
        else:
            try:
                result[k] = json.loads(v)
            except Exception:
                result[k] = v

    # Merge with current env (env wins display if DB empty)
    _litellm_url = os.getenv("LITELLM_URL", "http://litellm.datapond.svc.cluster.local:4000")
    defaults = {
        "ai.provider":           (
            "litellm" if _litellm_url
            else ("bedrock" if os.getenv("AWS_BEDROCK_REGION") else ("anthropic" if os.getenv("ANTHROPIC_API_KEY") else "none"))
        ),
        "ai.litellm_url":        _litellm_url,
        "ai.litellm_model":      os.getenv("LITELLM_MODEL", "default"),
        "ai.aws_bedrock_region": os.getenv("AWS_BEDROCK_REGION", ""),
        "ai.bedrock_model_id":   os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
        "ai.aws_access_key_id":  "••••" if os.getenv("AWS_ACCESS_KEY_ID") else "",
        "ai.aws_secret_access_key": "••••" if os.getenv("AWS_SECRET_ACCESS_KEY") else "",
        "ai.anthropic_api_key":  "••••" if os.getenv("ANTHROPIC_API_KEY") else "",
    }
    for k, v in defaults.items():
        if k not in result:
            result[k] = v

    return {"settings": result}


async def _apply_ai_settings_to_env(pool) -> None:
    """Load AI settings from DB and apply to os.environ for current process."""
    try:
        async with pool.acquire() as conn:
            await _ensure_table(conn)
            rows = await conn.fetch(
                "SELECT key, value FROM system_settings WHERE key LIKE 'ai.%'"
            )
        for row in rows:
            k, v = row["key"], row["value"]
            env_key = AI_ENV_MAP.get(k)
            if not env_key:
                continue
            if k in SENSITIVE_KEYS:
                try:
                    dec = vault.decrypt_credentials(v)
                    os.environ[env_key] = dec.get("v", "")
                except Exception:
                    pass
            else:
                try:
                    os.environ[env_key] = str(json.loads(v))
                except Exception:
                    os.environ[env_key] = v
    except Exception as e:
        logger.warning(f"[settings] env apply failed: {e}")


async def load_settings_on_startup(pool) -> None:
    """Called at startup to restore persisted settings into env."""
    await _apply_ai_settings_to_env(pool)
