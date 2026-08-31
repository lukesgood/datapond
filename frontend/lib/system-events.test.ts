/** Presentation logic for Infrastructure → Events, run by `npm test` (node:test).
 *
 *  Split out of the component for the same reason markdown was: a wrong summary line
 *  passes `tsc` and `eslint` without complaint, and "3 times" versus "once" is the
 *  whole point of collapsing repeats into one row.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { causeNote, severityRank, summarizeOccurrences } from "./system-events.ts"

const T0 = "2026-08-27T02:00:00Z"
const T1 = "2026-08-27T06:00:00Z"

test("a single occurrence does not claim to repeat", () => {
  assert.equal(summarizeOccurrences(1, T0, T0), "once")
})

test("a repeat states how many times and over what span", () => {
  assert.equal(summarizeOccurrences(49, T0, T1), "49 times over 4h")
})

test("a repeat inside the same minute reports the count without a span", () => {
  assert.equal(summarizeOccurrences(3, T0, T0), "3 times")
})

test("a span under an hour reads in minutes", () => {
  assert.equal(summarizeOccurrences(2, T0, "2026-08-27T02:25:00Z"), "2 times over 25m")
})

test("a span over a day reads in days", () => {
  assert.equal(summarizeOccurrences(7, T0, "2026-08-29T02:00:00Z"), "7 times over 2d")
})

test("critical sorts above warning, warning above info", () => {
  assert.ok(severityRank("critical") < severityRank("warning"))
  assert.ok(severityRank("warning") < severityRank("info"))
})

test("an unknown severity sorts last rather than first", () => {
  assert.ok(severityRank("chartreuse") > severityRank("info"))
})

test("a reboot says the cause is not recorded", () => {
  // Nothing collects while the backend is down. The row has to say so, or its silence
  // reads as "nothing else happened".
  const note = causeNote({ kind: "node_reboot", details: { cause_recorded: false } })
  assert.ok(note && note.includes("not recorded"))
})

test("an event that carries its own cause gets no note", () => {
  assert.equal(causeNote({ kind: "oom_kill", details: { reason: "OOMKilling" } }), null)
})

test("a reboot whose cause was recorded gets no note", () => {
  assert.equal(causeNote({ kind: "node_reboot", details: { cause_recorded: true } }), null)
})
