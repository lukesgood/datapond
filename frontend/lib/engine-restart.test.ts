import { test } from "node:test"
import assert from "node:assert/strict"
import { engineBanner, parseEngineStatus, pollDelayMs } from "./engine-restart.ts"

test("restarting shows the one-minute notice and keeps polling", () => {
  const s = { engine: "trino" as const, ready: false, restarting: true }
  assert.equal(engineBanner(s)?.tone, "info")
  assert.equal(engineBanner(s)?.text,
    "Query engine restarting (~1 min) — the new source catalog appears when it is back.")
  assert.equal(pollDelayMs(s), 3000)
})

test("ready shows nothing and stops polling", () => {
  const s = { engine: "trino" as const, ready: true, restarting: false }
  assert.equal(engineBanner(s), null)
  assert.equal(pollDelayMs(s), 0)
})

test("not ready and not restarting is a warning, and polling stops", () => {
  const s = { engine: "trino" as const, ready: false, restarting: false }
  assert.equal(engineBanner(s)?.tone, "warn")
  assert.equal(engineBanner(s)?.text,
    "Query engine is not ready; sources cannot be browsed or synced until it is.")
  assert.equal(pollDelayMs(s), 0)
})

test("no engine on this profile shows nothing", () => {
  assert.equal(engineBanner({ engine: "none", ready: false, restarting: false }), null)
  assert.equal(engineBanner(null), null)
  assert.equal(pollDelayMs(null), 0)
})

test("an unreadable status warns instead of lying", () => {
  const b = engineBanner({ engine: "trino", ready: null, restarting: null, error: "403" })
  assert.equal(b?.tone, "warn")
  assert.match(b?.text ?? "", /^Query engine status unavailable/)
})

test("a response that is not a status is null, never a crash", () => {
  assert.equal(parseEngineStatus(null), null)
  assert.equal(parseEngineStatus({ detail: "Forbidden" }), null)
  assert.deepEqual(parseEngineStatus({ engine: "trino", ready: true, restarting: false, restarted_at: null }),
    { engine: "trino", ready: true, restarting: false, restarted_at: null, error: undefined })
  assert.equal(parseEngineStatus({ engine: "trino", ready: null, restarting: null, error: "Forbidden" })?.error, "Forbidden")
})
