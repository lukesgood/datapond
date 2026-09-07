// Snippets shown on a collection's "Use from app" tab. Pure strings, tested here.

export function snippetBase(origin: string): string {
  return origin || "https://your-deployment"
}

export function curlSearch(base: string, collection: string): string {
  return `curl -sX POST ${base}/api/ai/search \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"collection": "${collection}", "query": "your question", "k": 5}'`
}

export function curlRag(base: string, collection: string): string {
  return `curl -sX POST ${base}/api/ai/rag \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"collection": "${collection}", "question": "your question", "k": 5}'`
}

export function pythonRag(base: string, collection: string): string {
  return `import os
import requests

r = requests.post(
    "${base}/api/ai/rag",
    headers={"Authorization": f"Bearer {os.environ['DATAPOND_KEY']}"},
    json={"collection": "${collection}", "question": "your question", "k": 5},
    timeout=60,
)
r.raise_for_status()
body = r.json()
print(body["answer"])
for i, c in enumerate(body["citations"], 1):
    print(f"[{i}] {c['source']} (chunk {c['chunk_index']})")`
}
