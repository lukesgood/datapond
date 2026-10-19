import { test } from "node:test"
import assert from "node:assert/strict"
import { callerOptions, toolCallsUrl, isProblem } from "./tool-calls.ts"

test("caller options come from the summary, one per caller id, agents marked", () => {
  const opts = callerOptions([
    { actor_id: "a", actor_username: "svc-hr", actor_kind: "service", calls: 3 },
    { actor_id: "b", actor_username: "luke", actor_kind: "human", calls: 1 },
    { actor_id: null, actor_username: "anonymous", actor_kind: "human", calls: 2 },
    { actor_id: "a", actor_username: "svc-hr", actor_kind: "service", calls: 1 },
  ])
  assert.deepEqual(opts, [
    { id: "a", label: "svc-hr (agent)" },
    { id: "b", label: "luke" },
  ])
})

test("the list URL carries the window and, when chosen, the caller", () => {
  assert.equal(toolCallsUrl("2026-10-19T00:00:00.000Z", ""),
    "/api/audit/tool-calls?since=2026-10-19T00%3A00%3A00.000Z&limit=200")
  assert.equal(toolCallsUrl("2026-10-19T00:00:00.000Z", "a b"),
    "/api/audit/tool-calls?since=2026-10-19T00%3A00%3A00.000Z&limit=200&actor_id=a+b")
})

test("refused and error calls are the ones to look at", () => {
  assert.deepEqual(["ok", "degraded", "error", "refused"].map(isProblem), [false, false, true, true])
})
