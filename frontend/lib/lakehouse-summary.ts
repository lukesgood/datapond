/** The dashboard's Lakehouse row, from data the Catalog, Sources and Analytics pages
 *  already load. Each figure is null when its source could not be read (shown as
 *  unavailable, never as zero). */
import { isLakeKind } from "./data-catalogs.ts"

export const STALE_AFTER_MS = 86_400_000 // same 24h rule as the Sources page

export function lakeCatalogCount(catalogs: { kind: string; enabled: boolean }[]): number {
  return catalogs.filter(c => c.enabled && isLakeKind(c.kind)).length
}

/** Sources never synced, or last synced more than 24h before `now`. */
export function staleSourceCount(sources: { last_sync_at: string | null }[], now: number): number {
  return sources.filter(s => !s.last_sync_at || now - new Date(s.last_sync_at).getTime() > STALE_AFTER_MS).length
}

/** The most recent sync across sources, or null when none ever synced. */
export function lastSyncAt(sources: { last_sync_at: string | null }[]): string | null {
  const times = sources.map(s => s.last_sync_at).filter((t): t is string => !!t)
  if (times.length === 0) return null
  return times.reduce((a, b) => (new Date(a).getTime() >= new Date(b).getTime() ? a : b))
}

export function queriesSince(items: { created_at?: string | null }[], since: Date): number {
  return items.filter(i => i.created_at && new Date(i.created_at).getTime() >= since.getTime()).length
}
