/** Sources page: which sources are stale, why, and the All / Stale / Paused filter.
 *
 *  The server decides (app/source_freshness.py): a source is stale only when it missed a
 *  run its own schedule asked for — `overdue_since` is that run's time. A source synced by
 *  hand is never stale; the list shows how long since it last synced instead. Only an
 *  active source can be stale. The Overview stale line links here with ?filter=stale.
 */
import { parseCron } from "./schedule.ts"

export type SourceFilter = "all" | "stale" | "paused"

export type FreshnessFields = {
  status: string
  schedule?: string | null
  last_sync_at: string | null
  last_success_at?: string | null
  overdue_since?: string | null
  last_run_at?: string | null
  last_run_status?: string | null
}

export function isStale(s: FreshnessFields): boolean {
  return s.status === "active" && Boolean(s.overdue_since)
}

export function filterSources<T extends FreshnessFields>(list: T[], filter: SourceFilter): T[] {
  if (filter === "stale") return list.filter(isStale)
  if (filter === "paused") return list.filter((s) => s.status === "paused")
  return list
}

export function sourceCounts(list: FreshnessFields[]): Record<SourceFilter, number> {
  return {
    all: list.length,
    stale: list.filter(isStale).length,
    paused: list.filter((s) => s.status === "paused").length,
  }
}

export function parseSourceFilter(search: string): SourceFilter {
  const v = new URLSearchParams(search).get("filter")
  return v === "stale" || v === "paused" ? v : "all"
}

/** "Mon 08:00" within a week of `now`, else "Nov 18, 08:00" (local time). */
export function whenLabel(iso: string | null | undefined, now: number): string {
  if (!iso) return "never"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
  if (Math.abs(now - d.getTime()) < 6 * 86_400_000) {
    return `${d.toLocaleDateString("en-US", { weekday: "short" })} ${time}`
  }
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`
}

/** The last run, when it is newer than the last success and did not fully work. */
export function failedSince(s: FreshnessFields): boolean {
  if (!s.last_run_at || !s.last_run_status || s.last_run_status === "success") return false
  return !s.last_success_at || new Date(s.last_run_at).getTime() > new Date(s.last_success_at).getTime()
}

/** Why a stale source is stale, as the lines a person reads: what was missed, the data's
 *  age, and what happened last. Empty for a source that is not stale. */
export function staleReasons(s: FreshnessFields, now: number): string[] {
  if (!isStale(s)) return []
  const lines = [
    `Missed the scheduled run due ${whenLabel(s.overdue_since, now)}` +
      (s.schedule ? ` (${parseCron(s.schedule)})` : "") + ".",
    s.last_success_at
      ? `Data is from the last successful sync, ${whenLabel(s.last_success_at, now)}.`
      : "It has never synced successfully.",
  ]
  if (failedSince(s)) {
    lines.push(`The last sync, ${whenLabel(s.last_run_at, now)}, ${s.last_run_status === "running" ? "is still running" : "did not finish: " + s.last_run_status}.`)
  }
  lines.push("Scheduled runs go missing when the scheduler is off, the node was down at that time, or the backend could not start the run. Sync now to refresh the data.")
  return lines
}
