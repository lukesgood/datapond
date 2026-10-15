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
/** The newest unapproved version — what "Approve vN" approves — with its own SQL. The
 *  server sends it only to viewers who may author or approve. */
export type PendingVersion = {
  version: number; catalog: string; base_table: string; measure: string; filters: string | null
  example_sql: string | null
}
export type MetricDetail = {
  metric: MetricSummary & { version?: number; measure?: string; filters?: string | null; base_table?: string }
  versions: MetricVersionRow[]; pending: PendingVersion | null; broken: boolean; broken_reason: string | null
  example_sql: string | null; partition_info: string; recent_queries: number
}
export type AiSqlMetricInfo = { metrics_provided?: string[]; suggested_metric?: { name: string } | null }

export function metricStatusBadge(m: { status: string; current_version: number | null }) {
  if (m.status === "retired") return { label: "retired", tone: "retired" as const }
  if (m.status === "approved" && m.current_version) return { label: `v${m.current_version}`, tone: "ok" as const }
  return { label: "draft", tone: "draft" as const }
}

// A dimension shows its column (through its join's table), so a column or join change
// is visible in the diff, not only a rename.
const dim = (d: DimensionRow) => `${d.name}:${d.join ? `${d.join.to_table}.` : ""}${d.column}`
const show = (v: unknown): string =>
  Array.isArray(v) ? v.map(x => (x && typeof x === "object" ? dim(x as DimensionRow) : show(x))).join(", ")
    : v === null || v === undefined ? "—" : String(v)

const FIELDS: (keyof MetricVersionRow)[] =
  ["catalog", "base_table", "measure", "filters", "time_column", "grains", "max_period_days", "dimensions"]

export function versionDiff(prev: MetricVersionRow | undefined, next: MetricVersionRow): string[] {
  if (!prev) return ["first version"]
  return FIELDS.filter(f => JSON.stringify(prev[f]) !== JSON.stringify(next[f]))
    .map(f => `${f}: ${show(prev[f])} → ${show(next[f])}`)
}

export function pendingApproval(detail: MetricDetail | null): PendingVersion | null {
  if (!detail || detail.metric.status === "retired") return null
  return detail.pending ?? null
}

/** A metric without a time column answers 400 to a period; only that error is retried
 *  without one. Any other 400 is the caller's to see. */
export function retryWithoutPeriod(status: number, message: string): boolean {
  return status === 400 && /no time column/i.test(message)
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

export type RelationshipEdge = {
  source: string; target: string; evidence: string; count: number
  joins?: { left_column: string; right_column: string }[]
}
export type CatalogEntry = { name: string; engine_catalog: string }

/** The body of POST /semantic/joins for a relationship edge, or null when it cannot be one.
 *
 *  Edge ids are `engine_catalog.schema.table`; the join registry keys on the registry name,
 *  so the engine name is mapped through GET /catalogs (raw value when unmapped). Naming
 *  candidates come in alphabetical order, not many-to-one direction, so `reversed` swaps
 *  the sides and the column pair; the server's uniqueness check says which way is valid.
 */
export function joinCandidatePayload(edge: RelationshipEdge, catalogs: CatalogEntry[], reversed = false) {
  const pair = edge.joins?.[0]
  if (!pair) return null
  const [fromId, toId] = reversed ? [edge.target, edge.source] : [edge.source, edge.target]
  const [fromCat, ...from] = fromId.split(".")
  const [toCat, ...to] = toId.split(".")
  if (!from.length || !to.length || fromCat.toLowerCase() !== toCat.toLowerCase()) return null
  const entry = catalogs.find(c => c.engine_catalog.toLowerCase() === fromCat.toLowerCase())
  return {
    catalog: entry?.name ?? fromCat,
    from_table: from.join("."), to_table: to.join("."),
    on_columns: [reversed ? [pair.right_column, pair.left_column] : [pair.left_column, pair.right_column]],
    source: edge.evidence === "observed" ? "history" : "naming",
  }
}
