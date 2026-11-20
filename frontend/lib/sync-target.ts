/** Where a source table lands (app/sync_targets.py): one lake table per source table.
 *  The table-settings save answers 409 with a code; these turn it into what the panel
 *  shows. */

export type TargetRefusal =
  | { kind: "has_data"; table: string; from: string; to: string; rows: number | null; lastRunAt: string | null }
  | { kind: "duplicate"; message: string }

export function targetRefusal(status: number, detail: unknown): TargetRefusal | null {
  if (status !== 409 || !detail || typeof detail !== "object") return null
  const d = detail as Record<string, unknown>
  if (d.code === "target_has_data" && typeof d.from === "string" && typeof d.to === "string") {
    return { kind: "has_data", table: String(d.table ?? ""), from: d.from, to: d.to,
             rows: typeof d.rows === "number" ? d.rows : null,
             lastRunAt: typeof d.last_run_at === "string" ? d.last_run_at : null }
  }
  if (d.code === "duplicate_target") return { kind: "duplicate", message: String(d.message ?? "This table is already synced by another job.") }
  return null
}

/** "1,200 rows, last synced Nov 13" — what the old catalog holds. */
export function hasDataLine(r: Extract<TargetRefusal, { kind: "has_data" }>): string {
  const rows = r.rows != null ? `${r.rows.toLocaleString("en-US")} rows` : "Data"
  const when = r.lastRunAt
    ? `, last synced ${new Date(r.lastRunAt).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })}`
    : ""
  return `${rows}${when}.`
}

export type AlsoSynced = { source_table: string; catalog: string | null; enabled: boolean; last_run_at: string | null }

/** "also synced as public.customers → polaris_lake" for a row the source lists once. */
export function alsoSyncedLine(also: AlsoSynced[] | undefined): string | null {
  const live = (also ?? []).filter(a => a.enabled)
  if (!live.length) return null
  return `also synced as ${live.map(a => `${a.source_table} → ${a.catalog ?? "default"}`).join(", ")}`
}
