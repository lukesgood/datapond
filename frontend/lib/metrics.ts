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

/** Dimensions copied from the version being edited that reach another table but are not
 *  matched to an approved join id: the join list has not loaded, failed to load, or no
 *  longer holds that join. Saved as they are, they would be sent as base-table columns. */
export function unresolvedJoinDims(dims: { name: string; join_id: number | null; joinRef?: unknown }[]): string[] {
  return dims.filter(d => d.joinRef && d.join_id === null).map(d => d.name)
}

const iso = (y: number, m: number, d: number) =>
  `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`
const lastDay = (y: number, m: number) => new Date(y, m, 0).getDate()
const months = (y: number, from: number, to: number) => `${iso(y, from, 1)}..${iso(y, to, lastDay(y, to))}`

/** The period a question names, in the server's `period` forms (dates inclusive), or null
 *  when it names none. Only the forms read without doubt; anything else is the person's
 *  to fill in, so a query never runs on a period the question did not ask for. */
export function periodFromQuestion(question: string, today: Date): string | null {
  const q = question.toLowerCase()
  const year = today.getFullYear()
  let m = q.match(/(\d{4})\s*년\s*(\d{1,2})\s*월/) ?? q.match(/\b(\d{4})-(\d{1,2})\b(?!-)/)
  if (m) { const mo = +m[2]; return mo >= 1 && mo <= 12 ? months(+m[1], mo, mo) : null }
  m = q.match(/(?:(\d{4})\s*년\s*)?([1-4])\s*분기/)
  if (m) { const y = m[1] ? +m[1] : year, s = 3 * (+m[2] - 1) + 1; return months(y, s, s + 2) }
  m = q.match(/(?:(\d{4})\s*년\s*)?(상|하)반기/)
  if (m) { const y = m[1] ? +m[1] : year; return m[2] === "상" ? months(y, 1, 6) : months(y, 7, 12) }
  m = q.match(/(?:^|[^\d])(\d{1,2})\s*월/)
  if (m) { const mo = +m[1]; return mo >= 1 && mo <= 12 ? months(year, mo, mo) : null }
  m = q.match(/(\d{4})\s*년/)
  if (m) return months(+m[1], 1, 12)
  if (/지난\s*달|전월|last month/.test(q)) return "last_month"
  if (/이번\s*달|당월|this month/.test(q)) return "this_month"
  if (/작년|전년|last year/.test(q)) return "last_year"
  if (/올해|금년|this year/.test(q)) return "this_year"
  return null
}

/** The citation's half-open [start, end) as the inclusive range a person reads. */
export function periodLabel(period: [string, string] | null | undefined): string {
  if (!period) return "all time"
  const end = new Date(`${period[1]}T00:00:00Z`)
  end.setUTCDate(end.getUTCDate() - 1)
  return `${period[0]} – ${end.toISOString().slice(0, 10)}`
}

type JoinKey = { catalog: string; from_table: string; to_table: string; on_columns: string[][] }

/** Whether a relationship edge is already an approved join, in either direction — such an
 *  edge is not a candidate any more. */
export function edgeApproved(edge: RelationshipEdge, joins: JoinKey[], catalogs: CatalogEntry[]): boolean {
  const key = (j: JoinKey) =>
    [j.catalog.toLowerCase(), j.from_table, j.to_table, JSON.stringify(j.on_columns)].join("|")
  const approved = new Set(joins.map(key))
  return [false, true].some(rev => {
    const body = joinCandidatePayload(edge, catalogs, rev)
    return !!body && approved.has(key(body))
  })
}
