/** Presentation logic for AI Gateway -> Caller budgets (GET /api/settings/ai/budgets). */

export interface CallerBudget {
  user_id: string
  alias: string | null
  spend: number
  max_budget: number | null
  blocked: boolean
}

export type BudgetStatus = "blocked" | "over" | "ok" | "uncapped"

/** blocked: the gateway refuses this caller. over: spend has reached the cap.
 *  uncapped: no cap set. */
export function budgetStatus(c: Pick<CallerBudget, "spend" | "max_budget" | "blocked">): BudgetStatus {
  if (c.blocked) return "blocked"
  if (c.max_budget == null) return "uncapped"
  return c.spend >= c.max_budget ? "over" : "ok"
}

/** A cap from the text box: a non-negative number, or an error sentence. */
export function parseCap(text: string): { value: number } | { error: string } {
  const t = text.trim()
  if (t === "") return { error: "Enter a dollar amount." }
  const n = Number(t)
  if (!Number.isFinite(n) || n < 0) return { error: "The cap must be zero or more." }
  return { value: n }
}

export interface KnownCaller { id: string; label: string }

/** Callers an admin may cap that the gateway has not listed yet. Dedupes by id. */
export function unlistedCallers(known: KnownCaller[], listed: CallerBudget[]): KnownCaller[] {
  const have = new Set(listed.map(c => c.user_id))
  const seen = new Set<string>()
  return known.filter(k => {
    if (have.has(k.id) || seen.has(k.id)) return false
    seen.add(k.id)
    return true
  })
}
