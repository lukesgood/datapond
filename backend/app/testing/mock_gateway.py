"""The mock model behind an OpenAI-compatible HTTP surface.

Run with `python -m app.testing.mock_gateway`; point LITELLM_URL at it. The backend
speaks to its model gateway through three paths and this answers all three, so nothing
in the application needs to know it is talking to a fake.

Refuses to start unless MOCK_MODEL_PROVIDER=true is set. A stand-in that answers real
traffic because someone left an environment variable pointing at it is worse than no
stand-in: every answer would be wrong and everything would look fine.
"""
import os
import sys

from fastapi import FastAPI
from pydantic import BaseModel

from app.testing.mock_model import chat_completion, embedding_vector, rerank

app = FastAPI(title="DataPond mock model provider")

EMBED_DIM = int(os.getenv("AI_EMBED_DIM", "1024"))


class ChatRequest(BaseModel):
    model: str = "mock"
    messages: list = []
    max_tokens: int | None = None
    user: str | None = None
    metadata: dict | None = None
    tools: list | None = None
    tool_choice: str | None = None


class EmbedRequest(BaseModel):
    model: str = "mock"
    input: list | str = ""
    user: str | None = None
    metadata: dict | None = None


class RerankRequest(BaseModel):
    model: str = "mock"
    query: str = ""
    documents: list = []
    top_n: int = 5
    metadata: dict | None = None


@app.get("/health/readiness")
async def readiness():
    return {"status": "ok", "mock": True}


@app.post("/v1/chat/completions")
async def chat(body: ChatRequest):
    # No tool calls, ever. A mock that invented one would send the assistant down a
    # path nobody wrote, and the acceptance suite would be testing the mock.
    return chat_completion(body.messages, model=body.model)


@app.post("/v1/embeddings")
async def embeddings(body: EmbedRequest):
    items = body.input if isinstance(body.input, list) else [body.input]
    return {
        "object": "list",
        "model": body.model,
        "data": [{"object": "embedding", "index": i,
                  "embedding": embedding_vector(str(t), EMBED_DIM)}
                 for i, t in enumerate(items)],
        "usage": {"prompt_tokens": sum(len(str(t).split()) for t in items),
                  "total_tokens": sum(len(str(t).split()) for t in items)},
    }


@app.post("/v1/rerank")
async def rerank_endpoint(body: RerankRequest):
    return rerank(body.query, [str(d) for d in body.documents], body.top_n)


@app.get("/model/info")
async def model_info():
    return {"data": [{"model_name": name,
                      "litellm_params": {"model": f"mock/{name}"},
                      "model_info": {"id": f"mock-{name}"}}
                     for name in ("default", "chat", "embed")]}


@app.get("/spend/logs")
async def spend_logs():
    """Empty rather than absent. Usage reporting reads this; a 404 would surface as a
    broken gateway when the truth is that a mock costs nothing."""
    return []


def main() -> int:
    if os.getenv("MOCK_MODEL_PROVIDER", "").lower() not in ("1", "true", "yes"):
        print("refusing to start: set MOCK_MODEL_PROVIDER=true", file=sys.stderr)
        return 2
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "4000")), log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
