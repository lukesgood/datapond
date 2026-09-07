import assert from "node:assert/strict"
import { test } from "node:test"
import { curlRag, curlSearch, pythonRag, snippetBase } from "./app-snippets.ts"

test("base falls back to a placeholder when origin is unknown", () => {
  assert.equal(snippetBase(""), "https://your-deployment")
  assert.equal(snippetBase("https://dp.example.com"), "https://dp.example.com")
})

test("curl snippets carry the collection, the key header and the right path", () => {
  const s = curlSearch("https://dp", "faq")
  assert.match(s, /\/api\/ai\/search/)
  assert.match(s, /"collection": "faq"/)
  assert.match(s, /Authorization: Bearer \$DATAPOND_KEY/)
  assert.match(s, /-H "Content-Type: application\/json" \\/)
  assert.match(curlRag("https://dp", "faq"), /\/api\/ai\/rag/)
  assert.match(curlRag("https://dp", "faq"), /-H "Content-Type: application\/json" \\/)
})

test("python snippet uses requests and the collection name", () => {
  const p = pythonRag("https://dp", "faq")
  assert.match(p, /import requests/)
  assert.match(p, /"collection": "faq"/)
  assert.match(p, /citations/)
})
