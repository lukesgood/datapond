/** Concept bindings matrix (./concepts.ts). */
import assert from "node:assert/strict"
import { test } from "node:test"
import {
  bindingText, cell, conceptRows, coverage, matchesSearch, matrixTables, suggestionBody, tableLabel,
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
