/** Types and small helpers for Settings -> Data catalogs -> Export and Mirrors
 *  (POST /api/catalogs/{name}/export, GET /api/catalogs/mirrors, POST …/mirrors/check). */

export type ExportMode = "mirror" | "move"

export const MODE_HELP: Record<ExportMode, string> = {
  mirror: "Mirror: the source keeps owning the table; the target gets a read-only registration that follows it. No data is copied.",
  move: "Move: the target becomes the owner and writes go there; the source registration becomes the read-only mirror. No data is copied.",
}

export interface ExportItem {
  schema: string
  table: string
  action: string
  location?: string | null
  metadata_file?: string | null
  rows_source?: number | null
  rows_target?: number | null
  detail?: string | null
}

export interface ExportResult {
  source: string
  target: string
  applied: boolean
  mode: ExportMode
  summary: Record<string, number>
  allowed_locations_needed: string[]
  tables: ExportItem[]
}

export interface Mirror {
  mirror: string
  owner: string
  location?: string | null
  mirror_metadata_file?: string | null
  status: string
  detail?: string | null
  checked_at?: string | null
  refreshed_at?: string | null
}

export function exportBody(o: { target: string; schema: string; mode: ExportMode; apply: boolean }) {
  const body: { target: string; mode: ExportMode; apply: boolean; schema?: string } =
    { target: o.target, mode: o.mode, apply: o.apply }
  if (o.schema.trim()) body.schema = o.schema.trim()
  return body
}

/** "3 registered, 1 failed" from the response's summary. */
export function summaryLine(summary: Record<string, number>): string {
  const parts = Object.entries(summary).filter(([, n]) => n > 0).map(([a, n]) => `${n} ${a.replace(/_/g, " ")}`)
  return parts.length ? parts.join(", ") : "nothing to do"
}

/** Badge tone for a mirror's freshness status. */
export function mirrorTone(status: string): "good" | "warn" | "bad" {
  if (status === "fresh") return "good"
  if (status === "diverged") return "warn"
  return "bad"
}

/** A plan can be applied when it found at least one table to register. */
export function canApply(plan: ExportResult | null): boolean {
  return !!plan && !plan.applied && plan.tables.some(t => t.action === "register")
}
