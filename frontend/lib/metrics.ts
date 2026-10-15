/** Metric definitions in the console: view helpers with no React, so they are testable.
 *
 *  The server decides what a viewer may do (`viewer.can_author`, `viewer.can_approve`);
 *  nothing here infers a permission from a role name.
 */

export type MetricSummary = {
  name: string; label: string; description: string; synonyms: string[]
  owner_name: string | null; status: "draft" | "approved" | "retired"
  current_version: number | null; catalog: string | null
}
export type Viewer = { can_author: boolean; can_approve: boolean }
export type DimensionRow = { name: string; column: string; join?: { to_table: string; on: string[][] } }
export type MetricVersionRow = {
  version: number; catalog: string; base_table: string; measure: string; filters: string | null
  time_column: string | null; grains: string[]; max_period_days: number; dimensions: DimensionRow[]
  created_by_name?: string | null; change_note?: string; created_at?: string | null
  approved_by_name?: string | null; approved_at?: string | null
}
export type MetricDetail = {
  metric: MetricSummary & { version?: number; measure?: string; filters?: string | null; base_table?: string }
  versions: MetricVersionRow[]; broken: boolean; broken_reason: string | null
  example_sql: string | null; partition_info: string; recent_queries: number
}
export type AiSqlMetricInfo = { metrics_provided?: string[]; suggested_metric?: { name: string } | null }

export function metricStatusBadge(m: { status: string; current_version: number | null }) {
  if (m.status === "retired") return { label: "retired", tone: "retired" as const }
  if (m.status === "approved" && m.current_version) return { label: `v${m.current_version}`, tone: "ok" as const }
  return { label: "draft", tone: "draft" as const }
}

const show = (v: unknown): string =>
  Array.isArray(v) ? v.map(x => (typeof x === "object" ? (x as DimensionRow).name : String(x))).join(", ")
    : v === null || v === undefined ? "—" : String(v)

const FIELDS: (keyof MetricVersionRow)[] =
  ["catalog", "base_table", "measure", "filters", "time_column", "grains", "max_period_days", "dimensions"]

export function versionDiff(prev: MetricVersionRow | undefined, next: MetricVersionRow): string[] {
  if (!prev) return ["first version"]
  return FIELDS.filter(f => JSON.stringify(prev[f]) !== JSON.stringify(next[f]))
    .map(f => `${f}: ${show(prev[f])} → ${show(next[f])}`)
}

export function fieldError(detail: unknown): { field: string; message: string } | null {
  if (detail && typeof detail === "object" && "field" in detail && "message" in detail) {
    const d = detail as { field: unknown; message: unknown }
    return { field: String(d.field), message: String(d.message) }
  }
  return null
}

export function aiSqlMetricView(resp: AiSqlMetricInfo) {
  return {
    chips: (resp.metrics_provided ?? []).map(id => id.replace("@v", " v")),
    suggestion: resp.suggested_metric?.name ?? null,
  }
}

export function approvalWarning(partitionInfo: string): string | null {
  return partitionInfo === "partitioned" ? null
    : "Partitioning of the base table is unknown: a query may be a full scan within its period, billed by bytes scanned."
}
