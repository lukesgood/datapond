/** Axis tick labels for Analytics charts (components/query/chart-renderer.tsx). */
const COMPACT = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 })

/** Axis ticks: 45000000 reads as 45M. */
export function formatTick(v: unknown): string {
  return typeof v === "number" && Math.abs(v) >= 10_000 ? COMPACT.format(v) : String(v ?? "")
}

const ISO_TS = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/

/** X ticks for dates: "2026-05-20" at midnight, "05-20 00:23" otherwise, instead of the
 *  full ISO string ("2026-05-20T00:23:00Z") that overlapped its neighbours. */
export function formatTimeTick(v: unknown): string {
  const m = typeof v === "string" ? ISO_TS.exec(v) : null
  if (!m) return formatTick(v)
  const [, y, mo, d, h, mi] = m
  return h === "00" && mi === "00" ? `${y}-${mo}-${d}` : `${mo}-${d} ${h}:${mi}`
}
