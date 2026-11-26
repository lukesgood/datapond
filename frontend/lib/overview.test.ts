import { test } from "node:test"
import assert from "node:assert/strict"
import { agentProblems, attentionItems, catalogFact, getStartedSteps, lastCallLabel } from "./overview.ts"
import type { Agent } from "./agents.ts"
import type { OpsIssue } from "./ops-status.ts"

const now = new Date("2026-11-19T06:00:00Z")
const agent = (over: Partial<Agent>): Agent => ({
  id: "a1", username: "bot", display_name: "Bot", role: "viewer", is_active: true,
  created_at: "2026-11-01T00:00:00Z", keys: [], oauth_client: null, ...over,
})
const key = (expires_at: string | null, status = "active") => ({
  id: "k", name: "k", key_prefix: "dp_", status, scopes: [], expires_at, last_used_at: null, created_at: "2026-11-01T00:00:00Z",
})

test("agentProblems: no live key, expiring keys; disabled and healthy are skipped", () => {
  const out = agentProblems([
    agent({ id: "1" }),
    agent({ id: "2", keys: [key("2026-11-21T00:00:00Z")] }),
    agent({ id: "3", is_active: false }),
    agent({ id: "4", keys: [key(null)] }),
  ], now)
  assert.deepEqual(out.map(o => o.id), ["1", "2"])
  assert.match(out[1].text, /2026-11-21/)
})

test("attentionItems: urgent issues first, stale grouped, then agents", () => {
  const issues: OpsIssue[] = [
    { kind: "stale_source", connection_id: "c1", source: "Finance", hours: 50 },
    { kind: "catalog_unreachable", catalog: "polaris_lake" },
    { kind: "stale_source", connection_id: "c2", source: "FX", hours: null },
  ]
  const items = attentionItems(issues, [{ id: "a", name: "Bot", text: "x" }], new Set())
  assert.deepEqual(items.map(i => i.kind), ["issue", "stale", "agent"])
  const stale = items[1]
  assert.ok(stale.kind === "stale")
  assert.equal(stale.title, "2 sources missed a scheduled sync")
  assert.deepEqual(stale.sources.map(s => s.name), ["Finance", "FX"])
  assert.deepEqual(stale.connectionIds, ["c1", "c2"])
  assert.equal(stale.detail, "Finance, FX")
})

test("lastCallLabel: time today, date before, dash when missing", () => {
  const local = new Date(2026, 10, 19, 15, 8)
  assert.equal(lastCallLabel(local.toISOString(), new Date(2026, 10, 19, 18, 0)), "15:08")
  assert.equal(lastCallLabel(local.toISOString(), new Date(2026, 10, 20, 9, 0)), "Nov 19, 15:08")
  assert.equal(lastCallLabel(null, now), "—")
})

test("getStartedSteps: unknown steps omitted, all done hides the list", () => {
  const some = getStartedSteps({ sources: 2, queriedEver: false, chunks: null, agentsWithKey: null })
  assert.deepEqual(some.map(s => [s.key, s.done]), [["source", true], ["query", false]])
  assert.deepEqual(getStartedSteps({ sources: 1, queriedEver: true, chunks: 5, agentsWithKey: 1 }), [])
})

test("catalogFact", () => {
  assert.equal(catalogFact(2, 0), "2 lake catalogs, both reachable")
  assert.equal(catalogFact(3, 1), "3 lake catalogs, 1 unreachable")
  assert.equal(catalogFact(1, 0), "1 lake catalog, reachable")
  assert.equal(catalogFact(0, 0), "None enabled")
})
