/** The data flow map's layout and reading aids. The graph itself comes from
 *  GET /api/transforms/flow (backend app/flow_map.py). */

export type FlowState = "ok" | "failed" | "running" | "stale" | "never" | "external"
export type FlowNode = {
  id: string
  kind: "source" | "table"
  name: string
  namespace?: string
  connector_type?: string | null
  ref?: string
  column: number
  state?: FlowState
  at?: string | null
  stale_input?: string[] | null
  written_by?: { kind: "sync" | "transform"; ref: string; name: string; dag_id?: string | null; schedule?: string | null } | null
}
export type FlowEdge = { from: string; to: string; kind: "sync" | "transform"; via?: string; ref?: string }
export type Flow = { nodes: FlowNode[]; edges: FlowEdge[]; warnings?: string[]; generated_at?: string }

export const NODE_W = 180
export const NODE_H = 54
export const COL_GAP = 70
export const ROW_GAP = 22
export const PAD = 16

export function needsAttention(n: FlowNode): boolean {
  return n.kind === "table" && (n.state === "failed" || n.state === "stale" || !!n.stale_input?.length)
}

/** Keep what needs attention and its direct inputs, so the cause is one step away
 *  on screen without the rest of the graph. */
export function filterFlow(flow: Flow, query: string, attentionOnly: boolean): Flow {
  let keep = new Set(flow.nodes.map(n => n.id))
  if (attentionOnly) {
    const bad = new Set(flow.nodes.filter(needsAttention).map(n => n.id))
    keep = new Set(bad)
    for (const e of flow.edges) if (bad.has(e.to)) keep.add(e.from)
  }
  const q = query.trim().toLowerCase()
  const nodes = flow.nodes.filter(n => keep.has(n.id) && (!q || n.kind !== "table" || n.id.includes(q) || n.name.toLowerCase().includes(q)))
  const ids = new Set(nodes.map(n => n.id))
  return { ...flow, nodes, edges: flow.edges.filter(e => ids.has(e.from) && ids.has(e.to)) }
}


const MEDALLION: Record<string, number> = { raw: 1, landing: 1, bronze: 1, default: 1, refined: 2, silver: 2, serving: 3, gold: 3 }

/** Sources first, then one column per namespace: medallion order where
 *  the name says it (raw → refined → serving), otherwise by how deep its tables sit.
 *  Inside a column each node sits near the average row of what feeds it (one
 *  barycentre pass). */
export function columnsOf(flow: Flow): Map<string, number> {
  const depth = new Map<string, number[]>()
  for (const n of flow.nodes) if (n.kind === "table") depth.set(n.namespace ?? "", [...(depth.get(n.namespace ?? "") ?? []), n.column])
  const rank = (ns: string) => {
    const d = depth.get(ns) ?? [1]
    return MEDALLION[ns] ?? d.reduce((a, b) => a + b, 0) / d.length
  }
  const order = [...depth.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
  const col = new Map<string, number>()
  for (const n of flow.nodes) col.set(n.id, n.kind === "table" ? order.indexOf(n.namespace ?? "") + 1 : 0)
  return col
}

export type Placed = FlowNode & { x: number; y: number }

export function layout(flow: Flow): { placed: Placed[]; width: number; height: number; columns: { x: number; label: string }[] } {
  const colOf = columnsOf(flow)
  const cols = new Map<number, FlowNode[]>()
  for (const n of flow.nodes) { const c = colOf.get(n.id) ?? 0; cols.set(c, [...(cols.get(c) ?? []), n]) }
  const order = [...cols.keys()].sort((a, b) => a - b)
  const preds = new Map<string, string[]>()
  for (const e of flow.edges) preds.set(e.to, [...(preds.get(e.to) ?? []), e.from])
  const succs = new Map<string, string[]>()
  for (const e of flow.edges) succs.set(e.from, [...(succs.get(e.from) ?? []), e.to])
  const row = new Map<string, number>()
  const placed: Placed[] = []
  order.forEach((c, ci) => {
    const list = [...(cols.get(c) ?? [])]
    const score = (n: FlowNode) => {
      const ps = (preds.get(n.id) ?? []).map(p => row.get(p)).filter((v): v is number => v !== undefined)
      return ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : Number.MAX_SAFE_INTEGER
    }
    // Sources have nothing to their left: order them by what they feed, alphabetically.
    if (ci === 0) list.sort((a, b) => (succs.get(a.id)?.[0] ?? "").localeCompare(succs.get(b.id)?.[0] ?? "") || a.name.localeCompare(b.name))
    else list.sort((a, b) => score(a) - score(b) || a.name.localeCompare(b.name))
    list.forEach((n, i) => {
      row.set(n.id, i)
      placed.push({ ...n, x: PAD + ci * (NODE_W + COL_GAP), y: PAD + i * (NODE_H + ROW_GAP) })
    })
  })
  const rows = Math.max(1, ...order.map(c => cols.get(c)?.length ?? 0))
  const columns = order.map((c, ci) => {
    const ns = [...new Set((cols.get(c) ?? []).filter(n => n.kind === "table").map(n => n.namespace ?? ""))]
    return { x: PAD + ci * (NODE_W + COL_GAP), label: c === 0 ? "Sources" : ns.join(" · ") }
  })
  return { placed, width: PAD * 2 + order.length * NODE_W + Math.max(0, order.length - 1) * COL_GAP,
           height: PAD * 2 + rows * NODE_H + (rows - 1) * ROW_GAP, columns }
}

export function edgePath(a: { x: number; y: number }, b: { x: number; y: number }): string {
  const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2
  const dx = Math.max(30, (x2 - x1) / 2)
  return `M${x1} ${y1} C${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
}

export function stateText(n: FlowNode, ago: (iso: string | null | undefined) => string): string {
  if (n.kind === "source") return n.connector_type ?? "source"
  const when = n.at ? ago(n.at) : ""
  switch (n.state) {
    case "failed": return `failed ${when}`.trim()
    case "running": return "running now"
    case "stale": return `last ${n.written_by?.kind === "sync" ? "sync" : "run"} ${when}`.trim()
    case "never": return "not run yet"
    case "external": return "not written by DataPond"
    default: return `${n.written_by?.kind === "sync" ? "synced" : "ran"} ${when}`.trim()
  }
}

export function neighbours(flow: Flow, id: string): { reads: string[]; readBy: string[] } {
  return { reads: flow.edges.filter(e => e.to === id).map(e => e.from), readBy: flow.edges.filter(e => e.from === id).map(e => e.to) }
}
