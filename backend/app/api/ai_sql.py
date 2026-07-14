"""
AI SQL Assistant — natural language → SQL.

Single-gateway architecture: all LLM access goes through the LiteLLM gateway over
an OpenAI-compatible /v1/chat/completions endpoint. The actual provider behind a
model_name (Bedrock, Anthropic, OpenAI, Ollama/vLLM …) is configured at runtime in
Settings → AI; this module is provider-agnostic and only ever speaks to LiteLLM.

  1. LiteLLM gateway   (LITELLM_URL set → call the active model_name)
  2. Graceful fallback — schema-aware SQL template (no LLM configured)

LITELLM_URL points at the co-located gateway by default, or a customer-supplied
OpenAI-compatible endpoint (BYO). LITELLM_MODEL is the active default model_name,
switched from the Settings → AI page (app.api.ai_backends).
"""
import os
import json
import re
import logging
import asyncio
import threading
import time
import httpx

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from app.guardrails import pii_ko
from app.api.ai_backends import egress_policy, is_external_provider, provider_of_model
from app.api.auth import require_user
from app.ai_context import set_actor, actor_payload
from app.runtime import component_secret

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Gateway configuration (read dynamically — settings API updates os.environ) ─
def _cfg():
    """Read gateway config fresh from env each call so Settings changes apply immediately."""
    # OpenAI 호환 게이트웨이 URL. 비어 있으면 시도하지 않음(템플릿 폴백).
    # 기본은 co-located LiteLLM, 또는 고객 사내 OpenAI 호환 엔드포인트(BYO).
    url = os.getenv("LITELLM_URL", "").strip()
    return {
        "litellm_url":   url,
        "litellm_model": os.getenv("LITELLM_MODEL", "default"),
        # Master key — authenticates to the gateway (admin + chat) when set.
        "master_key":    component_secret("LITELLM_MASTER_KEY", "", component="litellm") if url else "",
    }



# ── Schema context ────────────────────────────────────────────────────────────

# Schema context is expensive (Trino information_schema → Polaris round-trips) and
# changes rarely — cache it so AI SQL latency is dominated by the LLM call, not
# catalog introspection. Invalidated by TTL only; a brand-new table simply takes
# up to AI_SQL_SCHEMA_TTL_SEC to appear in prompts.
_SCHEMA_TTL_SEC = int(os.getenv("AI_SQL_SCHEMA_TTL_SEC", "300"))
_schema_cache: dict = {"text": None, "ts": 0.0}


def _fetch_schema_context() -> str:
    """List tables + columns from the active catalog backend (Glue or Polaris)."""
    try:
        from app.api.query_engine import get_engine
        from app.api.catalog_backend import get_catalog_reader
        eng = get_engine()
        reader = get_catalog_reader()
        lines = [f"Available tables (catalog: {eng.ai_table_prefix}):"]
        for ns in reader.list_namespaces():
            for tbl in reader.list_tables(ns):
                try:
                    cols = reader.get_columns(ns, tbl)
                except Exception:
                    cols = []
                col_str = ", ".join(f"{c['name']} ({c['type']})" for c in cols[:20])
                lines.append(f"  {eng.ai_table_prefix}.{ns}.{tbl}: {col_str}")
                if len(lines) > 50:  # cap prompt size: 50 tables
                    return "\n".join(lines)
        if len(lines) == 1:
            return "No tables found in the catalog."
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[ai_sql] schema fetch failed: {e}")
        return "Schema unavailable — use <catalog>.<schema>.<table> notation."


_refresh_lock = threading.Lock()


def _refresh_schema_cache():
    """Refresh the cache; caller must hold _refresh_lock (released here)."""
    try:
        text = _fetch_schema_context()
        if not text.startswith("Schema unavailable"):
            _schema_cache["text"], _schema_cache["ts"] = text, time.monotonic()
    finally:
        _refresh_lock.release()


def prewarm_schema_cache():
    """Kick off a background fetch so the first AI SQL request isn't cold (~40s on Polaris)."""
    if _refresh_lock.acquire(blocking=False):
        threading.Thread(target=_refresh_schema_cache, daemon=True).start()


def _get_schema_context() -> str:
    """TTL cache with stale-while-revalidate.

    information_schema on Polaris can take ~40s — never block a user request on it
    when any (even expired) cache exists: serve stale and refresh in background.
    Only the very first request after boot fetches synchronously, and startup
    prewarm (main.py) normally covers even that.
    """
    now = time.monotonic()
    cached = _schema_cache["text"]
    if cached is not None:
        if now - _schema_cache["ts"] >= _SCHEMA_TTL_SEC:
            prewarm_schema_cache()  # stale → background revalidate (stampede-guarded)
        return cached
    # Cold (no cache at all): fetch synchronously.
    text = _fetch_schema_context()
    if not text.startswith("Schema unavailable"):
        _schema_cache["text"], _schema_cache["ts"] = text, now
    return text


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_messages(schema_ctx: str, question: str, context: Optional[str]) -> tuple[str, list]:
    from app.api.query_engine import get_engine
    eng = get_engine()
    system = f"""You are an expert SQL assistant for DataPond, an AI Data Foundation.
{eng.ai_dialect_prompt}

{schema_ctx}

Rules:
- Always use fully-qualified table names: {eng.ai_table_prefix}.<schema>.<table>
- Presto/Trino SQL dialect: double-quote identifiers, no backticks
- Return ONLY valid JSON with exactly two keys: "sql" and "explanation"
- "sql": runnable SQL (no markdown, no code fences)
- "explanation": one sentence describing what the query does
- Include ORDER BY for aggregations; default LIMIT 1000"""

    user_text = f"Context: {context}\n\nQuestion: {question}" if context else question
    messages = [{"role": "user", "content": user_text}]
    return system, messages


# ── Provider implementations ──────────────────────────────────────────────────

def _call_litellm(system: str, messages: list) -> str:
    """Call the LiteLLM gateway (OpenAI-compatible).  Connect timeout: 3 s."""
    cfg = _cfg()
    payload = {
        "model": cfg["litellm_model"],
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": 1024,
        **actor_payload("ai_sql"),  # per-user spend attribution (ContextVar copies into to_thread)
    }
    headers = {"Authorization": f"Bearer {cfg['master_key']}"} if cfg["master_key"] else {}
    with httpx.Client(timeout=httpx.Timeout(connect=3.0, read=60.0, write=10.0, pool=5.0)) as client:
        resp = client.post(f"{cfg['litellm_url']}/v1/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


_SQL_KEYWORDS = re.compile(r"\b(SELECT|WITH|INSERT|UPDATE|DELETE|CREATE|SHOW|DESCRIBE|EXPLAIN)\b", re.I)


def _salvage_sql(text: str) -> str:
    """Extract a bare SQL statement from a string that may carry JSON-wrapper noise
    (e.g. a malformed/unparseable `{"sql": "...", "explanation": "..."}` whose inner
    SQL uses unescaped double-quote Trino identifiers). Cut from the first SQL keyword
    and drop the trailing '","explanation":...}' tail plus stray quote/brace."""
    text = (text or "").strip()
    km = _SQL_KEYWORDS.search(text)
    if not km:
        return text
    cut = re.split(r'"\s*,\s*"explanation"', text[km.start():], maxsplit=1)[0]
    return cut.rstrip().rstrip("}").strip().rstrip('"').strip()


def _parse_response(raw: str) -> dict:
    """Parse the model reply into {sql, explanation}. Robust to the common ways the
    reply deviates from spec:
      - ``` / ```json code fences
      - prose before/after the JSON object
      - raw control chars (literal newlines/tabs) inside JSON strings — models emit
        multi-line SQL unescaped, which strict json.loads rejects (the observed bug)
      - a plain-SQL reply with no JSON at all
    Raises only when no SQL can be recovered (caller then uses the template fallback)."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[A-Za-z0-9_-]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s).strip()

    # Try the whole string, then the outermost {...} block. strict=False permits
    # literal control characters inside strings.
    candidates = [s]
    a, b = s.find("{"), s.rfind("}")
    if 0 <= a < b:
        candidates.append(s[a:b + 1])
    for cand in candidates:
        try:
            d = json.loads(cand, strict=False)
        except Exception:
            continue
        if isinstance(d, dict) and str(d.get("sql") or "").strip():
            sql_val = str(d["sql"]).strip()
            expl = str(d.get("explanation") or "").strip()
            # Some models double-wrap: the "sql" value is itself a JSON object
            # {"sql": "...", "explanation": "..."}. Unwrap one level if so.
            if sql_val.startswith("{") and '"sql"' in sql_val:
                try:
                    inner = json.loads(sql_val, strict=False)
                    if isinstance(inner, dict) and str(inner.get("sql") or "").strip():
                        sql_val = str(inner["sql"]).strip()
                        expl = expl or str(inner.get("explanation") or "").strip()
                except Exception:
                    # Malformed nested JSON (e.g. unescaped Trino "identifiers").
                    sql_val = _salvage_sql(sql_val)
            return {"sql": sql_val, "explanation": expl}

    # No usable JSON at all — salvage SQL from a fenced block or a wrapper-ish string.
    body = s
    m = re.search(r"```[A-Za-z0-9_-]*\n?(.*?)```", raw or "", re.S)
    if m:
        body = m.group(1).strip()
    if _SQL_KEYWORDS.search(body):
        # body may still carry a broken `{"sql": "..."}` wrapper → strip it.
        return {"sql": _salvage_sql(body), "explanation": "Generated by AI (non-JSON reply)."}
    raise ValueError("no SQL found in model reply")


# Small TTL cache so the local-only egress guard doesn't add a LiteLLM round-trip to
# every /ai/sql request — the active model rarely changes. Keyed by (url, model).
_PROVIDER_CACHE: dict = {}
_PROVIDER_TTL = 60.0


def _active_provider_is_external() -> Optional[bool]:
    """Best-effort: is the active model an external (egress) provider? None if unknown.

    Defense-in-depth for the local-only egress policy: registration already blocks
    external backends, but a model could be seeded directly into LiteLLM (e.g. via
    helm config), so we re-check the active model's provider at call time. Cached for
    a short TTL to keep this off the per-request hot path."""
    cfg = _cfg()
    if not cfg["litellm_url"]:
        return None
    ck = (cfg["litellm_url"], cfg["litellm_model"])
    hit = _PROVIDER_CACHE.get(ck)
    now = time.monotonic()
    if hit and now - hit[0] < _PROVIDER_TTL:
        return hit[1]
    try:
        headers = {"Authorization": f"Bearer {cfg['master_key']}"} if cfg["master_key"] else {}
        with httpx.Client(timeout=5) as client:
            r = client.get(f"{cfg['litellm_url']}/model/info", headers=headers)
            if r.status_code >= 400:
                return None  # transient — don't cache, retry next request
            val = None
            for m in r.json().get("data", []):
                if m.get("model_name") == cfg["litellm_model"]:
                    model_str = (m.get("litellm_params") or {}).get("model", "")
                    val = is_external_provider(provider_of_model(model_str))
                    break
            _PROVIDER_CACHE[ck] = (now, val)  # cache definitive result (incl. not-found=None)
            return val
    except Exception:
        return None


# ── Request / response models ─────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    context: Optional[str] = None


class AskResponse(BaseModel):
    sql: str
    explanation: str
    has_ai: bool
    provider: str = "none"
    pii_masked: int = 0          # number of Korean PII items masked before LLM call


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/ai/sql", response_model=AskResponse)
async def generate_sql(req: AskRequest, user: dict = Depends(require_user)):
    """Convert a natural language question to a Trino SQL query."""
    set_actor(user)  # attribute LLM spend to this user
    # ── PII guardrail (local, before the prompt reaches the LLM gateway) ──────
    q_text, q_find, q_block = pii_ko.apply(req.question)
    c_text, c_find, c_block = pii_ko.apply(req.context or "")
    pii_count = len(q_find) + len(c_find)
    if q_block or c_block:
        types = sorted({f["type"] for f in (q_find + c_find)})
        return AskResponse(
            sql="-- 요청에 개인정보(PII)가 감지되어 차단되었습니다.\n"
                f"-- 감지 유형: {', '.join(types)}",
            explanation="개인정보 가드레일에 의해 차단됨 (PII_GUARDRAIL_MODE=block).",
            has_ai=False,
            provider="guardrail:blocked",
            pii_masked=pii_count,
        )

    schema_ctx = await asyncio.to_thread(_get_schema_context)
    system, messages = _build_messages(schema_ctx, q_text, c_text or None)

    cfg = _cfg()

    # ── Egress guard (sovereign / air-gapped) ────────────────────────────────
    # local-only 정책에서 활성 모델이 외부(클라우드) provider면 호출 차단(fail-closed) —
    # 데이터가 클러스터를 벗어나지 않도록 보장. 판별 불가 시엔 통과(로컬 사용 견고성 우선).
    if cfg["litellm_url"] and egress_policy() == "local-only":
        if await asyncio.to_thread(_active_provider_is_external) is True:
            logger.warning("[ai_sql] blocked external LLM under local-only egress policy")
            return AskResponse(
                sql="-- 주권 모드(AI_EGRESS_POLICY=local-only): 외부 LLM 사용이 차단되었습니다.\n"
                    "-- 로컬 백엔드(Ollama/vLLM)를 Settings → AI에서 활성화하세요.",
                explanation="AI egress policy 'local-only' — external LLM blocked (no data egress).",
                has_ai=False,
                provider="egress:blocked",
                pii_masked=pii_count,
            )

    # ── 1. LiteLLM gateway (OpenAI 호환 — 모든 provider의 단일 진입점) ─────────
    # 미설정(빈 URL) 시 시도하지 않음 → 죽은 svc로의 불필요한 타임아웃 방지.
    if cfg["litellm_url"]:
        try:
            raw = await asyncio.to_thread(_call_litellm, system, messages)
            data = _parse_response(raw)
            return AskResponse(
                sql=data["sql"].strip(),
                explanation=data.get("explanation", ""),
                has_ai=True,
                provider=f"litellm:{cfg['litellm_model']}",
                pii_masked=pii_count,
            )
        except Exception as e:
            logger.warning(f"[ai_sql] gateway unavailable or no active backend: {e}")

    # ── 2. Graceful fallback — schema-aware SQL template ──────────────────────
    from app.api.query_engine import get_engine
    _prefix = get_engine().ai_table_prefix + "."
    table_lines = "\n".join(
        f"-- SELECT * FROM {line.split(':')[0].strip()} LIMIT 10;"
        for line in schema_ctx.split("\n")
        if line.strip().startswith(_prefix)
    )[:800]

    return AskResponse(
        sql=(
            "-- AI SQL Assistant\n"
            "-- No AI backend configured. Open Settings → AI and add a provider\n"
            "-- backend (AWS Bedrock, Anthropic, OpenAI, or self-hosted Ollama/vLLM),\n"
            "-- then set it active. All providers route through the LiteLLM gateway.\n"
            "--\n"
            "-- Available tables:\n"
            f"{table_lines}"
        ),
        explanation="No AI backend configured. Add and activate one in Settings → AI.",
        has_ai=False,
        provider="none",
        pii_masked=pii_count,
    )
