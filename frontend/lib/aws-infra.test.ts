import { test } from "node:test"
import assert from "node:assert/strict"
import {
  acu, auroraIdle, capacityProblem, money, missingSentence, niceMax, scheduleDelta, scheduleProblem,
  share, stopsToday, weeklyHours,
} from "./aws-infra.ts"

const WEEK = ["MON", "TUE", "WED", "THU", "FRI"]

test("weekly hours", () => {
  assert.equal(weeklyHours(WEEK, "07:30", "18:00"), 52.5)
  assert.equal(weeklyHours(WEEK, "07:30", "18:00", false), 168)
  assert.equal(weeklyHours(WEEK, "18:00", "07:30"), 0)
})

test("schedule problems", () => {
  assert.equal(scheduleProblem([], "07:00", "18:00"), "Pick at least one day.")
  assert.equal(scheduleProblem(WEEK, "7", "18:00"), "Start is not a time (HH:MM).")
  assert.equal(scheduleProblem(WEEK, "18:00", "07:00"), "Stop must be later in the day than start.")
  assert.equal(scheduleProblem(WEEK, "07:00", "18:00"), null)
})

test("schedule delta and aurora idle", () => {
  // 24/7 instead of 52.5 h at $0.05/h
  assert.equal(scheduleDelta(52.5, 168, 0.05), 25.09)
  assert.equal(scheduleDelta(52.5, 168, null), null)
  assert.equal(auroraIdle(0.5), 43.8)
  assert.equal(auroraIdle(0), 0)
  assert.equal(capacityProblem(2, 2), "The maximum must be larger than the minimum.")
  assert.equal(capacityProblem(0.5, 4), null)
})

test("stops today only on a scheduled day", () => {
  const s = { known: true, enabled: true, days: ["MON", "TUE", "WED", "THU", "FRI"] as never, stop: "18:00", tz: "Asia/Seoul" }
  assert.equal(stopsToday(s, new Date("2026-11-20T03:00:00Z")), "18:00 KST")   // Friday in Seoul
  assert.equal(stopsToday(s, new Date("2026-11-21T03:00:00Z")), null)           // Saturday
  assert.equal(stopsToday({ ...s, enabled: false }, new Date("2026-11-20T03:00:00Z")), null)
})

test("formatting", () => {
  assert.equal(money(64.6), "$64.60")
  assert.equal(money(1234.5, 0), "$1,235")
  assert.equal(money(null), "—")
  assert.equal(acu(1.025462962962963), "1.03")
  assert.equal(acu(4), "4")
  assert.equal(acu(null), "—")
  assert.equal(niceMax([3.2, 4.1]), 5)
  assert.equal(niceMax([]), 1)
  assert.equal(share(34.55, 64.6), 53)
  assert.equal(missingSentence([]), null)
  assert.match(missingSentence(["a", "b", "c", "d", "e", "f"]) ?? "", /a, b, c, d and 2 more/)
})
