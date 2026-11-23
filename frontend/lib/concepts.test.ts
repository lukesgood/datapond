/** Concept bindings matrix (./concepts.ts). */
import assert from "node:assert/strict"
import { test } from "node:test"
import {
  addCondition, canBecomeSegment, segmentBody, segmentValue, valueCondition, bindingText, cell, conceptChips, conceptWordsFor, shortUse, conceptRows, coverage, maskHref, matchesSearch, matrixTables, parseMaskParam, segmentsFor, suggestionBody, tableLabel,
  type Binding, type Concept, type Suggestion,
} from "./concepts.ts"

const C = (name: string, parent: string | null = null, terms: string[] = []): Concept => ({ name, parent, pii: false, terms })
const B = (concept: string, table: string, column: string, status: "approved" | "proposed" = "approved", extra: Partial<Binding> = {}): Binding => ({
  id: Math.random(), concept, catalog: "iceberg", namespace: "default", table, column, role: "key",
  filter_sql: null, status, source: "manual", evidence: "", ...extra,
})
const S = (concept: string, table: string, column: string): Suggestion => ({
  concept, catalog: "iceberg", namespace: "default", table, column, role: "key", source: "naming", evidence: "name",
})

test("concepts come in tree order with depth; orphans and cycles still appear once", () => {
  const rows = conceptRows([C("VIP 고객", "고객"), C("주문"), C("고객"), C("휴면 고객", "고객"), C("x", "없음"), C("a", "b"), C("b", "a")])
  assert.deepEqual(rows.map(r => [r.concept.name, r.depth]),
    [["x", 0], ["고객", 0], ["VIP 고객", 1], ["휴면 고객", 1], ["주문", 0], ["a", 0], ["b", 1]])
})

test("tables with the most bindings come first; labels drop what every table shares", () => {
  const t = matrixTables([B("고객", "orders", "customer_id"), B("주문", "orders", "id")], [S("고객", "customers", "id")])
  assert.deepEqual(t, ["iceberg.default.orders", "iceberg.default.customers"])
  assert.equal(tableLabel(t[0], t), "orders")
  assert.equal(tableLabel("iceberg.raw.orders", [...t, "iceberg.raw.orders"]), "raw.orders")
  assert.equal(tableLabel("polaris_lake.default.x", [...t, "polaris_lake.default.x"]), "polaris_lake.default.x")
})

test("a cell separates approved, proposed and suggested", () => {
  const c = cell("고객", "iceberg.default.orders", [B("고객", "orders", "customer_id"), B("고객", "orders", "buyer", "proposed"), B("주문", "orders", "id")],
    [S("고객", "orders", "cust"), S("고객", "customers", "id")])
  assert.deepEqual([c.approved.length, c.proposed.length, c.suggested.length], [1, 1, 1])
})

test("coverage counts what waits and names concepts bound nowhere", () => {
  const cov = coverage([C("고객"), C("환불")], [B("고객", "orders", "customer_id"), B("환불", "refunds", "id", "proposed")], [S("고객", "customers", "id")])
  assert.equal(cov.waiting, 2)
  assert.deepEqual(cov.unbound, ["환불"])
})

test("a segment reads as its condition; search finds aliases and columns", () => {
  assert.equal(bindingText({ table: "customers", column: "tier", role: "filter", filter_sql: "tier = 'VIP'" }), "customers: tier = 'VIP'")
  assert.equal(bindingText({ table: "orders", column: "customer_id", role: "key" }), "orders.customer_id")
  const c = C("고객", null, ["customer"])
  assert.ok(matchesSearch(c, "CUST", []))
  assert.ok(matchesSearch(c, "buyer", [B("고객", "payments", "buyer")]))
  assert.ok(!matchesSearch(c, "refund", []))
})

test("a suggestion becomes a binding body with namespace.table", () => {
  assert.deepEqual(suggestionBody(S("고객", "customers", "id"), "rejected"), {
    concept: "고객", catalog: "iceberg", table: "default.customers", column: "id", role: "key",
    source: "naming", evidence: "name", status: "rejected",
  })
})

test("the answer's chips drop catalog and namespace", () => {
  assert.equal(shortUse("iceberg.default.customers WHERE tier = 'platinum'"), "customers: tier = 'platinum'")
  assert.equal(shortUse("iceberg.default.orders.customer_id"), "orders.customer_id")
  assert.equal(shortUse("odd"), "odd")
  assert.deepEqual(conceptChips([{ name: "고객", uses: ["iceberg.default.customers.id"] }]), [{ name: "고객", uses: ["customers.id"] }])
  assert.deepEqual(conceptChips(undefined), [])
})

test("a PII gap links to a prefilled mask, and the link parses back", () => {
  const href = maskHref({ concept: "고객", catalog: "iceberg", namespace: "default", table: "orders", column: "customer_id", key: true })
  assert.equal(href, "/governance?tab=access-control&mask=iceberg.default.orders.customer_id")
  assert.deepEqual(parseMaskParam(new URL(href, "http://x").searchParams.get("mask")),
    { catalog: "iceberg", schema: "default", table: "orders", column: "customer_id" })
  assert.equal(parseMaskParam("a.b.c"), null)
  assert.equal(parseMaskParam("a.b.c.d e"), null)
})

test("segments on the base table feed the metric filter", () => {
  const seg = B("플래티넘 고객", "customers", "tier", "approved", { role: "filter", filter_sql: "tier = 'platinum'" })
  const other = B("취소 주문", "orders", "status", "approved", { role: "filter", filter_sql: "status = 'cancelled'" })
  const waiting = B("활성 고객", "customers", "is_active", "proposed", { role: "filter", filter_sql: "is_active = true" })
  assert.deepEqual(segmentsFor([seg, other, waiting], "iceberg", "default.customers"), [{ concept: "플래티넘 고객", filter_sql: "tier = 'platinum'" }])
  assert.equal(addCondition("", "tier = 'platinum'"), "tier = 'platinum'")
  assert.equal(addCondition("status = 'paid'", "tier = 'platinum'"), "status = 'paid' AND tier = 'platinum'")
  assert.equal(addCondition("tier = 'platinum'", "tier = 'platinum'"), "tier = 'platinum'")
  assert.equal(addCondition("a = 1 OR b = 2", "c = 3 or d = 4"), "(a = 1 OR b = 2) AND (c = 3 or d = 4)")
})

test("a metric label's concept words", () => {
  const cs = [C("고객", null, ["customer", "회원", "VIP 고객"]), C("주문", null, ["order"])]
  assert.deepEqual(conceptWordsFor("고객 수", cs), ["customer", "회원"])
  assert.deepEqual(conceptWordsFor("매출", cs), [])
})

test("a value suggestion becomes a segment binding", () => {
  const v = { table: "iceberg.default.customers", column: "tier", value: "vip", questions: 4, example: "", segments_on_column: true }
  assert.equal(valueCondition(v), "tier = 'vip'")
  assert.equal(valueCondition({ column: "is_active", value: "true" }), "is_active = true")
  assert.equal(valueCondition({ column: "name", value: "O'Neil" }), "name = 'O''Neil'")
  assert.deepEqual(segmentBody(v, "VIP 고객"), {
    concept: "VIP 고객", catalog: "iceberg", table: "default.customers", column: "tier", role: "filter",
    filter_sql: "tier = 'vip'", source: "history", evidence: "used in 4 questions to /ai/sql", status: "approved",
  })
})

test("a guessed value becomes the stored spelling, and a missing one cannot become a segment", () => {
  const v = { table: "iceberg.default.customers", column: "tier", value: "VIP", questions: 2, example: "", segments_on_column: true,
              checked: true, exists: true, rows: 0, actual: "vip", actual_rows: 3 }
  assert.equal(segmentValue(v), "vip")
  assert.equal(segmentBody(v, "VIP 고객").filter_sql, "tier = 'vip'")
  assert.equal(canBecomeSegment(v), true)
  assert.equal(canBecomeSegment({ ...v, actual: undefined, exists: false }), false)
  assert.equal(canBecomeSegment({ ...v, checked: false, exists: undefined }), true)
})
