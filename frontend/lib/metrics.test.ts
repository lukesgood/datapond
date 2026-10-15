import test from "node:test"
import assert from "node:assert/strict"
import { aiSqlMetricView, approvalWarning, fieldError, joinCandidatePayload, metricStatusBadge, pendingApproval, retryWithoutPeriod, versionDiff, type MetricDetail, type MetricVersionRow, type RelationshipEdge } from "./metrics.ts"

test("status badge: approved with a version, draft, retired", () => {
  assert.deepEqual(metricStatusBadge({ status: "approved", current_version: 3 }), { label: "v3", tone: "ok" })
  assert.deepEqual(metricStatusBadge({ status: "draft", current_version: null }), { label: "draft", tone: "draft" })
  assert.deepEqual(metricStatusBadge({ status: "retired", current_version: 2 }), { label: "retired", tone: "retired" })
})

test("version diff names changed fields only", () => {
  const a: MetricVersionRow = { version: 1, measure: "SUM(a)", filters: null, time_column: "t", grains: ["month"], max_period_days: 366, dimensions: [{ name: "c", column: "c" }], base_table: "s.o", catalog: "glue" }
  const b: MetricVersionRow = { ...a, version: 2, measure: "SUM(b)", grains: ["month", "day"] }
  assert.deepEqual(versionDiff(a, b), ["measure: SUM(a) → SUM(b)", "grains: month → month, day"])
  assert.deepEqual(versionDiff(undefined, b), ["first version"])
})

test("field error reads the router's 422 detail", () => {
  assert.deepEqual(fieldError({ field: "measure", message: "SUBQUERY is not allowed here." }),
    { field: "measure", message: "SUBQUERY is not allowed here." })
  assert.equal(fieldError("plain string"), null)
  assert.equal(fieldError(undefined), null)
})

test("ai sql view: chips and a suggestion only when present", () => {
  assert.deepEqual(aiSqlMetricView({ metrics_provided: ["revenue@v3"], suggested_metric: { name: "revenue" } }),
    { chips: ["revenue v3"], suggestion: "revenue" })
  assert.deepEqual(aiSqlMetricView({}), { chips: [], suggestion: null })
})

test("approval warns unless partitioning is known", () => {
  assert.match(approvalWarning("unknown") ?? "", /full scan/i)
  assert.equal(approvalWarning("partitioned"), null)
})

const EDGE: RelationshipEdge = {
  source: "awsdatacatalog.sales.orders", target: "awsdatacatalog.sales.customers",
  evidence: "observed", count: 4, joins: [{ left_column: "customer_id", right_column: "id" }],
}
const CATALOGS = [{ name: "glue_main", engine_catalog: "awsdatacatalog" }]

test("join candidate payload maps the engine catalog to the registry name", () => {
  assert.deepEqual(joinCandidatePayload(EDGE, CATALOGS), {
    catalog: "glue_main", from_table: "sales.orders", to_table: "sales.customers",
    on_columns: [["customer_id", "id"]], source: "history",
  })
})

test("join candidate payload falls back to the raw catalog when there is no mapping", () => {
  assert.equal(joinCandidatePayload(EDGE, [])?.catalog, "awsdatacatalog")
  assert.equal(joinCandidatePayload({ ...EDGE, evidence: "candidate" }, [])?.source, "naming")
})

test("reversed swaps the tables and the column pair", () => {
  const p = joinCandidatePayload(EDGE, CATALOGS, true)
  assert.equal(p?.from_table, "sales.customers")
  assert.equal(p?.to_table, "sales.orders")
  assert.deepEqual(p?.on_columns, [["id", "customer_id"]])
})

test("join candidate payload is null without a column pair or across catalogs", () => {
  assert.equal(joinCandidatePayload({ ...EDGE, joins: [] }, CATALOGS), null)
  assert.equal(joinCandidatePayload({ ...EDGE, target: "other.sales.customers" }, CATALOGS), null)
})

test("version diff shows a dimension's column and join, so those changes are visible", () => {
  const a: MetricVersionRow = { version: 1, measure: "SUM(a)", filters: null, time_column: null, grains: [], max_period_days: 366, dimensions: [{ name: "region", column: "region" }], base_table: "s.o", catalog: "glue" }
  const b: MetricVersionRow = { ...a, version: 2, dimensions: [{ name: "region", column: "region", join: { to_table: "s.customers", on: [["customer_id", "id"]] } }] }
  assert.deepEqual(versionDiff(a, b), ["dimensions: region:region → region:s.customers.region"])
  const c: MetricVersionRow = { ...a, version: 3, dimensions: [{ name: "region", column: "area" }] }
  assert.deepEqual(versionDiff(a, c), ["dimensions: region:region → region:area"])
})

test("version diff survives null entries in a list", () => {
  const a = { version: 1, grains: null } as unknown as MetricVersionRow
  const b = { version: 2, grains: [null, "day"] } as unknown as MetricVersionRow
  assert.deepEqual(versionDiff(a, b), ["grains: — → —, day"])
})

const DETAIL = {
  metric: { name: "revenue", status: "approved" }, versions: [], broken: false, broken_reason: null,
  example_sql: null, partition_info: "unknown", recent_queries: 0,
  pending: { version: 2, catalog: "glue", base_table: "s.o", measure: "SUM(b)", filters: null, example_sql: "SELECT 2" },
} as unknown as MetricDetail

test("pending approval: the server's pending version, never on a retired metric", () => {
  assert.equal(pendingApproval(DETAIL)?.version, 2)
  assert.equal(pendingApproval({ ...DETAIL, pending: null }), null)
  assert.equal(pendingApproval({ ...DETAIL, metric: { ...DETAIL.metric, status: "retired" } }), null)
  assert.equal(pendingApproval(null), null)
})

test("metric query retries without a period only when the metric has no time column", () => {
  assert.equal(retryWithoutPeriod(400, "This metric has no time column; omit period."), true)
  assert.equal(retryWithoutPeriod(400, "Unknown dimension 'x'."), false)
  assert.equal(retryWithoutPeriod(404, "This metric has no time column; omit period."), false)
})
