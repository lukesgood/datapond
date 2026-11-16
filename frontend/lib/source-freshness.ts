/** Sources page: which sources are stale, and the All / Stale / Paused filter.
 *
 *  Only an active source can be stale. A paused source is one a person said is not in use;
 *  an error source already shows as Error; a pending one has not run yet. The Overview
 *  stale line links here with ?filter=stale.
 */

export type SourceFilter = "all" | "stale" | "paused"

export const STALE_AFTER_MS = 86_400_000   // a day, as on the server (app/api/ops.py)

type Src = { status: string; last_sync_at: string | null }

export function isStale(s: Src, now: number): boolean {
  if (s.status !== "active") return false
  return !s.last_sync_at || now - new Date(s.last_sync_at).getTime() > STALE_AFTER_MS
}

export function filterSources<T extends Src>(list: T[], filter: SourceFilter, now: number): T[] {
  if (filter === "stale") return list.filter((s) => isStale(s, now))
  if (filter === "paused") return list.filter((s) => s.status === "paused")
  return list
}

export function sourceCounts(list: Src[], now: number): Record<SourceFilter, number> {
  return {
    all: list.length,
    stale: list.filter((s) => isStale(s, now)).length,
    paused: list.filter((s) => s.status === "paused").length,
  }
}

export function parseSourceFilter(search: string): SourceFilter {
  const v = new URLSearchParams(search).get("filter")
  return v === "stale" || v === "paused" ? v : "all"
}
