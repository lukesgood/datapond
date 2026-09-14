/** "Total spend" on the AI Gateway page, from GET /api/settings/ai/spend.
 *
 *  That endpoint answers `{total_spend, keys_with_spend}` when it could read the gateway
 *  and `{unavailable}` when it could not (backend spend_summary, commit 0efb679). Only the
 *  first is a measurement. Reading `.total_spend` off the second is how the Virtual keys
 *  card crashed the page, so this takes whatever arrived and decides what it is.
 */
export type SpendLabel = { text: string; measured: boolean; title?: string }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

export function totalSpendLabel(summary: unknown): SpendLabel {
  if (isRecord(summary) && typeof summary.total_spend === "number" && Number.isFinite(summary.total_spend)) {
    return { text: `$${summary.total_spend.toFixed(4)}`, measured: true }
  }
  // Same convention as the Governance stat cards: an em dash with a "Not measured" title,
  // never a zero, when nothing was measured.
  const reason = isRecord(summary) && typeof summary.unavailable === "string" ? summary.unavailable : null
  return { text: "—", measured: false, title: reason ? `Not measured: ${reason}` : "Not measured" }
}
