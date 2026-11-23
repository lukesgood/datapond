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
import { hubs, neighbours, egoLayout, evidenceLabel, searchTables, findNodeId, type RelGraph } from "./relationship-view.ts"

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

test("a node id reads as catalog, namespace and table in either shape", async () => {
  const { splitTableId, tableHref } = await import("./relationship-view.ts")
  assert.deepEqual(splitTableId("finance.ledger.entries"),
                   { catalog: "finance", namespace: "ledger", table: "entries" })
  assert.deepEqual(splitTableId("sales.orders"),
                   { catalog: null, namespace: "sales", table: "orders" })
  assert.equal(tableHref("finance.ledger.entries"), "/catalog/ledger/entries?catalog=finance")
  assert.equal(tableHref("sales.orders"), "/catalog/sales/orders")
})

test("with one catalog, names drop it; with several, they keep it", async () => {
  const { soleCatalog, displayId } = await import("./relationship-view.ts")
  const one: RelGraph = { nodes: [
    { id: "awsdatacatalog.default.orders", query_count: 1, columns: [] },
    { id: "awsdatacatalog.default.customers", query_count: 1, columns: [] }], edges: [] }
  const sole = soleCatalog(one)
  assert.equal(sole, "awsdatacatalog")
  assert.equal(displayId("awsdatacatalog.default.orders", sole), "default.orders")
  assert.equal(displayId("awsdatacatalog.default.orders.id = awsdatacatalog.default.customers.id", sole),
               "default.orders.id = default.customers.id")

  const two: RelGraph = { nodes: [
    { id: "finance.ledger.entries", query_count: 1, columns: [] },
    { id: "sales.default.orders", query_count: 1, columns: [] }], edges: [] }
  assert.equal(soleCatalog(two), null)
  assert.equal(displayId("finance.ledger.entries", soleCatalog(two)), "finance.ledger.entries")
  assert.equal(soleCatalog({ nodes: [{ id: "sales.orders", query_count: 0, columns: [] }], edges: [] }), null)
})

test("only a leading catalog is dropped, not a namespace that shares its name", async () => {
  const { displayId } = await import("./relationship-view.ts")
  assert.equal(displayId("sales.sales.orders", "sales"), "sales.orders")
})

test("findNodeId matches either catalog name, or a two-part id", () => {
  const g = { nodes: [
    { id: "awsdatacatalog.default.orders", query_count: 1, columns: [] },
    { id: "polaris_lake.default.orders", query_count: 1, columns: [] },
    { id: "public.users", query_count: 1, columns: [] },
  ], edges: [] }
  assert.equal(findNodeId(g, ["AwsDataCatalog", "iceberg"], "default", "orders"), "awsdatacatalog.default.orders")
  assert.equal(findNodeId(g, ["polaris", "polaris_lake"], "default", "orders"), "polaris_lake.default.orders")
  assert.equal(findNodeId(g, ["x"], "public", "users"), "public.users")
  assert.equal(findNodeId(g, ["x"], "default", "orders"), null)
})

test("declared keys: shown without asking, after run joins, with a JOIN to open", () => {
  const g: RelGraph = {
    nodes: [{ id: "i.d.orders", query_count: 3, columns: [] }, { id: "i.d.customers", query_count: 1, columns: [] },
            { id: "i.d.items", query_count: 0, columns: [] }, { id: "i.d.notes", query_count: 0, columns: [] }],
    edges: [
      { source: "i.d.customers", target: "i.d.orders", count: 4, evidence: "fk", via: "lake", joins: [{ left_column: "id", right_column: "customer_id", count: 4 }] },
      { source: "i.d.items", target: "i.d.orders", count: 0, evidence: "fk", via: "source", joins: [{ left_column: "order_id", right_column: "id", count: 0 }] },
      { source: "i.d.notes", target: "i.d.orders", count: 0, evidence: "candidate", joins: [] },
    ],
  }
  const n = neighbours(g, "i.d.orders")
  assert.deepEqual(n.map(x => x.other), ["i.d.customers", "i.d.items"])
  assert.equal(evidenceLabel(n[0]), "run 4× · key (from source)")
  assert.equal(evidenceLabel(n[1]), "declared key")
  assert.match(n[1].joinSql ?? "", /JOIN i\.d\.orders ON i\.d\.items\.order_id = i\.d\.orders\.id/)
  const h = hubs(g)
  assert.equal(h[0].id, "i.d.orders"); assert.equal(h[0].observed, 1); assert.equal(h[0].declared, 2)
})
