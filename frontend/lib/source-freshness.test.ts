import { test } from "node:test"
import assert from "node:assert/strict"
import { filterSources, isStale, parseSourceFilter, sourceCounts } from "./source-freshness.ts"

const NOW = Date.parse("2026-11-16T12:00:00Z")
const ago = (h: number) => new Date(NOW - h * 3600_000).toISOString()
const src = (id: string, status: string, last: string | null) => ({ id, status, last_sync_at: last })

test("only an active source can be stale; paused, pending and error sources never are", () => {
  assert.equal(isStale(src("a", "active", ago(25)), NOW), true)
  assert.equal(isStale(src("a", "active", ago(23)), NOW), false)
  assert.equal(isStale(src("a", "active", null), NOW), true)       // never synced
  assert.equal(isStale(src("p", "paused", ago(500)), NOW), false)
  assert.equal(isStale(src("q", "pending", null), NOW), false)
  assert.equal(isStale(src("e", "error", ago(500)), NOW), false)   // shown as Error, not twice
})

test("filters and counts", () => {
  const list = [src("a", "active", ago(1)), src("b", "active", ago(30)), src("p", "paused", ago(300)), src("e", "error", ago(2))]
  assert.deepEqual(filterSources(list, "all", NOW).map((s) => s.id), ["a", "b", "p", "e"])
  assert.deepEqual(filterSources(list, "stale", NOW).map((s) => s.id), ["b"])
  assert.deepEqual(filterSources(list, "paused", NOW).map((s) => s.id), ["p"])
  assert.deepEqual(sourceCounts(list, NOW), { all: 4, stale: 1, paused: 1 })
})

test("the filter comes from ?filter= and anything else is all", () => {
  assert.equal(parseSourceFilter("?filter=stale"), "stale")
  assert.equal(parseSourceFilter("?filter=paused&x=1"), "paused")
  assert.equal(parseSourceFilter("?filter=nope"), "all")
  assert.equal(parseSourceFilter(""), "all")
})
