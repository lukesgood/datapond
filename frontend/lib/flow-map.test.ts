import { test } from "node:test"
import assert from "node:assert/strict"
import { NODE_W, COL_GAP, PAD, edgePath, filterFlow, layout, needsAttention, neighbours, stateText, type Flow } from "./flow-map.ts"

const flow: Flow = {
  nodes: [
    { id: "source:c1", kind: "source", name: "Orders DB", column: 0, connector_type: "postgresql" },
    { id: "raw.orders", kind: "table", name: "orders", namespace: "raw", column: 1, state: "ok", at: "x" },
    { id: "raw.customers", kind: "table", name: "customers", namespace: "raw", column: 1, state: "stale" },
    { id: "refined.customers", kind: "table", name: "customers", namespace: "refined", column: 2, state: "failed", at: "x", stale_input: ["raw.customers"] },
    { id: "serving.rev", kind: "table", name: "rev", namespace: "serving", column: 3, state: "ok", stale_input: ["refined.customers"] },
    { id: "refined.orders_clean", kind: "table", name: "orders_clean", namespace: "refined", column: 2, state: "ok" },
  ],
  edges: [
    { from: "source:c1", to: "raw.orders", kind: "sync" },
    { from: "source:c1", to: "raw.customers", kind: "sync" },
    { from: "raw.customers", to: "refined.customers", kind: "transform" },
    { from: "refined.customers", to: "serving.rev", kind: "transform" },
    { from: "raw.orders", to: "refined.orders_clean", kind: "transform" },
  ],
}

test("layout puts columns left to right and labels them by namespace", () => {
  const l = layout(flow)
  const at = (id: string) => l.placed.find(p => p.id === id)!
  assert.equal(at("source:c1").x, PAD)
  assert.equal(at("raw.orders").x, PAD + NODE_W + COL_GAP)
  assert.deepEqual(l.columns.map(c => c.label), ["Sources", "raw", "refined", "serving"])
  // refined.orders_clean follows raw.orders' row, refined.customers raw.customers'
  assert.ok(at("refined.orders_clean").y < at("refined.customers").y === at("raw.orders").y < at("raw.customers").y)
})

test("a serving table two steps from raw still sits in the serving column", () => {
  const f: Flow = { nodes: [...flow.nodes, { id: "serving.funnel", kind: "table", name: "funnel", namespace: "serving", column: 2, state: "ok" }],
                    edges: [...flow.edges, { from: "raw.orders", to: "serving.funnel", kind: "transform" }] }
  const l = layout(f)
  assert.equal(l.placed.find(p => p.id === "serving.funnel")!.x, l.placed.find(p => p.id === "serving.rev")!.x)
  assert.deepEqual(l.columns.map(c => c.label), ["Sources", "raw", "refined", "serving"])
})

test("needs attention keeps the troubled tables and their direct inputs", () => {
  assert.equal(needsAttention(flow.nodes[1]), false)
  assert.equal(needsAttention(flow.nodes[3]), true)
  const f = filterFlow(flow, "", true)
  assert.deepEqual(f.nodes.map(n => n.id).sort(), ["raw.customers", "refined.customers", "serving.rev", "source:c1"])
  assert.equal(f.edges.length, 3)
  assert.deepEqual(filterFlow(flow, "orders", false).nodes.filter(n => n.kind === "table").map(n => n.id), ["raw.orders", "refined.orders_clean"])
})

test("stateText, neighbours, edgePath", () => {
  const ago = () => "2 h ago"
  assert.equal(stateText(flow.nodes[3], ago), "failed 2 h ago")
  assert.equal(stateText(flow.nodes[1], ago), "ran 2 h ago")
  assert.deepEqual(neighbours(flow, "refined.customers"), { reads: ["raw.customers"], readBy: ["serving.rev"] })
  assert.match(edgePath({ x: 0, y: 0 }, { x: 250, y: 76 }), /^M180 27 C/)
})
