import { test } from "node:test"
import assert from "node:assert/strict"
import {
  healthCounts, healthDetail, healthDotClass, parseCatalogHealth, type CatalogHealth,
} from "./catalog-health.ts"

const OK: CatalogHealth = {
  name: "iceberg", kind: "polaris", is_default: true, status: "reachable", error: null, latency_ms: 42,
}
const BAD: CatalogHealth = {
  name: "lake", kind: "iceberg_rest", is_default: false, status: "error",
  error: "No answer within 5s.", latency_ms: null,
}

test("a response that is not the expected shape is no catalogs, never a crash", () => {
  assert.deepEqual(parseCatalogHealth(null), [])
  assert.deepEqual(parseCatalogHealth({ detail: "Forbidden" }), [])
  assert.deepEqual(parseCatalogHealth({ catalogs: "x" }), [])
  assert.deepEqual(parseCatalogHealth({ catalogs: [OK, { name: 1 }, { name: "x", status: "odd" }, BAD] }), [OK, BAD])
})

test("the dot and the line say reachable with latency, or the error", () => {
  assert.match(healthDotClass(OK), /dp-good/)
  assert.match(healthDotClass(BAD), /dp-bad/)
  assert.equal(healthDetail(OK), "Reachable · 42 ms")
  assert.equal(healthDetail({ ...OK, latency_ms: null }), "Reachable")
  assert.equal(healthDetail(BAD), "No answer within 5s.")
  assert.equal(healthDetail({ ...BAD, error: null }), "The catalog did not answer.")
})

test("counts", () => {
  assert.deepEqual(healthCounts([OK, BAD, OK]), { reachable: 2, error: 1 })
  assert.deepEqual(healthCounts([]), { reachable: 0, error: 0 })
})
