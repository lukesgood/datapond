import test from "node:test"
import assert from "node:assert/strict"
import { attrFromText, attrRows, attrToText, buildAttributes, grantWarning, revokeWarning, agentStatus, joinAgentRows, lastUsed, viaLabel, type Agent, type AgentKey } from "./agents.ts"

const NOW = new Date("2026-10-16T00:00:00Z")
const DAY = 86_400_000
const iso = (offsetDays: number) => new Date(NOW.getTime() + offsetDays * DAY).toISOString()

const key = (over: Partial<AgentKey> = {}): AgentKey => ({
  id: "k1", name: "k", key_prefix: "dp_sk_ab", status: "active", scopes: [],
  expires_at: null, last_used_at: null, created_at: iso(-30), ...over,
})
const agent = (over: Partial<Agent> = {}): Agent => ({
  id: "a1", username: "svc-a", display_name: "A", role: "ai_engineer", is_active: true,
  created_at: iso(-30), keys: [key()], oauth_client: null, ...over,
})

test("status: disabled wins over everything", () => {
  assert.deepEqual(agentStatus(agent({ is_active: false }), NOW), { label: "disabled", tone: "bad" })
})

test("status: no keys, only revoked keys, or only expired keys read as no active key", () => {
  assert.deepEqual(agentStatus(agent({ keys: [] }), NOW), { label: "no active key", tone: "warn" })
  assert.equal(agentStatus(agent({ keys: [key({ status: "revoked" })] }), NOW).label, "no active key")
  assert.equal(agentStatus(agent({ keys: [key({ expires_at: iso(-1) })] }), NOW).label, "no active key")
})

test("status: an active key expiring within 14 days is flagged, later is not", () => {
  assert.deepEqual(agentStatus(agent({ keys: [key({ expires_at: iso(14) })] }), NOW), { label: "key expiring", tone: "warn" })
  assert.equal(agentStatus(agent({ keys: [key({ expires_at: iso(15) })] }), NOW).label, "active")
  assert.equal(agentStatus(agent(), NOW).label, "active")
})

test("status: a healthy key outweighs an expiring one", () => {
  const keys = [key({ id: "a", expires_at: iso(3) }), key({ id: "b", expires_at: iso(60) })]
  assert.deepEqual(agentStatus(agent({ keys }), NOW), { label: "active", tone: "ok" })
})

test("last used is the latest across keys, null when never used", () => {
  assert.equal(lastUsed(agent()), null)
  const keys = [key({ last_used_at: iso(-5) }), key({ id: "b", last_used_at: iso(-1) }), key({ id: "c" })]
  assert.equal(lastUsed(agent({ keys })), iso(-1))
})

test("joinAgentRows joins calls and spend by agent id", () => {
  const rows = joinAgentRows(
    [agent(), agent({ id: "a2" })],
    [{ actor_id: "a1", calls: 7, refused: 2 }, { actor_id: null, calls: 1, refused: 0 }],
    [{ user_id: "a1", spend: 1.5, max_budget: 5 }],
  )
  assert.deepEqual([rows[0].calls24h, rows[0].refused24h, rows[0].spend, rows[0].cap], [7, 2, 1.5, 5])
  // Present sources, agent absent: it made no calls and has spent nothing.
  assert.deepEqual([rows[1].calls24h, rows[1].refused24h, rows[1].spend, rows[1].cap], [0, 0, 0, null])
})

test("joinAgentRows tolerates missing sources", () => {
  const rows = joinAgentRows([agent()], null, null)
  assert.equal(rows.length, 1)
  assert.deepEqual([rows[0].calls24h, rows[0].refused24h, rows[0].spend, rows[0].cap], [null, null, null, null])
  const onlySummary = joinAgentRows([agent()], [{ actor_id: "a1", calls: 3, refused: 0 }], null)
  assert.deepEqual([onlySummary[0].calls24h, onlySummary[0].spend], [3, null])
})

test("via labels", () => {
  assert.equal(viaLabel("user", "ai_engineer"), "granted to this agent")
  assert.equal(viaLabel("role", "ai_engineer"), "granted to role ai_engineer")
  assert.equal(viaLabel("open", "ai_engineer"), "open to every caller")
  assert.equal(viaLabel(null, "ai_engineer"), "not granted")
})

test("grantWarning: only an open catalog warns", () => {
  assert.match(grantWarning("hr", false)!, /hr is open to every caller\. Granting it to this agent restricts it: every other caller without a grant loses access\./)
  assert.equal(grantWarning("hr", true), null)
})

test("revokeWarning: only when this agent's user grant is the only grant", () => {
  const me = { kind: "user", principal: "AAA" }
  assert.match(revokeWarning("hr", [me], "aaa")!, /only grant on hr\. Revoking it opens the catalog to every caller\./)
  assert.equal(revokeWarning("hr", [me, { kind: "role", principal: "viewer" }], "aaa"), null)
  assert.equal(revokeWarning("hr", [{ kind: "user", principal: "bbb" }], "aaa"), null)
  assert.equal(revokeWarning("hr", [{ kind: "role", principal: "aaa" }], "aaa"), null)
})

test("attributes: an unedited 'Sales, Korea' string and an unedited number survive unchanged", () => {
  const rows = attrRows({ department: "Sales, Korea", level: 3, tags: ["a", "b"] })
  assert.deepEqual(buildAttributes(rows), { department: "Sales, Korea", level: 3, tags: ["a", "b"] })
  assert.equal(rows[1].text, "3")
})

test("attributes: edited list round-trips one value per line; edited string stays a string", () => {
  const rows = attrRows({ tags: ["a", "b"], department: "Sales" })
  rows[0].text = "a\nb\n c "
  rows[1].text = "Sales, Korea"
  assert.deepEqual(buildAttributes(rows), { tags: ["a", "b", "c"], department: "Sales, Korea" })
  assert.equal(attrToText(["x", "y"]), "x\ny")
})

test("attributes: a number that is edited becomes text; a list toggle turns text into a list", () => {
  assert.equal(attrFromText("4", false, 3), "4")
  assert.deepEqual(attrFromText("a\nb", true, "a"), ["a", "b"])
  assert.deepEqual(buildAttributes([{ key: " k ", text: "v", isList: false }, { key: " ", text: "x", isList: false }]), { k: "v" })
})
