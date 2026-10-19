/** Presentation logic for Governance → Tool calls (GET /api/audit/tool-calls). */

export type ToolCall = {
  id: string | number; occurred_at: string
  actor_id: string | null; actor_username: string; actor_kind: string
  tool: string; outcome: string; resource: string[]; citation_sources: string[]
  hit_count: number | null; chunks_withheld: number | null; pii_masked: number | null
}

export type ActorSummary = {
  actor_id: string | null; actor_username: string; actor_kind: string; calls: number
}

/** The newest rows one request may return (the route's own maximum). */
export const PAGE = 200

/** One option per caller that has an id, in the summary's order (most calls first).
 *  A call refused before its caller was known has no id and cannot be filtered on. */
export function callerOptions(byActor: ActorSummary[]): { id: string; label: string }[] {
  const seen = new Set<string>()
  const out: { id: string; label: string }[] = []
  for (const a of byActor) {
    if (!a.actor_id || seen.has(a.actor_id)) continue
    seen.add(a.actor_id)
    out.push({ id: a.actor_id, label: a.actor_kind === "service" ? `${a.actor_username} (agent)` : a.actor_username })
  }
  return out
}

export function toolCallsUrl(since: string, actorId: string): string {
  const qs = new URLSearchParams({ since, limit: String(PAGE) })
  if (actorId) qs.set("actor_id", actorId)
  return `/api/audit/tool-calls?${qs}`
}

export function isProblem(outcome: string): boolean {
  return outcome === "refused" || outcome === "error"
}
