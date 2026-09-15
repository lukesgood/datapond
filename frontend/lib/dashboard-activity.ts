/** What the Overview page says about today, from the tool call log and service status.
 *
 *  The page used to open on "Foundation health": inventory counts and a card per
 *  workload. The question an operator of a governed tool server brings is different —
 *  who called which tools today, what failed, what was masked — so these helpers turn
 *  GET /api/audit/tool-calls/summary and GET /api/services into that answer.
 */
export type ActorSummary = {
  actor_id?: string | null
  actor_username: string
  actor_kind: string
  calls: number
  ok?: number
  degraded?: number
  error?: number
  hits?: number
  pii_masked?: number
}

export type ActivityTotals = { calls: number; callers: number; errors: number; degraded: number; piiMasked: number }

export type ServiceState = { name: string; status: string }

export type PlatformStatus = { healthy: number; observed: number; configured: number; attention: string[] }

const num = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : 0)

/** Local midnight — "today" as the person reading the page means it. */
export function startOfLocalDay(now: Date): Date {
  const day = new Date(now)
  day.setHours(0, 0, 0, 0)
  return day
}

/** The by_actor array of a summary response, or null when the payload is not one. */
export function actorsFrom(payload: unknown): ActorSummary[] | null {
  if (typeof payload !== "object" || payload === null) return null
  const list = (payload as { by_actor?: unknown }).by_actor
  if (!Array.isArray(list)) return null
  return list.filter((a): a is ActorSummary => typeof a === "object" && a !== null && typeof (a as ActorSummary).actor_username === "string")
}

export function activityTotals(actors: ActorSummary[]): ActivityTotals {
  return actors.reduce<ActivityTotals>(
    (t, a) => ({
      calls: t.calls + num(a.calls),
      callers: t.callers + 1,
      errors: t.errors + num(a.error),
      degraded: t.degraded + num(a.degraded),
      piiMasked: t.piiMasked + num(a.pii_masked),
    }),
    { calls: 0, callers: 0, errors: 0, degraded: 0, piiMasked: 0 },
  )
}

const plural = (n: number, word: string) => `${n.toLocaleString("en-US")} ${word}${n === 1 ? "" : "s"}`

export function activitySentence(t: ActivityTotals): string {
  if (t.calls === 0) return "No tool calls yet today."
  const parts = [`${plural(t.calls, "tool call")} from ${plural(t.callers, "caller")} today`]
  if (t.errors > 0) parts.push(plural(t.errors, "error"))
  if (t.piiMasked > 0) parts.push(`${plural(t.piiMasked, "PII value")} masked`)
  return `${parts.join(" · ")}.`
}

/** In-cluster workloads are observed; managed adapters are only configured, never probed. */
export function platformStatus(services: ServiceState[]): PlatformStatus {
  const observed = services.filter((s) => s.status !== "managed")
  return {
    healthy: observed.filter((s) => s.status === "healthy").length,
    observed: observed.length,
    configured: services.length - observed.length,
    attention: observed.filter((s) => s.status !== "healthy").map((s) => s.name).sort(),
  }
}

/** Gateway-wide lifetime spend from GET /api/settings/ai/budget-alerts, in the shape
 *  totalSpendLabel reads. /settings/ai/spend is not this: it sums spend recorded against
 *  virtual keys only, and read $0.00 on a deployment whose gateway had spent $0.30. */
export function spendFromBudgetAlerts(payload: unknown): { total_spend: number } | { unavailable: string } {
  const total = typeof payload === "object" && payload !== null ? (payload as { spend_total?: unknown }).spend_total : undefined
  return typeof total === "number" && Number.isFinite(total)
    ? { total_spend: total }
    : { unavailable: "gateway spend could not be read" }
}
