"""
AI backends — manage LLM provider backends through the LiteLLM gateway (DB mode).

Architecture: the DataPond backend speaks only OpenAI-compatible HTTP to a single
LiteLLM gateway. Every provider (Bedrock, Anthropic, OpenAI, Ollama/vLLM, Gemini …)
is a model entry in LiteLLM's database, added/removed/switched at RUNTIME via its
admin API — no helm upgrade needed. This router proxies those admin calls and tracks
which model_name is the active default that AI SQL (app.api.ai_sql) calls.

LiteLLM admin API (authenticated with the master key):
  GET  /model/info                 → registered models (litellm_params, model_info.id)
  POST /model/new                  → add a model  {model_name, litellm_params}
  POST /model/delete               → remove a model  {id}
  POST /v1/chat/completions        → used here for per-backend connection tests
  GET  /health/readiness           → gateway + DB liveness
"""
import os
import json
import time
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.connectors import get_db_pool

logger = logging.getLogger(__name__)
router = APIRouter()

# system_settings key holding the active default model_name for AI SQL.
ACTIVE_MODEL_KEY = "ai.litellm_model"

# Supported provider types → LiteLLM model-string prefix.
# (See https://docs.litellm.ai/docs/providers — model resolves to "<prefix><model>".)
# `external` = inference leaves the cluster (data egress). Local providers keep
# inference on customer infrastructure (sovereign / air-gapped).
PROVIDERS: dict[str, dict] = {
    "bedrock":   {"label": "AWS Bedrock",              "prefix": "bedrock/",   "external": True},
    "anthropic": {"label": "Anthropic API",            "prefix": "anthropic/", "external": True},
    "openai":    {"label": "OpenAI",                   "prefix": "openai/",    "external": True},
    "gemini":    {"label": "Google Gemini",            "prefix": "gemini/",    "external": True},
    "ollama":    {"label": "Ollama (self-hosted)",     "prefix": "ollama/",    "external": False},
    "vllm":      {"label": "vLLM / OpenAI-compatible", "prefix": "openai/",    "external": False},
}

# ── AI egress policy (environment-configurable) ─────────────────────────────────
# Decides whether external (cloud) LLM providers are allowed for this deployment.
#   "local-only"   → sovereign / air-gapped: only on-prem LLMs (Ollama/vLLM); external
#                    providers are rejected at registration AND blocked at call time.
#   "cloud-allowed"→ external providers (Bedrock/Anthropic/OpenAI/Gemini) permitted.
# Set via AI_EGRESS_POLICY env (Helm: ai.egressPolicy). Default keeps backward compat.

def egress_policy() -> str:
    p = os.getenv("AI_EGRESS_POLICY", "cloud-allowed").strip().lower().replace("_", "-")
    return "local-only" if p in ("local-only", "sovereign", "no-egress", "airgap") else "cloud-allowed"


def is_external_provider(provider: str) -> bool:
    info = PROVIDERS.get((provider or "").lower())
    return bool(info and info.get("external"))


def provider_allowed(provider: str) -> bool:
    """False when egress policy is local-only and the provider sends data out."""
    return egress_policy() != "local-only" or not is_external_provider(provider)


def provider_of_model(model_str: str) -> str:
    """LiteLLM model string ("bedrock/claude…") → provider id ("bedrock")."""
    return model_str.split("/", 1)[0].lower() if "/" in (model_str or "") else "unknown"


# ── Gateway access ──────────────────────────────────────────────────────────────

def _gateway() -> tuple[str, str]:
    """Return (base_url, master_key). Raises 503 if the gateway isn't configured."""
    url = os.getenv("LITELLM_URL", "").strip().rstrip("/")
    key = os.getenv("LITELLM_MASTER_KEY", "").strip()
    if not url:
        raise HTTPException(503, "LiteLLM gateway not configured (LITELLM_URL is empty).")
    return url, key


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"} if key else {}


def _short(text: str, n: int = 300) -> str:
    return (text or "").strip().replace("\n", " ")[:n]


# ── Request models ──────────────────────────────────────────────────────────────

class BackendCreate(BaseModel):
    model_name: str                              # friendly name the app calls (e.g. "default")
    provider: str                                # bedrock | anthropic | openai | gemini | ollama | vllm
    model: str                                   # provider model id (e.g. "claude-haiku-4-5-...")
    api_base: Optional[str] = None               # for ollama / vllm / self-hosted
    api_key: Optional[str] = None                # anthropic / openai / gemini / vllm
    aws_region_name: Optional[str] = None        # bedrock
    aws_access_key_id: Optional[str] = None      # bedrock (blank → instance IAM role)
    aws_secret_access_key: Optional[str] = None  # bedrock
    # Advanced per-model params (optional)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    rpm: Optional[int] = None                     # requests/min cap
    tpm: Optional[int] = None                     # tokens/min cap
    set_active: bool = False                      # make this the active default after creating


class ActivePatch(BaseModel):
    model_name: str


class KeyCreate(BaseModel):
    key_alias: str
    models: list[str] = []                        # restrict to these model_names ([] = all)
    max_budget: Optional[float] = None            # USD spend cap
    rpm_limit: Optional[int] = None
    tpm_limit: Optional[int] = None
    duration: Optional[str] = None                # e.g. "30d", "24h"


def _build_params(b: BackendCreate) -> dict:
    """Translate a provider-shaped request into LiteLLM litellm_params."""
    prefix = PROVIDERS.get(b.provider, {}).get("prefix", "")
    # Allow callers to pass a fully-qualified model ("provider/xyz") untouched.
    model = b.model if "/" in b.model else f"{prefix}{b.model}"
    params: dict = {"model": model}
    if b.api_base:               params["api_base"] = b.api_base
    if b.api_key:                params["api_key"] = b.api_key
    if b.aws_region_name:        params["aws_region_name"] = b.aws_region_name
    if b.aws_access_key_id:       params["aws_access_key_id"] = b.aws_access_key_id
    if b.aws_secret_access_key:   params["aws_secret_access_key"] = b.aws_secret_access_key
    if b.temperature is not None: params["temperature"] = b.temperature
    if b.max_tokens is not None:  params["max_tokens"] = b.max_tokens
    if b.rpm is not None:         params["rpm"] = b.rpm
    if b.tpm is not None:         params["tpm"] = b.tpm
    return params


# ── Active-model persistence (system_settings) ──────────────────────────────────

async def _ensure_table(conn) -> None:
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS system_settings (
               key        TEXT PRIMARY KEY,
               value      TEXT,
               updated_at TIMESTAMPTZ DEFAULT NOW()
           )"""
    )


async def _get_active_model() -> Optional[str]:
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM system_settings WHERE key = $1", ACTIVE_MODEL_KEY)
        if row and row["value"]:
            try:
                return json.loads(row["value"])
            except Exception:
                return row["value"]
    except Exception as e:
        logger.warning(f"[ai_backends] active model read failed: {e}")
    return (os.getenv("LITELLM_MODEL") or "").strip() or None


async def _set_active_model(model_name: str) -> None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _ensure_table(conn)
        await conn.execute(
            """INSERT INTO system_settings (key, value, updated_at)
               VALUES ($1, $2, NOW())
               ON CONFLICT (key) DO UPDATE
               SET value = EXCLUDED.value, updated_at = NOW()""",
            ACTIVE_MODEL_KEY, json.dumps(model_name),
        )
    # Apply immediately so ai_sql picks it up without a restart.
    os.environ["LITELLM_MODEL"] = model_name


# ── Routes ──────────────────────────────────────────────────────────────────────

@router.get("/settings/ai/providers")
async def list_providers():
    """Supported provider types + the active egress policy (for the Add-backend form).
    `allowed` is False for external providers when the policy is local-only."""
    policy = egress_policy()
    return {
        "egress_policy": policy,
        "providers": [
            {"id": k, "label": v["label"], "external": v["external"],
             "allowed": policy != "local-only" or not v["external"]}
            for k, v in PROVIDERS.items()
        ],
    }


@router.get("/settings/ai/status")
async def gateway_status():
    """Gateway health + registered backend count + active default model."""
    policy = egress_policy()
    try:
        url, key = _gateway()
    except HTTPException:
        return {"gateway": "unconfigured", "active": None, "backend_count": 0, "egress_policy": policy}

    active = await _get_active_model()
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            h = await c.get(f"{url}/health/readiness")
            healthy = h.status_code < 400
            count = 0
            try:
                mi = await c.get(f"{url}/model/info", headers=_headers(key))
                if mi.status_code < 400:
                    count = len(mi.json().get("data", []))
            except Exception:
                pass
        return {
            "gateway": "healthy" if healthy else "unhealthy",
            "active": active,
            "backend_count": count,
            "egress_policy": policy,
        }
    except Exception as e:
        return {"gateway": "unreachable", "active": active, "backend_count": 0,
                "egress_policy": policy, "detail": _short(str(e), 150)}


@router.get("/settings/ai/backends")
async def list_backends():
    """List provider backends registered in the LiteLLM gateway."""
    url, key = _gateway()
    active = await _get_active_model()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{url}/model/info", headers=_headers(key))
            r.raise_for_status()
            data = r.json().get("data", [])
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Cannot reach LiteLLM gateway: {_short(str(e), 200)}")

    backends = []
    for m in data:
        params = m.get("litellm_params", {}) or {}
        info = m.get("model_info", {}) or {}
        model_str = params.get("model", "") or ""
        provider = model_str.split("/", 1)[0] if "/" in model_str else "unknown"
        name = m.get("model_name")
        backends.append({
            "id": info.get("id"),
            "model_name": name,
            "model": model_str,
            "provider": provider,
            "api_base": params.get("api_base"),
            "is_active": name == active,
        })
    return {"backends": backends, "active": active}


@router.post("/settings/ai/backends")
async def create_backend(body: BackendCreate):
    """Register a new provider backend in the gateway (optionally set it active)."""
    if not body.model_name.strip() or not body.model.strip():
        raise HTTPException(400, "model_name and model are required.")
    if not provider_allowed(body.provider):
        raise HTTPException(
            403,
            f"AI egress policy is 'local-only' (sovereign / air-gapped): the external "
            f"provider '{body.provider}' would send data outside the cluster and is "
            f"blocked. Use a local backend (Ollama / vLLM), or change ai.egressPolicy "
            f"for this environment.",
        )
    url, key = _gateway()
    payload = {"model_name": body.model_name.strip(), "litellm_params": _build_params(body)}
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{url}/model/new", headers=_headers(key), json=payload)
        if r.status_code >= 400:
            raise HTTPException(r.status_code, f"LiteLLM rejected the backend: {_short(r.text)}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Cannot reach LiteLLM gateway: {_short(str(e), 200)}")

    if body.set_active:
        await _set_active_model(body.model_name.strip())
    return {"success": True, "active": body.set_active}


@router.delete("/settings/ai/backends/{model_id}")
async def delete_backend(model_id: str):
    """Remove a backend by its LiteLLM model id."""
    url, key = _gateway()
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{url}/model/delete", headers=_headers(key), json={"id": model_id})
        if r.status_code >= 400:
            raise HTTPException(r.status_code, f"Delete failed: {_short(r.text)}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Cannot reach LiteLLM gateway: {_short(str(e), 200)}")
    return {"success": True}


@router.post("/settings/ai/active")
async def set_active(body: ActivePatch):
    """Set the active default backend (model_name) used by AI SQL."""
    if not body.model_name.strip():
        raise HTTPException(400, "model_name is required.")
    await _set_active_model(body.model_name.strip())
    return {"success": True, "active": body.model_name.strip()}


async def _provider_of_registered_model(url: str, key: str, model_name: str) -> Optional[str]:
    """Resolve a registered model_name to its provider id via the gateway, or None."""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{url}/model/info", headers=_headers(key))
            if r.status_code >= 400:
                return None
            for m in r.json().get("data", []):
                if m.get("model_name") == model_name:
                    return provider_of_model((m.get("litellm_params") or {}).get("model", ""))
    except Exception:
        return None
    return None


@router.post("/settings/ai/backends/{model_name}/test")
async def test_backend(model_name: str):
    """Send a tiny completion through the gateway to verify a backend works."""
    url, key = _gateway()
    # Enforce the egress policy here too — otherwise a model seeded outside the
    # registration API (e.g. via helm config) could be exercised against an external
    # provider on a local-only (sovereign) deployment, leaking the prompt.
    if egress_policy() == "local-only":
        prov = await _provider_of_registered_model(url, key, model_name)
        if prov and is_external_provider(prov):
            raise HTTPException(
                403,
                f"AI egress policy is 'local-only': testing the external provider "
                f"'{prov}' is blocked (it would send data outside the cluster).",
            )
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "Reply with the single word: OK"}],
        "max_tokens": 5,
    }
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)) as c:
            r = await c.post(f"{url}/v1/chat/completions", headers=_headers(key), json=payload)
        latency = int((time.monotonic() - t0) * 1000)
        if r.status_code >= 400:
            return {"ok": False, "latency_ms": latency, "message": _short(r.text, 200)}
        content = r.json()["choices"][0]["message"]["content"]
        return {"ok": True, "latency_ms": latency, "message": _short(content, 120)}
    except Exception as e:
        return {"ok": False, "latency_ms": int((time.monotonic() - t0) * 1000), "message": _short(str(e), 200)}


# ── Virtual keys / budgets / spend (LiteLLM admin API) ──────────────────────────

@router.get("/settings/ai/keys")
async def list_keys():
    """List virtual API keys with their budget/spend/limits."""
    url, key = _gateway()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{url}/key/list", headers=_headers(key),
                            params={"return_full_object": "true", "size": "200"})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Cannot reach LiteLLM gateway: {_short(str(e), 200)}")

    raw = data.get("keys", []) if isinstance(data, dict) else (data or [])
    out = []
    for k in raw:
        if isinstance(k, str):
            out.append({"token": k, "key_alias": None, "spend": 0, "max_budget": None,
                        "models": [], "rpm_limit": None, "tpm_limit": None})
            continue
        out.append({
            "token":      k.get("token") or k.get("key_name"),
            "key_alias":  k.get("key_alias"),
            "spend":      k.get("spend") or 0,
            "max_budget": k.get("max_budget"),
            "models":     k.get("models") or [],
            "rpm_limit":  k.get("rpm_limit"),
            "tpm_limit":  k.get("tpm_limit"),
            "created_at": k.get("created_at"),
        })
    return {"keys": out}


@router.post("/settings/ai/keys")
async def create_key(body: KeyCreate):
    """Generate a virtual API key (optionally scoped to models, with budget/limits)."""
    if not body.key_alias.strip():
        raise HTTPException(400, "key_alias is required.")
    url, key = _gateway()
    payload: dict = {"key_alias": body.key_alias.strip()}
    if body.models:                payload["models"] = body.models
    if body.max_budget is not None: payload["max_budget"] = body.max_budget
    if body.rpm_limit is not None:  payload["rpm_limit"] = body.rpm_limit
    if body.tpm_limit is not None:  payload["tpm_limit"] = body.tpm_limit
    if body.duration:               payload["duration"] = body.duration
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{url}/key/generate", headers=_headers(key), json=payload)
        if r.status_code >= 400:
            raise HTTPException(r.status_code, f"Key generation failed: {_short(r.text)}")
        d = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Cannot reach LiteLLM gateway: {_short(str(e), 200)}")
    # The plaintext key is shown ONCE — surface it to the caller.
    return {"key": d.get("key"), "key_alias": d.get("key_alias", body.key_alias.strip())}


@router.delete("/settings/ai/keys/{token}")
async def delete_key(token: str):
    """Revoke a virtual API key by its token."""
    url, key = _gateway()
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{url}/key/delete", headers=_headers(key), json={"keys": [token]})
        if r.status_code >= 400:
            raise HTTPException(r.status_code, f"Key delete failed: {_short(r.text)}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Cannot reach LiteLLM gateway: {_short(str(e), 200)}")
    return {"success": True}


@router.get("/settings/ai/spend")
async def spend_summary():
    """Aggregate spend across all virtual keys (USD)."""
    url, key = _gateway()
    total = 0.0
    n = 0
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{url}/key/list", headers=_headers(key),
                            params={"return_full_object": "true", "size": "500"})
            if r.status_code < 400:
                data = r.json()
                raw = data.get("keys", []) if isinstance(data, dict) else (data or [])
                for k in raw:
                    if isinstance(k, dict) and k.get("spend"):
                        total += float(k["spend"]); n += 1
    except Exception as e:
        logger.warning(f"[ai_backends] spend summary failed: {e}")
    return {"total_spend": round(total, 4), "keys_with_spend": n}
