// Snippets shown on a collection's "Use from app" tab. Pure strings, tested here.
//
// Collection names are user-controlled (CollectionCreate.name is an unconstrained str,
// only `.strip()`-ed server-side) and these snippets are copy-pasted straight into a
// terminal, so every builder below must escape the name rather than concatenate it in.

// Wrap JSON text in single quotes the POSIX-safe way: close the quote, emit an escaped
// literal quote, reopen the quote, for every `'` in the text.
const shq = (s: string) => "'" + s.replace(/'/g, "'\\''") + "'"

// JSON string escaping (\", \\, control-char escapes) is valid Python string-literal
// syntax for the characters that matter here, so a JSON-encoded string is safe to splice
// into a Python source literal as-is.
const pyStr = (s: string) => JSON.stringify(s)

export function snippetBase(origin: string): string {
  return origin || "https://your-deployment"
}

export function curlSearch(base: string, collection: string): string {
  const body = JSON.stringify({ collection, query: "your question", k: 5 })
  return `curl -sX POST ${base}/api/ai/search \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d ${shq(body)}`
}

export function curlRag(base: string, collection: string): string {
  const body = JSON.stringify({ collection, question: "your question", k: 5 })
  return `curl -sX POST ${base}/api/ai/rag \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d ${shq(body)}`
}

export function pythonRag(base: string, collection: string): string {
  return `import os
import requests

r = requests.post(
    "${base}/api/ai/rag",
    headers={"Authorization": f"Bearer {os.environ['DATAPOND_KEY']}"},
    json={"collection": ${pyStr(collection)}, "question": "your question", "k": 5},
    timeout=60,
)
r.raise_for_status()
body = r.json()
print(body["answer"])
for i, c in enumerate(body["citations"], 1):
    print(f"[{i}] {c['source']} (chunk {c['chunk_index']})")`
}
