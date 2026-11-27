/** Axis ticks (./chart-format.ts): the live orders chart printed 45000000 and full ISO
 *  timestamps that ran into each other. */
import assert from "node:assert/strict"
import { test } from "node:test"
import { formatTick, formatTimeTick } from "./chart-format.ts"

test("large numbers are compact, small ones unchanged", () => {
  assert.equal(formatTick(45_000_000), "45M")
  assert.equal(formatTick(15_500), "15.5K")
  assert.equal(formatTick(950), "950")
  assert.equal(formatTick("North"), "North")
})

test("timestamps are shortened; midnight shows the date", () => {
  assert.equal(formatTimeTick("2026-05-20T00:23:00Z"), "05-20 00:23")
  assert.equal(formatTimeTick("2026-05-20 00:00:00"), "2026-05-20")
  assert.equal(formatTimeTick("2026-05-20"), "2026-05-20")
  assert.equal(formatTimeTick("Seoul"), "Seoul")
})
