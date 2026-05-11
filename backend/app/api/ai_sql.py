"""
AI SQL Assistant — natural language → SQL.

Provider priority (automatic fallback chain):
  1. LiteLLM internal proxy  (LITELLM_URL — Ollama / any configured model)
  2. AWS Bedrock direct       (AWS_BEDROCK_REGION set, LiteLLM unavailable)
  3. Anthropic API direct     (ANTHROPIC_API_KEY set, both above unavailable)
  4. Graceful fallback        — schema-aware SQL template (no AI)

LiteLLM exposes an OpenAI-compatible /v1/chat/completions endpoint, so
providers 1-3 all use the same message format; only the HTTP target differs.
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

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Provider configuration (read dynamically — settings API updates os.environ) ─
def _cfg():
    """Read provider config fresh from env each call so Settings UI changes apply immediately."""
    return {
        "litellm_url":            os.getenv("LITELLM_URL", "http://litellm.datapond.svc.cluster.local:4000"),
        "litellm_model":          os.getenv("LITELLM_MODEL", "default"),
        "aws_bedrock_region":     os.getenv("AWS_BEDROCK_REGION", ""),
        "aws_access_key_id":      os.getenv("AWS_ACCESS_KEY_ID", ""),
        "aws_secret_access_key":  os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        "bedrock_model_id":       os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
        "anthropic_api_key":      os.getenv("ANTHROPIC_API_KEY", ""),
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
    """Call LiteLLM proxy (OpenAI-compatible).  Connect timeout: 3 s."""
    cfg = _cfg()
    payload = {
        "model": cfg["litellm_model"],
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": 1024,
    }
    with httpx.Client(timeout=httpx.Timeout(connect=3.0, read=60.0, write=10.0, pool=5.0)) as client:
        resp = client.post(f"{cfg['litellm_url']}/v1/chat/completions", json=payload)
        resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _call_bedrock(system: str, messages: list) -> str:
    """Call AWS Bedrock directly (Anthropic Messages API via boto3)."""
    import boto3
    cfg = _cfg()

    kwargs: dict = {"region_name": cfg["aws_bedrock_region"]}
    if cfg["aws_access_key_id"] and cfg["aws_secret_access_key"]:
        kwargs["aws_access_key_id"] = cfg["aws_access_key_id"]
        kwargs["aws_secret_access_key"] = cfg["aws_secret_access_key"]

    client = boto3.client("bedrock-runtime", **kwargs)
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": system,
        "messages": messages,
    })
    resp = client.invoke_model(
        modelId=cfg["bedrock_model_id"],
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    result = json.loads(resp["body"].read())
    return result["content"][0]["text"].strip()


def _call_anthropic(system: str, messages: list) -> str:
    """Call Anthropic API directly."""
    import anthropic
    cfg = _cfg()
    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"])
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return msg.content[0].text.strip()


def _parse_response(raw: str) -> dict:
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:-1])
    return json.loads(raw)


# ── Request / response models ─────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    context: Optional[str] = None


class AskResponse(BaseModel):
    sql: str
    explanation: str
    has_ai: bool
    provider: str = "none"


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/ai/sql", response_model=AskResponse)
async def generate_sql(req: AskRequest):
    """Convert a natural language question to a Trino SQL query."""
    schema_ctx = await asyncio.to_thread(_get_schema_context)
    system, messages = _build_messages(schema_ctx, req.question, req.context)

    cfg = _cfg()

    # ── 1. LiteLLM proxy (Ollama / any configured model) ─────────────────────
    try:
        raw = await asyncio.to_thread(_call_litellm, system, messages)
        data = _parse_response(raw)
        return AskResponse(
            sql=data["sql"].strip(),
            explanation=data.get("explanation", ""),
            has_ai=True,
            provider=f"litellm:{cfg['litellm_model']}",
        )
    except Exception as e:
        logger.warning(f"[ai_sql] LiteLLM unavailable: {e}")

    # ── 2. AWS Bedrock direct ─────────────────────────────────────────────────
    if cfg["aws_bedrock_region"]:
        try:
            raw = await asyncio.to_thread(_call_bedrock, system, messages)
            data = _parse_response(raw)
            return AskResponse(
                sql=data["sql"].strip(),
                explanation=data.get("explanation", ""),
                has_ai=True,
                provider=f"bedrock:{cfg['bedrock_model_id']}",
            )
        except Exception as e:
            logger.error(f"[ai_sql] Bedrock failed: {e}")

    # ── 3. Anthropic API direct ───────────────────────────────────────────────
    if cfg["anthropic_api_key"]:
        try:
            raw = await asyncio.to_thread(_call_anthropic, system, messages)
            data = _parse_response(raw)
            return AskResponse(
                sql=data["sql"].strip(),
                explanation=data.get("explanation", ""),
                has_ai=True,
                provider="anthropic",
            )
        except Exception as e:
            logger.error(f"[ai_sql] Anthropic failed: {e}")

    # ── 4. Graceful fallback — schema-aware SQL template ──────────────────────
    table_lines = "\n".join(
        f"-- SELECT * FROM {line.split(':')[0].strip()} LIMIT 10;"
        for line in schema_ctx.split("\n")
        if line.strip().startswith("iceberg.")
    )[:800]

    return AskResponse(
        sql=(
            "-- AI SQL Assistant\n"
            "-- No AI provider reachable. Configure one of:\n"
            "--   LITELLM_URL          (LiteLLM proxy — default, on-prem/Ollama)\n"
            "--   AWS_BEDROCK_REGION   (+ IAM credentials)\n"
            "--   ANTHROPIC_API_KEY    (direct Anthropic API)\n"
            "--\n"
            "-- Available tables:\n"
            f"{table_lines}"
        ),
        explanation="No AI provider reachable. Set LITELLM_URL, AWS_BEDROCK_REGION, or ANTHROPIC_API_KEY.",
        has_ai=False,
        provider="none",
    )
