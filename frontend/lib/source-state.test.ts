import { test } from "node:test"
import assert from "node:assert/strict"
import { readJson, sourceStatus, statusText } from "./source-state.ts"
import { buildSchedule, matchCron } from "./schedule.ts"

test("sourceStatus: nothing yet and loading is loading", () => {
  assert.equal(sourceStatus({ loading: true, error: null, empty: true }), "loading")
})

test("sourceStatus: a failure with nothing to show is an error, never empty", () => {
  assert.equal(sourceStatus({ loading: false, error: "boom", empty: true }), "error")
})

test("sourceStatus: a refresh over data on screen keeps it", () => {
  assert.equal(sourceStatus({ loading: true, error: null, empty: false }), "ready")
})

test("sourceStatus: loaded and empty is empty", () => {
  assert.equal(sourceStatus({ loading: false, error: null, empty: true }), "empty")
})

test("readJson throws the API detail, else the status in words", async () => {
  await assert.rejects(readJson(new Response(JSON.stringify({ detail: "No catalog" }), { status: 400 })), /No catalog/)
  await assert.rejects(readJson(new Response("oops", { status: 502 })), /server failed \(HTTP 502\)/)
  assert.deepEqual(await readJson(new Response(JSON.stringify({ a: 1 }))), { a: 1 })
  assert.match(statusText(403), /role/)
})

test("matchCron: picker crons round-trip; hand-written ones are null", () => {
  assert.deepEqual(matchCron("0 5 * * *"), { freqId: "daily", hour: 5 })
  assert.deepEqual(matchCron("*/15 * * * *"), { freqId: "15min", hour: 2 })
  assert.equal(matchCron("30 4 * * 2"), null)
  assert.equal(matchCron(null), null)
  assert.equal(buildSchedule("weekly", 7), "0 7 * * 1")
  assert.equal(buildSchedule("manual", 7), null)
})
