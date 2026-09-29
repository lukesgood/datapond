import { test } from "node:test"
import assert from "node:assert/strict"
import { describeCheck } from "./source-check.ts"

const NOW = Date.parse("2026-09-30T12:00:00Z")

test("a source never checked says so, and is stale", () => {
  assert.deepEqual(describeCheck(null, NOW), { text: "never checked", stale: true })
  assert.deepEqual(describeCheck(undefined, NOW), { text: "never checked", stale: true })
  assert.deepEqual(describeCheck("not a date", NOW), { text: "never checked", stale: true })
})

test("the age is written in the largest whole unit", () => {
  assert.equal(describeCheck("2026-09-30T11:59:40Z", NOW).text, "checked just now")
  assert.equal(describeCheck("2026-09-30T11:45:00Z", NOW).text, "checked 15m ago")
  assert.equal(describeCheck("2026-09-30T09:00:00Z", NOW).text, "checked 3h ago")
  assert.equal(describeCheck("2026-09-27T12:00:00Z", NOW).text, "checked 3d ago")
})

test("a check older than a day is stale", () => {
  assert.equal(describeCheck("2026-09-29T13:00:00Z", NOW).stale, false)
  assert.equal(describeCheck("2026-09-29T11:00:00Z", NOW).stale, true)
})

test("a timestamp without a zone is read as UTC, the way the API writes it", () => {
  assert.equal(describeCheck("2026-09-30T09:00:00", NOW).text, "checked 3h ago")
  assert.equal(describeCheck("2026-09-30T18:00:00+09:00", NOW).text, "checked 3h ago")
})
