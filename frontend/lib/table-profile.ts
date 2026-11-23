/** Shapes and small readings of GET /api/catalog/tables/{ns}/{t}/profile and /keys.
 *
 *  The profile comes from the table's own statistics (SHOW STATS, Iceberg snapshots),
 *  so it costs no scan; `nulls` is a fraction and `distinct` an estimate. */

export type ProfileColumn = {
  name: string
  nulls?: number | null
  distinct?: number | null
  low?: string | null
  high?: string | null
  /** masked or bound to a PII concept: no range is shown */
  hidden?: boolean
}
export type Snapshot = { at: string; operation: string; added_records: number | null; total_records: number | null }
export type TableProfile = {
  restricted: boolean
  rows: number | null
  columns: ProfileColumn[]
  snapshots: Snapshot[]
  note?: string
}
export type ForeignKey = { column: string; ref_table: string; ref_column: string; via: "source" | "lake" }
export type TableKeys = {
  primary: string[]
  foreign: ForeignKey[]
  referenced_by: { table: string; column: string; ref_column: string }[]
}

/** "12.5%", "<0.1%", "0%", or "—" when the statistic is missing. */
export function nullPct(fraction: number | null | undefined): string {
  if (fraction == null || Number.isNaN(fraction)) return "—"
  if (fraction === 0) return "0%"
  const pct = fraction * 100
  if (pct < 0.1) return "<0.1%"
  // Whole numbers from 10% up, except just under 100: "99.9%" is not "100%".
  if (pct >= 10 && !(pct > 99 && pct < 100)) return `${Math.round(pct)}%`
  return `${Math.floor(pct * 10) / 10}%`
}

/** "about 1,200" for an estimate; exact counts are not claimed. */
export function distinctLabel(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—"
  return `≈ ${Math.round(n).toLocaleString("en-US")}`
}

/** Badges per column (lower-cased name): PK, and FK with what it points at. */
export function keyBadges(keys: TableKeys | null): Record<string, { label: string; title: string }[]> {
  const out: Record<string, { label: string; title: string }[]> = {}
  if (!keys) return out
  const add = (col: string, b: { label: string; title: string }) =>
    (out[col.toLowerCase()] ??= []).push(b)
  for (const c of keys.primary) add(c, { label: "PK", title: "Primary key in the source database" })
  for (const f of keys.foreign) {
    const ref = f.ref_table.split(".").slice(-1)[0]
    add(f.column, {
      label: `FK → ${ref}.${f.ref_column}`,
      title: `Foreign key to ${f.ref_table}.${f.ref_column}` +
        (f.via === "lake" ? " (declared on the source table this is synced from)" : " (declared in the source database)"),
    })
  }
  return out
}

/** "+1,200 rows" for an append, "overwrite" when the operation replaced data. */
export function snapshotLabel(s: Snapshot): string {
  if (s.operation === "append" && s.added_records != null) return `+${s.added_records.toLocaleString("en-US")} rows`
  return s.operation
}
