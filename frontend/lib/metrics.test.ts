import test from "node:test"
import assert from "node:assert/strict"
import { aiSqlMetricView, approvalWarning, fieldError, metricStatusBadge, versionDiff, type MetricVersionRow } from "./metrics.ts"

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
