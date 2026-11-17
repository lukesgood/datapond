/** View logic for the Agents pages (service accounts, one per agent). Pure, so the
 *  list's status and its three independently loaded sources are tested without React. */

export interface AgentKey {
  id: string; name: string; key_prefix: string; status: string; scopes: string[]
  expires_at: string | null; last_used_at: string | null; created_at: string
}

export interface Agent {
  id: string; username: string; display_name: string | null; role: string
  is_active: boolean; created_at: string
  keys: AgentKey[]
  oauth_client: { client_id: string; issuer: string | null } | null
  attributes?: Record<string, unknown>
}

export interface ByActor { actor_id: string | null; calls: number; refused: number }
export interface Budget { user_id: string; spend: number; max_budget: number | null }
export type AgentRow = Agent & {
  calls24h: number | null; refused24h: number | null; spend: number | null; cap: number | null
}

export type AgentStatus = {
  label: "disabled" | "no active key" | "key expiring" | "active"
  tone: "bad" | "warn" | "ok"
}

const EXPIRY_WARN_MS = 14 * 86_400_000

/** What an operator needs to know at a glance: can this agent get in at all, and will
 *  it stop soon. A key counts only while active and unexpired. */
export function agentStatus(a: Agent, now: Date): AgentStatus {
  if (!a.is_active) return { label: "disabled", tone: "bad" }
  const live = a.keys.filter(k => k.status === "active"
    && (k.expires_at === null || new Date(k.expires_at).getTime() > now.getTime()))
  if (live.length === 0) return { label: "no active key", tone: "warn" }
  // Expiring only if every live key is: a second, later key means no outage is coming.
  const soon = live.every(k => k.expires_at !== null
    && new Date(k.expires_at).getTime() - now.getTime() <= EXPIRY_WARN_MS)
  return soon ? { label: "key expiring", tone: "warn" } : { label: "active", tone: "ok" }
}

/** Latest `last_used_at` across the agent's keys (ISO strings, so max by time). */
export function lastUsed(a: Agent): string | null {
  let best: string | null = null
  for (const k of a.keys) {
    if (k.last_used_at && (best === null || new Date(k.last_used_at) > new Date(best))) best = k.last_used_at
  }
  return best
}

/** Join the list with the audit summary and budgets. A source that failed to load is
 *  null and gives null columns ("—"); a source that loaded but does not mention the
 *  agent means it made no calls and has spent nothing. */
export function joinAgentRows(agents: Agent[], summary: ByActor[] | null, budgets: Budget[] | null): AgentRow[] {
  return agents.map(a => {
    const s = summary?.find(r => r.actor_id === a.id)
    const b = budgets?.find(r => r.user_id === a.id)
    return {
      ...a,
      calls24h: summary ? (s?.calls ?? 0) : null,
      refused24h: summary ? (s?.refused ?? 0) : null,
      spend: budgets ? (b?.spend ?? 0) : null,
      cap: budgets ? (b?.max_budget ?? null) : null,
    }
  })
}

export function viaLabel(via: "user" | "role" | "open" | null, role: string): string {
  switch (via) {
    case "user": return "granted to this agent"
    case "role": return `granted to role ${role}`
    case "open": return "open to every caller"
    default: return "not granted"
  }
}

/** GET /api/service-accounts/{id}: the list item plus what the page needs to edit it. */
export type AgentDetail = Agent & {
  permissions: string[]
  oauth?: { enabled: boolean; issuer: string | null }
  assignable_roles: string[]
  grantable_permissions: string[]
  rate_limit_per_minute: number
  /** The agent's own PII guardrail; null inherits `pii_default`. */
  pii_mode?: PiiMode | null
  /** The deployment's PII_GUARDRAIL_MODE, which `pii_mode` can only tighten. */
  pii_default?: PiiMode
}

// ── purpose presets and the PII guardrail ────────────────────────────────────

export type PiiMode = "off" | "mask" | "block"

/** GET /api/service-accounts `presets`: what an agent is for, and the role, first-key
 *  scopes and PII mode that serve it. The backend owns the list. */
export interface AgentPreset {
  id: string; label: string; description: string
  role: string; scopes: string[]; pii_mode: PiiMode | null
}

const STRICTNESS: Record<PiiMode, number> = { off: 0, mask: 1, block: 2 }

/** What applies to this agent's requests: the stricter of its own mode and the
 *  deployment default, as the backend resolves it (guardrails/pii_ko.strictest). */
export function effectivePiiMode(own: PiiMode | null | undefined, deployment: PiiMode): PiiMode {
  if (!own || !(own in STRICTNESS)) return deployment
  return STRICTNESS[own] > STRICTNESS[deployment] ? own : deployment
}

export const PII_MODE_TEXT: Record<PiiMode, string> = {
  off: "off — text passes unchanged",
  mask: "mask — Korean PII is masked before the model and in answers",
  block: "block — a request carrying PII is refused",
}

/** A mode the agent holds that changes nothing, because the deployment is already as
 *  strict or stricter. Said out loud so `off` is never read as "unmasked". */
export function piiModeNote(own: PiiMode | null | undefined, deployment: PiiMode): string | null {
  if (!own) return null
  if (STRICTNESS[own] <= STRICTNESS[deployment] && own !== deployment)
    return `The deployment already applies ${deployment}; a caller's mode can only make it stricter.`
  return null
}

/** The body for POST /api/service-accounts. A preset brings its role; pii_mode is sent
 *  only when the admin changed it from the preset's, so the backend owns the default. */
export function createAgentBody(
  name: string, description: string,
  choice: { preset: AgentPreset } | { role: string },
  pii: PiiMode | null, piiTouched: boolean,
  keyDays?: number | null,
): Record<string, unknown> {
  const body: Record<string, unknown> = { name: name.trim() }
  if (description.trim()) body.description = description.trim()
  if ("preset" in choice) body.preset = choice.preset.id
  else body.role = choice.role
  if (piiTouched || !("preset" in choice)) body.pii_mode = pii
  // Only a preset issues a key; null asks for one that never expires.
  if ("preset" in choice && keyDays !== undefined) body.key_expires_in_days = keyDays
  return body
}

// ── catalog grants ───────────────────────────────────────────────────────────
// A catalog with no grants is open to every caller; the first grant restricts it to
// the granted principals and the last revoke reopens it. Both flip access for people
// other than the agent on screen, so the page must say so before doing it.

export function grantWarning(catalog: string, restricted: boolean): string | null {
  return restricted ? null
    : `${catalog} is open to every caller. Granting it to this agent restricts it: every other caller without a grant loses access.`
}

export function revokeWarning(
  catalog: string, grants: { kind: string; principal: string }[], agentId: string,
): string | null {
  const only = grants.length === 1 && grants[0].kind === "user"
    && grants[0].principal.toLowerCase() === agentId.toLowerCase()
  return only ? `This is the only grant on ${catalog}. Revoking it opens the catalog to every caller.` : null
}

// ── attributes ───────────────────────────────────────────────────────────────
// Values chunk rules and SQL RLS read. Saving replaces the whole object, so a value the
// admin did not touch has to come back exactly as it was: never re-parsed, never
// re-typed. A list is a list because it was one (or the admin said so), never because
// a string contains a comma.

/** The text box content: lists one value per line, other scalars as strings. */
export function attrToText(v: unknown): string {
  if (v === undefined || v === null) return ""
  if (Array.isArray(v)) return v.map(x => String(x)).join("\n")
  return String(v)
}

export const attrIsList = (v: unknown): boolean => Array.isArray(v)

export interface AttrRow { key: string; text: string; isList: boolean; original?: unknown }

/** One value back from the box: the original, untouched, unless text or list-ness changed. */
export function attrFromText(text: string, isList: boolean, original?: unknown): unknown {
  if (original !== undefined && text === attrToText(original) && isList === attrIsList(original)) return original
  return isList ? text.split("\n").map(s => s.trim()).filter(Boolean) : text.trim()
}

export function buildAttributes(rows: AttrRow[]): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const r of rows) if (r.key.trim()) out[r.key.trim()] = attrFromText(r.text, r.isList, r.original)
  return out
}

export function attrRows(attrs: Record<string, unknown> | undefined): AttrRow[] {
  return Object.entries(attrs ?? {}).map(([key, v]) => ({ key, text: attrToText(v), isList: attrIsList(v), original: v }))
}

// ── what a new agent will be able to do ──────────────────────────────────────
// The create page explains a choice before it is made. Permissions are named for the
// system; these say what each lets the agent do, in the words an admin would use.

export const PERMISSION_TEXT: Record<string, string> = {
  "catalog:read": "Browse tables and schemas in the catalog",
  "catalog:write": "Move tables between catalogs",
  "query:run": "Run read-only SQL, including approved metrics",
  "query:write": "Change data or schema with SQL",
  "dashboard:write": "Save and delete dashboards",
  "knowledge:read": "Search the Knowledge collections it is granted",
  "knowledge:write": "Create collections and add documents",
  "ai:generate": "Call models for cited answers and NL→SQL (billed to this agent)",
  "connector:read": "See sources and when they last synced",
  "connector:write": "Create, edit and run source syncs",
  "pipeline:write": "Edit transforms and streaming jobs",
  "workbench:read": "Browse notebooks and experiments",
  "workbench:write": "Run notebooks and change experiments",
  "governance:read": "Read row/column policies and PII reports",
  "governance:write": "Change row/column policies",
  "audit:read": "Read the audit log",
  "spend:read": "See model usage and cost",
  "service:manage": "Operate infrastructure and storage",
}

const WRITES = ["query:write", "knowledge:write", "connector:write", "catalog:write",
  "pipeline:write", "dashboard:write", "workbench:write", "governance:write", "service:manage"]

/** Plain-language can / cannot lists for a set of permissions. "Cannot" names only the
 *  limits an admin weighs when choosing (SQL, model spend, Knowledge, writes) plus the
 *  ones that hold for every agent, rather than every permission it lacks. */
export function describeAccess(perms: string[]): { can: string[]; cannot: string[] } {
  const held = new Set(perms)
  const can = perms.filter(p => p in PERMISSION_TEXT).sort().map(p => PERMISSION_TEXT[p])
  const cannot: string[] = []
  if (!held.has("query:run")) cannot.push("Run SQL or read metrics")
  if (!held.has("knowledge:read")) cannot.push("Read Knowledge collections")
  if (!held.has("ai:generate")) cannot.push("Call models, so it never adds model spend")
  if (!WRITES.some(w => held.has(w))) cannot.push("Change any data, source or setting")
  cannot.push("Sign in to the console, manage users or change settings")
  return { can, cannot }
}

// ── the agent page's summary rail ────────────────────────────────────────────

function liveKeys(a: Agent, now: Date): AgentKey[] {
  return a.keys.filter(k => k.status === "active"
    && (k.expires_at === null || new Date(k.expires_at).getTime() > now.getTime()))
}

/** What the agent's live keys can actually do: each key's scopes, or the whole role for
 *  a key with none (as the backend's intersection does), unioned. */
export function keyPermissions(a: Agent & { permissions: string[] }, now: Date): string[] {
  const out = new Set<string>()
  for (const k of liveKeys(a, now)) {
    const held = new Set(a.permissions)
    for (const p of (k.scopes.length ? k.scopes : a.permissions)) if (held.has(p)) out.add(p)
  }
  return [...out].sort()
}

export interface Attention { tone: "bad" | "warn"; text: string }

/** Gaps between what was set up and what will work. `collections`/`catalogs` are null
 *  while loading or when they failed, and then say nothing rather than guess. */
export function agentAttention(
  a: Agent & { permissions: string[] }, now: Date,
  collections: { name: string; access: string }[] | null,
  catalogs: { catalog: string; via: string | null }[] | null,
): Attention[] {
  if (!a.is_active) return [{ tone: "bad", text: "Disabled: every key is refused." }]
  const live = liveKeys(a, now)
  if (live.length === 0) return [{ tone: "warn", text: "No active key: it cannot call anything yet." }]
  const out: Attention[] = []
  if (live.every(k => k.expires_at !== null && new Date(k.expires_at).getTime() - now.getTime() <= EXPIRY_WARN_MS)) {
    const last = live.map(k => k.expires_at as string).sort().at(-1) as string
    out.push({ tone: "warn", text: `Every key expires by ${last.slice(0, 10)}. Rotate or issue one before then.` })
  }
  const perms = new Set(keyPermissions(a, now))
  if (perms.has("knowledge:read") && collections !== null && collections.length === 0)
    out.push({ tone: "warn", text: "No collection granted: Knowledge searches return nothing." })
  if (!perms.has("catalog:read") && catalogs?.some(c => c.via === "user"))
    out.push({ tone: "warn", text: "Catalog grants have no effect: no key has catalog:read." })
  return out
}
