import test from "node:test"
import assert from "node:assert/strict"
import { aiSqlMetricView, edgeApproved, periodFromQuestion, periodLabel, approvalWarning, fieldError, joinCandidatePayload, metricStatusBadge, pendingApproval, unresolvedJoinDims, versionDiff, type MetricDetail, type MetricVersionRow, type RelationshipEdge } from "./metrics.ts"

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

test("a copied dimension whose join is not matched to an approved join blocks save", () => {
  const ref = { to_table: "sales.customers", on: [["customer_id", "id"]] }
  assert.deepEqual(unresolvedJoinDims([
    { name: "region", join_id: null, joinRef: ref },      // joins not loaded, or no longer approved
    { name: "segment", join_id: 4, joinRef: ref },        // matched
    { name: "channel", join_id: null },                   // a base-table column
  ]), ["region"])
})

test("a period is read from the question, inclusive dates as the server takes them", () => {
  const today = new Date(2026, 9, 16)
  const p = (q: string) => periodFromQuestion(q, today)
  assert.equal(p("2026년 6월 채널별 주문 건수"), "2026-06-01..2026-06-30")
  assert.equal(p("2024년 2월 매출"), "2024-02-01..2024-02-29")
  assert.equal(p("2026-02 orders"), "2026-02-01..2026-02-28")
  assert.equal(p("6월 주문 건수"), "2026-06-01..2026-06-30")          // this year
  assert.equal(p("2026년 상반기 취소율"), "2026-01-01..2026-06-30")
  assert.equal(p("2025년 하반기"), "2025-07-01..2025-12-31")
  assert.equal(p("2026년 3분기 매출"), "2026-07-01..2026-09-30")
  assert.equal(p("2025년 매출"), "2025-01-01..2025-12-31")
  assert.equal(p("지난달 매출"), "last_month")
  assert.equal(p("revenue last month"), "last_month")
  assert.equal(p("이번 달 주문"), "this_month")
  assert.equal(p("올해 매출"), "this_year")
  assert.equal(p("작년 매출"), "last_year")
  assert.equal(p("주문 건수"), null)
  assert.equal(p("2026년 13월"), null)
})

test("a half-open period from the citation is shown with its inclusive end", () => {
  assert.equal(periodLabel(["2026-06-01", "2026-07-01"]), "2026-06-01 – 2026-06-30")
  assert.equal(periodLabel(null), "all time")
})

test("a candidate already approved, either way round, is not offered again", () => {
  const cats = [{ name: "demo", engine_catalog: "awsdatacatalog" }]
  const edge = { source: "awsdatacatalog.shop.order_items", target: "awsdatacatalog.shop.products",
    evidence: "naming", count: 1, joins: [{ left_column: "product_id", right_column: "id" }] }
  const join = { catalog: "demo", from_table: "shop.order_items", to_table: "shop.products", on_columns: [["product_id", "id"]] }
  assert.equal(edgeApproved(edge, [join], cats), true)
  // Approved reversed: the edge came alphabetically the other way.
  assert.equal(edgeApproved({ ...edge, source: edge.target, target: edge.source,
    joins: [{ left_column: "id", right_column: "product_id" }] }, [join], cats), true)
  assert.equal(edgeApproved(edge, [{ ...join, to_table: "shop.orders" }], cats), false)
  assert.equal(edgeApproved(edge, [], cats), false)
})
