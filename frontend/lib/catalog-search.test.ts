import { test } from "node:test"
import assert from "node:assert/strict"
import { columnsOf, summaryLine, whyFor, type SearchResult } from "./catalog-search.ts"

const base: SearchResult = { query: "고객", words: ["고객"], tables: [], columns: [], concepts: [], segments: [], metrics: [] }

const R: SearchResult = {
  ...base,
  tables: [
    { catalog: "iceberg", namespace: "default", table: "customers", score: 14, why: ["name", "concept 고객", "4 columns"], columns: ["id"] },
    { catalog: "iceberg", namespace: "default", table: "orders", score: 11, why: ["concept 고객", "1 column"], columns: ["customer_id"] },
  ],
  table_total: 7,
  columns: [
    { catalog: "iceberg", namespace: "default", table: "orders", column: "customer_id", type: "bigint", why: "concept 고객" },
    { catalog: "iceberg", namespace: "default", table: "customers", column: "id", type: "bigint", why: "concept 고객" },
  ],
  column_total: 11,
  concepts: ["고객", "고객 문의", "골드 고객", "플래티넘 고객"].map(name => ({ name, pii: false, terms: [], matched: ["고객"], keys: [], attributes: [], segments: 0 })),
  segments: [1, 2, 3].map(i => ({ concept: "골드 고객", catalog: "iceberg", namespace: "default", table: "customers", column: "tier", filter_sql: `tier = '${i}'` })),
  metrics: [{ name: "customer_count", base_table: "iceberg.default.customers", matched: ["고객"] }],
}

test("summaryLine: counts every group and names up to three concepts", () => {
  assert.equal(summaryLine(R), "7 tables · 11 columns · concepts 고객, 고객 문의, 골드 고객 +1 · 3 segments · 1 metric")
})

test("summaryLine: leaves out zero groups and says null for nothing", () => {
  assert.equal(summaryLine({ ...base, columns: R.columns.slice(0, 1) }), "1 column")
  assert.equal(summaryLine(base), null)
})

test("whyFor: returns reasons without the bare name, null when not found", () => {
  assert.deepEqual(whyFor(R, { catalog: "iceberg", namespace: "default", name: "customers" }), ["concept 고객", "4 columns"])
  assert.deepEqual(whyFor(R, { catalog: "ICEBERG", namespace: "default", name: "Orders" }), ["concept 고객", "1 column"])
  assert.equal(whyFor(R, { catalog: "iceberg", namespace: "default", name: "products" }), null)
  assert.equal(whyFor(null, { catalog: "iceberg", namespace: "default", name: "orders" }), null)
})

test("columnsOf: picks one table's column hits", () => {
  assert.deepEqual(columnsOf(R, "iceberg.default.orders").map(c => c.column), ["customer_id"])
})
