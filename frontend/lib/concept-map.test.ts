import { test } from "node:test"
import assert from "node:assert/strict"
import { columnsByRole, conceptTables, impactLines, impactUrl, metricsAcross, narrower, ontologyGraph, ontologyLayout, relatedConcepts, sourcesOf, type Impact } from "./concept-map.ts"
import type { Binding, Concept } from "./concepts.ts"
import type { Flow } from "./flow-map.ts"

const B = (id: number, concept: string, table: string, column: string, role: Binding["role"], filter_sql: string | null = null,
           status: Binding["status"] = "approved"): Binding =>
  ({ id, concept, catalog: "iceberg", namespace: "default", table, column, role, filter_sql, status, source: "manual", evidence: "" })
const BINDINGS = [
  B(1, "주문", "orders", "id", "key"),
  B(2, "고객", "orders", "customer_id", "key"),
  B(3, "고객", "customers", "id", "key"),
  B(4, "고객", "customers", "email", "attribute"),
  B(5, "고객 문의", "support_tickets", "id", "key"),
  B(6, "고객", "support_tickets", "customer_id", "key"),
  B(7, "취소 주문", "orders", "status", "filter", "status = 'cancelled'"),
  B(8, "상품", "orders", "product_id", "key", null, "proposed"),
]
const CONCEPTS: Concept[] = [
  { name: "고객", parent: null, pii: true, terms: ["customer"] },
  { name: "주문", parent: null, pii: false, terms: [] },
  { name: "고객 문의", parent: null, pii: false, terms: [] },
  { name: "취소 주문", parent: "주문", pii: false, terms: [] },
  { name: "플래티넘 고객", parent: "고객", pii: false, terms: [] },
  { name: "상품", parent: null, pii: false, terms: [] },
]

test("relatedConcepts: shared key tables, via this concept's column, approved only", () => {
  assert.deepEqual(relatedConcepts("고객", BINDINGS), [
    { concept: "고객 문의", via: [{ table: "iceberg.default.support_tickets", column: "customer_id" }] },
    { concept: "주문", via: [{ table: "iceberg.default.orders", column: "customer_id" }] },
  ])
  assert.deepEqual(relatedConcepts("주문", BINDINGS).map(r => r.concept), ["고객"])
})

test("narrower and columnsByRole", () => {
  assert.deepEqual(narrower("고객", CONCEPTS).map(c => c.name), ["플래티넘 고객"])
  const c = columnsByRole("고객", BINDINGS)
  assert.equal(c.keys.length, 3)
  assert.deepEqual(c.attributes, [{ table: "iceberg.default.customers", column: "email", filter_sql: null }])
  assert.deepEqual(conceptTables("고객", BINDINGS), ["iceberg.default.customers", "iceberg.default.orders", "iceberg.default.support_tickets"])
})

test("sourcesOf reads sync and stream writers from the flow map", () => {
  const flow: Flow = {
    nodes: [{ id: "source:3", kind: "source", name: "src_sample_e_commerce_db", column: 0 },
            { id: "default.customers", kind: "table", name: "customers", namespace: "default", column: 1 },
            { id: "default.vip", kind: "table", name: "vip", namespace: "default", column: 2 }],
    edges: [{ from: "source:3", to: "default.customers", kind: "sync" },
            { from: "default.customers", to: "default.vip", kind: "transform", via: "vip" }],
  }
  assert.deepEqual(sourcesOf(flow, ["iceberg.default.customers", "iceberg.default.vip"]),
    [{ table: "iceberg.default.customers", from: "src_sample_e_commerce_db", kind: "sync" }])
  assert.deepEqual(sourcesOf(null, ["x"]), [])
})

test("ontologyGraph derives shares lines, narrower lines and segments", () => {
  const g = ontologyGraph(CONCEPTS, BINDINGS)
  const shares = g.edges.filter(e => e.kind === "shares").map(e => `${e.from}-${e.to}:${e.via.join(",")}`).sort()
  assert.deepEqual(shares, ["고객-고객 문의:support_tickets", "고객-주문:orders"])
  assert.ok(g.edges.some(e => e.kind === "narrower" && e.from === "주문" && e.to === "취소 주문"))
  assert.equal(g.nodes.find(n => n.name === "취소 주문")!.segment, true)
  assert.equal(g.nodes.find(n => n.name === "상품")!.tables, 0)            // proposed binding does not count
})

test("ontologyLayout places every node, satellites near the parent, centred view keeps depth 1", () => {
  const g = ontologyGraph(CONCEPTS, BINDINGS)
  const all = ontologyLayout(g)
  for (const n of all.nodes) assert.ok(all.pos[n.name], n.name)
  const p = all.pos["주문"], s = all.pos["취소 주문"]
  assert.ok(Math.hypot(p.x - s.x, p.y - s.y) <= 121)
  const c = ontologyLayout(g, "고객")
  assert.deepEqual(c.pos["고객"], { x: 0, y: 0 })
  assert.deepEqual(c.nodes.map(n => n.name).sort(), ["고객", "고객 문의", "주문", "플래티넘 고객"].sort())
  assert.ok(c.edges.every(e => e.from === "고객" || e.to === "고객"))
})

const IMPACT: Impact = {
  metrics: [{ name: "revenue", label: "Revenue", version: 3 }],
  concepts: [{ concept: "주문", column: "id", role: "key", filter_sql: null }, { concept: "고객", column: "customer_id", role: "key", filter_sql: null },
             { concept: "주문", column: "x", role: "attribute", filter_sql: null }],
  dashboards: [{ id: "d1", name: "a" }, { id: "d2", name: "b" }],
  queries: { calls: 68, people: 2, services: 1, service_calls: 41, callers: [] },
}

test("impactLines and impactUrl", () => {
  assert.deepEqual(impactLines(IMPACT, 30), [
    { kind: "metrics", text: "revenue v3" }, { kind: "concepts", text: "주문 · 고객" },
    { kind: "dashboards", text: "2 dashboards" }, { kind: "queries", text: "68× in 30 days · 2 people, 1 key (41×)" }])
  assert.deepEqual(impactLines(null, 30), [])
  assert.equal(impactUrl(["iceberg.default.orders", "a b.c.d"]), "/api/catalog/impact?table=iceberg.default.orders&table=a%20b.c.d")
  assert.deepEqual(metricsAcross({ days: 30, tables: { a: IMPACT, b: IMPACT } }).map(m => m.name), ["revenue"])
})

test("askSql counts a segment's rows or a concept's key", async () => {
  const { askSql } = await import("./concept-map.ts")
  assert.equal(askSql("취소 주문", BINDINGS), `SELECT count(*) AS "취소 주문"\nFROM "iceberg"."default"."orders"\nWHERE status = 'cancelled'`)
  assert.equal(askSql("고객", BINDINGS), `SELECT count(DISTINCT "id") AS "고객"\nFROM "iceberg"."default"."customers"`)
  assert.equal(askSql("상품", BINDINGS), null)
})
