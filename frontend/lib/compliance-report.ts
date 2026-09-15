// Pure pieces of the governance compliance report, kept out of the page so they can be
// tested with node --test (see collection-members.ts for the same split).

export type ToolCallRow = Record<string, unknown>
export type ToolCallActor = {
  actor_id?: string | null; actor_username: string; actor_kind: string
  calls: number; ok: number; degraded: number; error: number
  // Refused: turned away before it ran — the caller asked for a tool it may not
  // have. Older deployments do not send it (migration 0010).
  refused?: number
  collections: string[]; tables: string[]; hits: number; pii_masked: number
}
export type ToolCallSection = {
  total_available: number; returned: number; capped: boolean
  by_actor: ToolCallActor[]; rows: ToolCallRow[]
}

/** since/until query params for the audit endpoints; empty inputs mean "open". */
export function windowParams(from: string, to: string): URLSearchParams {
  const p = new URLSearchParams()
  if (from) p.set("since", new Date(`${from}T00:00:00`).toISOString())
  if (to) p.set("until", new Date(`${to}T23:59:59`).toISOString())
  return p
}

export function buildToolCallSection(
  list: { rows: ToolCallRow[]; total: number; capped: boolean },
  summary: { by_actor: ToolCallActor[] },
): ToolCallSection {
  return {
    total_available: list.total,
    returned: list.rows.length,
    capped: list.capped,
    by_actor: summary.by_actor,
    rows: list.rows,
  }
}
