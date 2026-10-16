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
  attributes?: Record<string, string | string[]>
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
}
