import { test } from "node:test"
import assert from "node:assert/strict"
import { failedSince, filterSources, isStale, parseSourceFilter, sourceCounts, staleReasons } from "./source-freshness.ts"

const NOW = Date.parse("2026-11-30T03:00:00Z")
const src = (id: string, status: string, overdue: string | null = null, extra = {}) =>
  ({ id, status, last_sync_at: null, overdue_since: overdue, ...extra })
const MISSED = "2026-11-29T23:00:00Z"

test("stale is the server's missed run, and only for an active source", () => {
  assert.equal(isStale(src("a", "active", MISSED)), true)
  assert.equal(isStale(src("m", "active")), false)                 // synced by hand: never stale
  assert.equal(isStale(src("p", "paused", MISSED)), false)
  assert.equal(isStale(src("e", "error", MISSED)), false)          // shown as Error, not twice
})

test("filters and counts", () => {
  const list = [src("a", "active"), src("b", "active", MISSED), src("p", "paused"), src("e", "error")]
  assert.deepEqual(filterSources(list, "all").map((s) => s.id), ["a", "b", "p", "e"])
  assert.deepEqual(filterSources(list, "stale").map((s) => s.id), ["b"])
  assert.deepEqual(filterSources(list, "paused").map((s) => s.id), ["p"])
  assert.deepEqual(sourceCounts(list), { all: 4, stale: 1, paused: 1 })
})

test("the filter comes from ?filter= and anything else is all", () => {
  assert.equal(parseSourceFilter("?filter=stale"), "stale")
  assert.equal(parseSourceFilter("?filter=paused&x=1"), "paused")
  assert.equal(parseSourceFilter("?filter=nope"), "all")
  assert.equal(parseSourceFilter(""), "all")
})

test("a stale source says which run it missed, how old its data is, and what happened last", () => {
  const s = src("b", "active", MISSED, {
    schedule: "0 8 * * 1-5", last_success_at: "2026-11-26T23:01:00Z",
    last_run_at: "2026-11-28T01:00:00Z", last_run_status: "failed",
  })
  const lines = staleReasons(s, NOW)
  assert.match(lines[0], /^Missed the scheduled run due .+\(.+\)\.$/)
  assert.match(lines[1], /^Data is from the last successful sync, /)
  assert.match(lines[2], /did not finish: failed\.$/)
  assert.match(lines.at(-1)!, /scheduler is off/)
  assert.deepEqual(staleReasons(src("m", "active"), NOW), [])
  assert.match(staleReasons(src("n", "active", MISSED), NOW)[1], /never synced successfully/)
})

test("a newer run that did not succeed is called out; an older one is not", () => {
  const base = { status: "active", last_sync_at: null, last_success_at: "2026-11-27T00:00:00Z" }
  assert.equal(failedSince({ ...base, last_run_at: "2026-11-28T00:00:00Z", last_run_status: "failed" }), true)
  assert.equal(failedSince({ ...base, last_run_at: "2026-11-26T00:00:00Z", last_run_status: "failed" }), false)
  assert.equal(failedSince({ ...base, last_run_at: "2026-11-28T00:00:00Z", last_run_status: "success" }), false)
})
