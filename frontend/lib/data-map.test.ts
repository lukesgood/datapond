import { test } from "node:test"
import assert from "node:assert/strict"
import { conceptsAround, flowKey, lineageAround, lineageLayout, modeFrom, schemaNeighbours } from "./data-map.ts"
import type { Flow } from "./flow-map.ts"
import type { Binding, Concept } from "./concepts.ts"
import type { Neighbour, RelEdge } from "./relationship-view.ts"

test("modeFrom falls back to relationships", () => {
  assert.equal(modeFrom("lineage"), "lineage")
  assert.equal(modeFrom("nope"), "relationships")
  assert.equal(modeFrom(null), "relationships")
})

test("flowKey drops the catalog", () => {
  assert.equal(flowKey("iceberg.default.Orders"), "default.orders")
})

const FLOW: Flow = {
  nodes: [
    { id: "src:c2", kind: "source", name: "Shop DB", column: 0 },
    { id: "default.orders", kind: "table", name: "orders", namespace: "default", column: 1 },
    { id: "default.customers", kind: "table", name: "customers", namespace: "default", column: 1 },
    { id: "serving.daily_sales", kind: "table", name: "daily_sales", namespace: "serving", column: 2 },
    { id: "serving.weekly", kind: "table", name: "weekly", namespace: "serving", column: 3 },
    { id: "default.unrelated", kind: "table", name: "unrelated", namespace: "default", column: 1 },
  ],
  edges: [
    { from: "src:c2", to: "default.orders", kind: "sync" },
    { from: "src:c2", to: "default.customers", kind: "sync" },
    { from: "default.orders", to: "serving.daily_sales", kind: "transform", via: "daily" },
    { from: "default.customers", to: "serving.daily_sales", kind: "transform", via: "daily" },
    { from: "serving.daily_sales", to: "serving.weekly", kind: "transform", via: "weekly" },
  ],
}

test("lineageAround walks up and down from the centre", () => {
  const l = lineageAround(FLOW, "iceberg.default.orders")
  assert.equal(l.found, true)
  const lanes = Object.fromEntries(l.nodes.map(n => [n.id, n.lane]))
  assert.deepEqual(lanes, { "default.orders": 0, "src:c2": -1, "serving.daily_sales": 1, "serving.weekly": 2 })
  // customers feeds daily_sales but is not upstream of orders: not on this map.
  assert.equal(l.nodes.some(n => n.id === "default.customers"), false)
  assert.deepEqual(l.edges.map(e => `${e.from}>${e.to}`).sort(),
    ["default.orders>serving.daily_sales", "serving.daily_sales>serving.weekly", "src:c2>default.orders"])
})

test("lineageAround says when the table is not on the flow map", () => {
  assert.deepEqual(lineageAround(FLOW, "iceberg.raw.nothing"), { nodes: [], edges: [], found: false })
})

test("lineageAround honours the hop limits", () => {
  const l = lineageAround(FLOW, "iceberg.default.orders", 3, 1)
  assert.equal(l.nodes.some(n => n.id === "serving.weekly"), false)
})

test("lineageLayout puts lanes in columns", () => {
  const l = lineageAround(FLOW, "iceberg.default.orders")
  const pos = lineageLayout(l.nodes, 100, 50)
  assert.ok(pos["src:c2"].x < pos["default.orders"].x)
  assert.ok(pos["default.orders"].x < pos["serving.daily_sales"].x)
})

const edge = (source: string, target: string, l: string, r: string, extra: Partial<RelEdge> = {}): RelEdge =>
  ({ source, target, count: 0, evidence: "fk", joins: [{ left_column: l, right_column: r, count: 0 }], ...extra })
const nb = (other: string, e: RelEdge, evidence: Neighbour["evidence"] = "fk"): Neighbour =>
  ({ other, evidence, count: e.count, declared: evidence === "fk", on: "x", edge: e })

test("schemaNeighbours marks join columns on both sides and leaves guesses out", () => {
  const c = "iceberg.default.orders"
  const around = [
    nb("iceberg.default.customers", edge(c, "iceberg.default.customers", "customer_id", "id")),
    nb("iceberg.default.order_items", edge("iceberg.default.order_items", c, "order_id", "id")),
    nb("iceberg.default.guess", edge(c, "iceberg.default.guess", "x", "y"), "candidate"),
  ]
  const s = schemaNeighbours(c, around)
  assert.deepEqual(s.centre.joinColumns.sort(), ["customer_id", "id"])
  assert.deepEqual(s.others.map(o => [o.id, o.joinColumns]), [
    ["iceberg.default.customers", ["id"]], ["iceberg.default.order_items", ["order_id"]]])
})

const CONCEPTS: Concept[] = [
  { name: "고객", parent: null, pii: true, terms: [] },
  { name: "주문", parent: null, pii: false, terms: [] },
  { name: "취소 주문", parent: "주문", pii: false, terms: [] },
]
const B = (id: number, concept: string, table: string, column: string, role: Binding["role"],
           status: Binding["status"] = "approved", filter_sql: string | null = null): Binding =>
  ({ id, concept, catalog: "iceberg", namespace: "default", table, column, role, filter_sql, status, source: "manual", evidence: "" })

test("conceptsAround lists the centre's concepts and where else each lives", () => {
  const bindings = [
    B(1, "주문", "orders", "id", "key"),
    B(2, "고객", "orders", "customer_id", "key"),
    B(3, "고객", "customers", "id", "key"),
    B(4, "고객", "customers", "email", "attribute"),
    B(5, "고객", "support_tickets", "customer_id", "key"),
    B(6, "취소 주문", "orders", "status", "filter", "approved", "status = 'cancelled'"),
    B(7, "주문", "order_items", "order_id", "key"),
    B(8, "고객", "invoices", "customer_id", "key", "proposed"),
  ]
  const r = conceptsAround(CONCEPTS, bindings, "iceberg.default.orders")
  assert.deepEqual(r.map(c => c.concept), ["고객", "주문", "취소 주문"])
  const cust = r[0]
  assert.equal(cust.pii, true)
  assert.deepEqual(cust.here, [{ column: "customer_id", role: "key", filter_sql: null }])
  assert.deepEqual(cust.elsewhere.map(e => [e.table, e.columns, e.role]), [
    ["iceberg.default.customers", ["id", "email"], "key"],
    ["iceberg.default.support_tickets", ["customer_id"], "key"]])   // proposed invoices left out
  assert.equal(r[2].here[0].filter_sql, "status = 'cancelled'")
  assert.equal(r[2].parent, "주문")
})
