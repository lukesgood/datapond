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
import logging
import asyncio
import trino
import httpx

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.guardrails import pii_ko
from app.api.ai_backends import egress_policy, is_external_provider, provider_of_model

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Gateway configuration (read dynamically — settings API updates os.environ) ─
def _cfg():
    """Read gateway config fresh from env each call so Settings changes apply immediately."""
    return {
        # OpenAI 호환 게이트웨이 URL. 비어 있으면 시도하지 않음(템플릿 폴백).
        # 기본은 co-located LiteLLM, 또는 고객 사내 OpenAI 호환 엔드포인트(BYO).
        "litellm_url":   os.getenv("LITELLM_URL", "").strip(),
        "litellm_model": os.getenv("LITELLM_MODEL", "default"),
        # Master key — authenticates to the gateway (admin + chat) when set.
        "master_key":    os.getenv("LITELLM_MASTER_KEY", "").strip(),
    }

TRINO_HOST    = os.getenv("TRINO_SERVICE_HOST", "trino.datapond.svc.cluster.local")
TRINO_PORT    = int(os.getenv("TRINO_SERVICE_PORT", "8080"))
TRINO_CATALOG = "iceberg"


# ── Schema context ────────────────────────────────────────────────────────────

def _get_schema_context() -> str:
    """Fetch Iceberg table/column info from Trino for the prompt."""
    try:
        conn = trino.dbapi.connect(
            host=TRINO_HOST, port=TRINO_PORT,
            user="datapond", catalog=TRINO_CATALOG,
            http_scheme="http", request_timeout=10,
        )
        cur = conn.cursor()
        cur.execute(
            f"SELECT table_schema, table_name "
            f"FROM {TRINO_CATALOG}.information_schema.tables "
            f"WHERE table_schema NOT IN ('information_schema','system') "
            f"ORDER BY table_schema, table_name LIMIT 50"
        )
        tables = cur.fetchall()
        if not tables:
            return "No tables found in the Iceberg catalog."

        lines = ["Available Iceberg tables (catalog: iceberg):"]
        for schema, table in tables:
            try:
                cur2 = conn.cursor()
                cur2.execute(
                    f"SELECT column_name, data_type "
                    f"FROM {TRINO_CATALOG}.information_schema.columns "
                    f"WHERE table_schema='{schema}' AND table_name='{table}' "
                    f"ORDER BY ordinal_position LIMIT 20"
                )
                col_str = ", ".join(f"{r[0]} ({r[1]})" for r in cur2.fetchall())
                lines.append(f"  iceberg.{schema}.{table}: {col_str}")
            except Exception:
                lines.append(f"  iceberg.{schema}.{table}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[ai_sql] schema fetch failed: {e}")
        return "Schema unavailable — use iceberg.<schema>.<table> notation."


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_messages(schema_ctx: str, question: str, context: Optional[str]) -> tuple[str, list]:
    system = f"""You are an expert SQL assistant for DataPond, an AI-Native Lakehouse.
The query engine is Trino. Tables are Apache Iceberg format.

{schema_ctx}

Rules:
- Always use fully-qualified table names: iceberg.<schema>.<table>
- Trino SQL dialect: double-quote identifiers, no backticks
- Return ONLY valid JSON with exactly two keys: "sql" and "explanation"
- "sql": runnable Trino SQL (no markdown, no code fences)
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
    }
    headers = {"Authorization": f"Bearer {cfg['master_key']}"} if cfg["master_key"] else {}
    with httpx.Client(timeout=httpx.Timeout(connect=3.0, read=60.0, write=10.0, pool=5.0)) as client:
        resp = client.post(f"{cfg['litellm_url']}/v1/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _parse_response(raw: str) -> dict:
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:-1])
    return json.loads(raw)


def _active_provider_is_external() -> Optional[bool]:
    """Best-effort: is the active model an external (egress) provider? None if unknown.

    Defense-in-depth for the local-only egress policy: registration already blocks
    external backends, but a model could be seeded directly into LiteLLM (e.g. via
    helm config), so we re-check the active model's provider at call time."""
    cfg = _cfg()
    if not cfg["litellm_url"]:
        return None
    try:
        headers = {"Authorization": f"Bearer {cfg['master_key']}"} if cfg["master_key"] else {}
        with httpx.Client(timeout=5) as client:
            r = client.get(f"{cfg['litellm_url']}/model/info", headers=headers)
            if r.status_code >= 400:
                return None
            for m in r.json().get("data", []):
                if m.get("model_name") == cfg["litellm_model"]:
                    model_str = (m.get("litellm_params") or {}).get("model", "")
                    return is_external_provider(provider_of_model(model_str))
    except Exception:
        return None
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
async def generate_sql(req: AskRequest):
    """Convert a natural language question to a Trino SQL query."""
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
    table_lines = "\n".join(
        f"-- SELECT * FROM {line.split(':')[0].strip()} LIMIT 10;"
        for line in schema_ctx.split("\n")
        if line.strip().startswith("iceberg.")
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
