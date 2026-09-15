import { test } from "node:test"
import assert from "node:assert/strict"
import { activitySentence, activityTotals, actorsFrom, platformStatus, spendFromBudgetAlerts, startOfLocalDay } from "./dashboard-activity.ts"

test("today starts at local midnight", () => {
  const d = startOfLocalDay(new Date(2026, 8, 15, 14, 30, 12))
  assert.deepEqual([d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes()], [2026, 8, 15, 0, 0])
})

test("a summary payload yields its actors; anything else is not a measurement", () => {
  assert.deepEqual(actorsFrom({ by_actor: [{ actor_username: "svc", actor_kind: "service", calls: 2 }] })?.length, 1)
  assert.equal(actorsFrom({ unavailable: "no db" }), null)
  assert.equal(actorsFrom(null), null)
})

test("totals add calls, errors, degraded, and masked PII across callers", () => {
  const t = activityTotals([
    { actor_username: "svc-bot", actor_kind: "service", calls: 10, error: 1, degraded: 2, pii_masked: 3 },
    { actor_username: "alice", actor_kind: "human", calls: 2, error: 0, degraded: 0, pii_masked: 1 },
  ])
  assert.deepEqual(t, { calls: 12, callers: 2, errors: 1, degraded: 2, piiMasked: 4 })
})

test("the sentence names what happened, and only what happened", () => {
  assert.equal(activitySentence({ calls: 0, callers: 0, errors: 0, degraded: 0, piiMasked: 0 }), "No tool calls yet today.")
  assert.equal(activitySentence({ calls: 1, callers: 1, errors: 0, degraded: 0, piiMasked: 0 }), "1 tool call from 1 caller today.")
  assert.equal(activitySentence({ calls: 1200, callers: 3, errors: 2, degraded: 0, piiMasked: 1 }),
    "1,200 tool calls from 3 callers today · 2 errors · 1 PII value masked.")
})

test("adapters are counted as configured, and unhealthy workloads are named", () => {
  const p = platformStatus([
    { name: "backend", status: "healthy" }, { name: "valkey", status: "unknown" },
    { name: "aurora", status: "managed" }, { name: "litellm", status: "unhealthy" },
  ])
  assert.deepEqual(p, { healthy: 1, observed: 3, configured: 1, attention: ["litellm", "valkey"] })
})

test("model spend is the gateway total, and an unread gateway is not zero", () => {
  assert.deepEqual(spendFromBudgetAlerts({ spend_total: 0.299768, global: null, alerts: [] }), { total_spend: 0.299768 })
  assert.deepEqual(spendFromBudgetAlerts({ spend_total: 0 }), { total_spend: 0 })
  assert.deepEqual(spendFromBudgetAlerts({ spend_total: null }), { unavailable: "gateway spend could not be read" })
  assert.deepEqual(spendFromBudgetAlerts(undefined), { unavailable: "gateway spend could not be read" })
})
