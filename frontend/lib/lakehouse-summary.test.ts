import { test } from "node:test"
import assert from "node:assert/strict"
import { lakeCatalogCount, lastSyncAt, queriesSince, staleSourceCount } from "./lakehouse-summary.ts"

const NOW = Date.parse("2026-11-12T12:00:00Z")

test("only enabled lake catalogs count", () => {
  assert.equal(lakeCatalogCount([
    { kind: "glue", enabled: true }, { kind: "polaris", enabled: true },
    { kind: "trino_source", enabled: true }, { kind: "iceberg_rest", enabled: false },
  ]), 2)
})

test("a source is stale when never synced or older than 24h", () => {
  const sources = [
    { last_sync_at: null },
    { last_sync_at: "2026-11-12T08:00:00Z" },
    { last_sync_at: "2026-11-10T08:00:00Z" },
  ]
  assert.equal(staleSourceCount(sources, NOW), 2)
  assert.equal(lastSyncAt(sources), "2026-11-12T08:00:00Z")
  assert.equal(lastSyncAt([{ last_sync_at: null }]), null)
})

test("queries today are those at or after the start of the day", () => {
  const since = new Date("2026-11-12T00:00:00Z")
  assert.equal(queriesSince([{ created_at: "2026-11-12T01:00:00Z" }, { created_at: "2026-11-11T23:00:00Z" }, {}], since), 1)
})
