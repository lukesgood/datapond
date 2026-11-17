import test from "node:test"
import assert from "node:assert/strict"
import { agentAttention, keyPermissions, describeAccess, createAgentBody, effectivePiiMode, piiModeNote, type AgentPreset, attrFromText, attrRows, attrToText, buildAttributes, grantWarning, revokeWarning, agentStatus, joinAgentRows, lastUsed, viaLabel, type Agent, type AgentKey } from "./agents.ts"

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

// ── presets and PII mode ─────────────────────────────────────────────────────

const PRESET: AgentPreset = {
  id: "knowledge_assistant", label: "Document Q&A", description: "",
  role: "ai_engineer", scopes: ["knowledge:read", "ai:generate"], pii_mode: "mask",
}

test("pii: the stricter of own and deployment applies, null inherits", () => {
  assert.equal(effectivePiiMode(null, "mask"), "mask")
  assert.equal(effectivePiiMode("block", "mask"), "block")
  assert.equal(effectivePiiMode("off", "mask"), "mask")
  assert.equal(effectivePiiMode("mask", "off"), "mask")
  assert.equal(effectivePiiMode("bogus" as never, "mask"), "mask")
})

test("pii: a looser own mode is called out, an equal or stricter one is not", () => {
  assert.match(piiModeNote("off", "mask") ?? "", /only make it stricter/)
  assert.equal(piiModeNote("mask", "mask"), null)
  assert.equal(piiModeNote("block", "mask"), null)
  assert.equal(piiModeNote(null, "block"), null)
})

test("create body: a preset sends its id and leaves role and pii to the backend", () => {
  assert.deepEqual(createAgentBody(" bot ", "", { preset: PRESET }, "mask", false),
    { name: "bot", preset: "knowledge_assistant" })
})

test("create body: a changed pii mode is sent with the preset, including null", () => {
  assert.deepEqual(createAgentBody("bot", "d", { preset: PRESET }, null, true),
    { name: "bot", description: "d", preset: "knowledge_assistant", pii_mode: null })
})

test("create body: custom sends role and pii mode", () => {
  assert.deepEqual(createAgentBody("bot", "", { role: "viewer" }, "block", false),
    { name: "bot", role: "viewer", pii_mode: "block" })
})

test("describe: a read-only Q&A agent", () => {
  const d = describeAccess(["knowledge:read", "ai:generate"])
  assert.equal(d.can.length, 2)
  assert.ok(d.cannot.includes("Run SQL or read metrics"))
  assert.ok(d.cannot.includes("Change any data, source or setting"))
  assert.ok(!d.cannot.some(c => c.startsWith("Call models")))
})

test("describe: a writer is not told it cannot change data; unknown perms are skipped", () => {
  const d = describeAccess(["connector:write", "made:up"])
  assert.equal(d.can.length, 1)
  assert.ok(!d.cannot.includes("Change any data, source or setting"))
  assert.equal(d.cannot.at(-1), "Sign in to the console, manage users or change settings")
})

// ── summary rail ─────────────────────────────────────────────────────────────

const detail = (over: Partial<Agent> = {}) => ({ ...agent(over), permissions: ["catalog:read", "knowledge:read", "ai:generate", "query:run"] })

test("key permissions: scopes intersect the role; an unscoped key gets the role; dead keys count for nothing", () => {
  assert.deepEqual(keyPermissions(detail({ keys: [key({ scopes: ["knowledge:read", "made:up"] })] }), NOW), ["knowledge:read"])
  assert.equal(keyPermissions(detail({ keys: [key({ scopes: [] })] }), NOW).length, 4)
  assert.deepEqual(keyPermissions(detail({ keys: [key({ status: "revoked" }), key({ expires_at: iso(-1) })] }), NOW), [])
})

test("attention: disabled and keyless short-circuit", () => {
  assert.equal(agentAttention(detail({ is_active: false }), NOW, [], [])[0].tone, "bad")
  assert.match(agentAttention(detail({ keys: [] }), NOW, [], [])[0].text, /No active key/)
})

test("attention: knowledge without a collection, catalog grant without the scope, expiring keys", () => {
  const a = detail({ keys: [key({ scopes: ["knowledge:read"], expires_at: iso(5) })] })
  const t = agentAttention(a, NOW, [], [{ catalog: "c", via: "user" }]).map(x => x.text).join(" | ")
  assert.match(t, /expires by/)
  assert.match(t, /No collection granted/)
  assert.match(t, /no key has catalog:read/)
})

test("attention: nothing to say while sources load, or when all is well", () => {
  const a = detail({ keys: [key({ scopes: ["knowledge:read", "catalog:read"] })] })
  assert.deepEqual(agentAttention(a, NOW, null, null), [])
  assert.deepEqual(agentAttention(a, NOW, [{ name: "x", access: "reader" }], [{ catalog: "c", via: "user" }]), [])
})

test("create body: key lifetime goes with a preset only, null included", () => {
  assert.equal(createAgentBody("b", "", { preset: PRESET }, null, false, null).key_expires_in_days, null)
  assert.equal(createAgentBody("b", "", { preset: PRESET }, null, false, 30).key_expires_in_days, 30)
  assert.ok(!("key_expires_in_days" in createAgentBody("b", "", { role: "viewer" }, null, false, 30)))
})
