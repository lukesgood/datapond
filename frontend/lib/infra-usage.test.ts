import test from "node:test"
import assert from "node:assert/strict"
import { formatUsage } from "./infra-usage.ts"

test("usage cell", () => {
  assert.equal(formatUsage(null, null), "—")
  assert.equal(formatUsage(undefined, undefined), "—")
  assert.equal(formatUsage(26, 972), "26m · 972 Mi")
  assert.equal(formatUsage(1500, 2150), "1.5 cores · 2.1 Gi")
  assert.equal(formatUsage(0, null), "0m · —")
})
