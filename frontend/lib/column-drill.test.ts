import { test } from "node:test"
import assert from "node:assert/strict"
import { bindingBody, conditionFor, joinPartners, meaningOf, newConceptProblem, parentSuggestion, share, valuesUrl } from "./column-drill.ts"
import type { Binding, Concept } from "./concepts.ts"

test("valuesUrl encodes every part", () => {
  assert.equal(valuesUrl("iceberg.default.orders", "status"),
    "/api/catalog/tables/default/orders/columns/status/values?catalog=iceberg")
})

test("conditionFor types the literal", () => {
  assert.equal(conditionFor("status", "cancelled", "varchar"), "status = 'cancelled'")
  assert.equal(conditionFor("name", "O'Neil", "varchar(40)"), "name = 'O''Neil'")
  assert.equal(conditionFor("tier_id", "3", "bigint"), "tier_id = 3")
  assert.equal(conditionFor("tier_id", "3a", "bigint"), "tier_id = '3a'")
  assert.equal(conditionFor("active", "true", "boolean"), "active = true")
  assert.equal(conditionFor("day", "2026-11-20", "date"), "day = DATE '2026-11-20'")
})

test("share rounds and marks tiny shares", () => {
  assert.equal(share(2953, 6000), "49%")
  assert.equal(share(2, 6000), "<1%")
  assert.equal(share(0, 6000), "0%")
  assert.equal(share(1, 0), "—")
})

const B = (id: number, concept: string, table: string, column: string, role: Binding["role"], filter_sql: string | null = null,
           status: Binding["status"] = "approved"): Binding =>
  ({ id, concept, catalog: "iceberg", namespace: "default", table, column, role, filter_sql, status, source: "manual", evidence: "" })
const BINDINGS = [
  B(1, "주문", "orders", "id", "key"),
  B(2, "고객", "orders", "customer_id", "key"),
  B(3, "취소 주문", "orders", "status", "filter", "status = 'cancelled'"),
  B(4, "배송 완료 주문", "orders", "status", "filter", "status = 'delivered'"),
  B(5, "보류 주문", "orders", "status", "filter", "status = 'pending'", "proposed"),
]

test("meaningOf lists approved segments and bindings on the column", () => {
  const m = meaningOf(BINDINGS, "iceberg.default.orders", "STATUS")
  assert.deepEqual(m.segments.map(s => s.concept), ["취소 주문", "배송 완료 주문"])
  assert.deepEqual(meaningOf(BINDINGS, "iceberg.default.orders", "customer_id").concepts, [{ concept: "고객", role: "key" }])
})

test("parentSuggestion prefers the table's own id key", () => {
  assert.equal(parentSuggestion(BINDINGS, "iceberg.default.orders"), "주문")
  assert.equal(parentSuggestion(BINDINGS, "iceberg.default.nothing"), null)
})

test("joinPartners reads both directions of declared keys", () => {
  const keys = { primary: ["id"], foreign: [{ column: "customer_id", ref_table: "iceberg.default.customers", ref_column: "id", via: "lake" as const }],
                 referenced_by: [{ table: "iceberg.default.order_items", column: "order_id", ref_column: "id" }] }
  assert.deepEqual(joinPartners(keys, "customer_id"), [{ table: "iceberg.default.customers", column: "id", direction: "refers to" }])
  assert.deepEqual(joinPartners(keys, "id"), [{ table: "iceberg.default.order_items", column: "order_id", direction: "referred to by" }])
  assert.deepEqual(joinPartners(null, "id"), [])
})

test("newConceptProblem refuses empty and existing names", () => {
  const cs: Concept[] = [{ name: "취소 주문", parent: "주문", pii: false, terms: [] }]
  assert.equal(newConceptProblem("  ", cs), "Name the segment.")
  assert.match(newConceptProblem("취소 주문", cs) ?? "", /already exists/)
  assert.equal(newConceptProblem("보류 주문", cs), null)
})

test("bindingBody splits the table id and keeps a filter only for segments", () => {
  assert.deepEqual(bindingBody("iceberg.default.orders", "status", "보류 주문", "filter", "status = 'pending'", "e"), {
    concept: "보류 주문", catalog: "iceberg", table: "default.orders", column: "status", role: "filter",
    filter_sql: "status = 'pending'", source: "manual", evidence: "e", status: "approved" })
  assert.equal(bindingBody("iceberg.default.orders", "status", "x", "attribute", "ignored", "e").filter_sql, null)
})
