import test from "node:test"
import assert from "node:assert/strict"
import { aiSqlMetricView, approvalWarning, fieldError, joinCandidatePayload, metricStatusBadge, versionDiff, type MetricVersionRow, type RelationshipEdge } from "./metrics.ts"

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
