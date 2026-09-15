/** One way to write a dollar amount across the UI.
 *
 *  The AI Gateway, Governance cost tab, and My spend each had their own formatter —
 *  four decimals here, six there — so the same spend read `$0.2994`, `$0.000053`, and
 *  `$0.000000` on neighbouring rows. Cents are what an operator scans; an amount below
 *  one cent says so rather than printing a column of zeros.
 */
export function formatUsd(amount: number): string {
  if (!Number.isFinite(amount)) return "—"
  if (amount === 0) return "$0.00"
  if (Math.abs(amount) < 0.01) return amount < 0 ? "-<$0.01" : "<$0.01"
  const text = Math.abs(amount).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return amount < 0 ? `-$${text}` : `$${text}`
}
