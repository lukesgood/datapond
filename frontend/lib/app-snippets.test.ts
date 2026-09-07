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
  assert.match(s, /"collection":"faq"/)
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

// Undo the shell single-quote wrapping applied by the curl builders: take the text
// between `-d '` and the final `'`, then replace every `'\''` with `'`.
function unshellSingleQuoted(snippet: string): string {
  const start = snippet.indexOf("-d '") + "-d '".length
  const end = snippet.lastIndexOf("'")
  const body = snippet.slice(start, end)
  return body.replace(/'\\''/g, "'")
}

const HOSTILE_NAME = `Bob's "Q1" docs\\path`

test("a hostile collection name cannot break curl's shell quoting", () => {
  for (const snippet of [curlSearch("https://dp", HOSTILE_NAME), curlRag("https://dp", HOSTILE_NAME)]) {
    const jsonText = unshellSingleQuoted(snippet)
    const parsed = JSON.parse(jsonText)
    assert.equal(parsed.collection, "Bob's \"Q1\" docs\\path")
  }
})

test("a hostile collection name is valid Python string syntax in pythonRag", () => {
  const p = pythonRag("https://dp", HOSTILE_NAME)
  const expected = '"collection": "Bob\'s \\"Q1\\" docs\\\\path"'
  assert.ok(p.includes(expected), `expected pythonRag output to include ${JSON.stringify(expected)}, got:\n${p}`)
})
