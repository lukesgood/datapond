/** The table-centred relationship view (./relationship-view.ts).
 *
 *  The catalog drew every table on one ring with every join labelled, and guesses from
 *  column naming mixed in with joins people ran. Past a dozen tables it was a knot of
 *  crossing lines. The question someone brings to this screen is about one table —
 *  what does it join to, and on what — so the view starts from a table: its
 *  neighbours ranked by how often the join was actually run, guesses hidden unless
 *  asked for, and only that neighbourhood drawn.
 */
import assert from "node:assert/strict"
import { test } from "node:test"
import { hubs, neighbours, egoLayout, searchTables, type RelGraph } from "./relationship-view.ts"

const g: RelGraph = {
  nodes: [
    { id: "sales.orders", query_count: 40, columns: [] },
    { id: "sales.customers", query_count: 25, columns: [] },
    { id: "sales.products", query_count: 10, columns: [] },
    { id: "hr.employees", query_count: 0, columns: [] },
    { id: "ops.shipments", query_count: 5, columns: [] },
  ],
  edges: [
    { source: "sales.customers", target: "sales.orders", count: 12, evidence: "observed",
      joins: [{ left_column: "id", right_column: "customer_id", count: 12 }],
      join_sql: "SELECT * FROM sales.orders o JOIN sales.customers c ON c.id = o.customer_id" },
    { source: "sales.orders", target: "sales.products", count: 3, evidence: "observed",
      joins: [{ left_column: "product_id", right_column: "id", count: 3 }] },
    { source: "ops.shipments", target: "sales.orders", count: 0, evidence: "candidate",
      reason: "shipments.order_id looks like orders.id",
      joins: [{ left_column: "order_id", right_column: "id", count: 0 }] },
    { source: "hr.employees", target: "sales.customers", count: 0, evidence: "candidate",
      joins: [{ left_column: "id", right_column: "id", count: 0 }] },
  ],
}

test("hubs rank tables by joins people ran, then by queries", () => {
  const h = hubs(g, 3)
  assert.deepEqual(h.map(x => x.id), ["sales.orders", "sales.customers", "sales.products"])
  assert.equal(h[0].observed, 2)
  assert.equal(h[0].candidates, 1)
})

test("a table's neighbours are the observed joins, most-run first; guesses are hidden", () => {
  const n = neighbours(g, "sales.orders")
  assert.deepEqual(n.map(x => x.other), ["sales.customers", "sales.products"])
  assert.equal(n[0].count, 12)
  assert.equal(n[0].on, "sales.customers.id = sales.orders.customer_id")
})

test("guesses appear only when asked for, after every observed join", () => {
  const n = neighbours(g, "sales.orders", { includeCandidates: true })
  assert.deepEqual(n.map(x => x.other), ["sales.customers", "sales.products", "ops.shipments"])
  assert.equal(n[2].evidence, "candidate")
})

test("the join keys read from the selected table's side", () => {
  const n = neighbours(g, "sales.customers")
  assert.equal(n[0].on, "sales.customers.id = sales.orders.customer_id")
})

test("the neighbourhood is drawn around the table, capped", () => {
  const n = neighbours(g, "sales.orders", { includeCandidates: true })
  const { nodes, hidden } = egoLayout("sales.orders", n, 2)
  assert.equal(nodes[0].id, "sales.orders")
  assert.deepEqual(nodes[0].position, { x: 0, y: 0 })
  assert.equal(nodes.length, 3)
  assert.equal(hidden, 1)
  const dist = Math.hypot(nodes[1].position.x, nodes[1].position.y)
  assert.ok(dist > 150)
})

test("search matches schema or table, case-insensitively", () => {
  assert.deepEqual(searchTables(g, "CUST").map(t => t.id), ["sales.customers"])
  assert.deepEqual(searchTables(g, "sales.").length, 3)
  assert.deepEqual(searchTables(g, "").length, 0)
})
