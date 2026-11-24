/** The Data Map's modes beyond Relationships (Data Map step 3).
 *
 *  One canvas, one centre table, four ways to look at it:
 *  - Relationships: who it joins to (lib/relationship-view.ts, unchanged).
 *  - Lineage: what feeds it and what it feeds, from the flow map (GET /api/transforms/flow).
 *  - Schema: an ERD of the centre and its nearest neighbours — columns, keys, join columns.
 *  - Concepts: the business concepts its columns hold, and where else each one lives.
 *
 *  Pure: the component fetches, these shape.
 */
import type { Flow, FlowEdge, FlowNode } from "./flow-map.ts"
import type { Binding, Concept } from "./concepts.ts"
import { splitTableId, type Neighbour } from "./relationship-view.ts"

export type Mode = "relationships" | "lineage" | "schema" | "concepts"
export const MODES: { key: Mode; label: string; hint: string }[] = [
  { key: "relationships", label: "Relationships", hint: "Tables it joins to, and on what" },
  { key: "lineage", label: "Lineage", hint: "What feeds it and what it feeds" },
  { key: "schema", label: "Schema", hint: "Columns and keys of it and its neighbours" },
  { key: "concepts", label: "Concepts", hint: "Business concepts its columns hold" },
]

export function modeFrom(v: string | null | undefined): Mode {
  return MODES.some(m => m.key === v) ? (v as Mode) : "relationships"
}

// ── Lineage ─────────────────────────────────────────────────────────────────────

/** The flow map keys tables `namespace.table` (catalog dropped); the catalog graph keys
 *  them `catalog.namespace.table`. */
export function flowKey(tableId: string): string {
  const { namespace, table } = splitTableId(tableId)
  return `${namespace}.${table}`.toLowerCase()
}

export type LineageNode = FlowNode & { lane: number }
export type Lineage = { nodes: LineageNode[]; edges: FlowEdge[]; found: boolean }

/** The centre's upstream (up to `up` hops) and downstream (up to `down` hops). `lane`
 *  is the hop distance: negative upstream, 0 the centre, positive downstream. A node
 *  reached both ways keeps the nearer lane. */
export function lineageAround(flow: Flow, tableId: string, up = 3, down = 2): Lineage {
  const centre = flowKey(tableId)
  const byId = new Map(flow.nodes.map(n => [n.id, n]))
  if (!byId.has(centre)) return { nodes: [], edges: [], found: false }
  const lane = new Map<string, number>([[centre, 0]])
  const walk = (dir: -1 | 1, hops: number) => {
    let frontier = [centre]
    for (let h = 1; h <= hops && frontier.length; h++) {
      const next: string[] = []
      for (const id of frontier) {
        for (const e of flow.edges) {
          const other = dir < 0 ? (e.to === id ? e.from : null) : (e.from === id ? e.to : null)
          if (other && !lane.has(other) && byId.has(other)) { lane.set(other, dir * h); next.push(other) }
        }
      }
      frontier = next
    }
  }
  walk(-1, up)
  walk(1, down)
  const nodes = [...lane].map(([id, l]) => ({ ...(byId.get(id) as FlowNode), lane: l }))
  const edges = flow.edges.filter(e => lane.has(e.from) && lane.has(e.to)
    && (lane.get(e.to) as number) > (lane.get(e.from) as number))
  return { nodes, edges, found: true }
}

/** Positions for a left-to-right lineage: one column per lane, nodes stacked. */
export function lineageLayout(nodes: LineageNode[], w = 190, h = 64): Record<string, { x: number; y: number }> {
  const lanes = new Map<number, LineageNode[]>()
  for (const n of nodes) lanes.set(n.lane, [...(lanes.get(n.lane) ?? []), n])
  const out: Record<string, { x: number; y: number }> = {}
  for (const [l, ns] of lanes) {
    const sorted = [...ns].sort((a, b) => (a.name ?? a.id).localeCompare(b.name ?? b.id))
    sorted.forEach((n, i) => { out[n.id] = { x: l * (w + 110), y: (i - (sorted.length - 1) / 2) * h } })
  }
  return out
}

// ── Schema ──────────────────────────────────────────────────────────────────────

export type SchemaTable = { id: string; joinColumns: string[]; via: string; declared: boolean; count: number }

/** The centre and up to `max` neighbours, each with the columns that join it to the
 *  centre (so the ERD can mark them). Declared keys and joins people ran first; guesses
 *  are left out of an ERD. */
export function schemaNeighbours(centre: string, around: Neighbour[], max = 5): { centre: SchemaTable; others: SchemaTable[] } {
  const known = around.filter(n => n.evidence !== "candidate").slice(0, max)
  const centreCols = new Set<string>()
  const others = known.map(n => {
    const joins = (n.edge.fk_joins?.length ? n.edge.fk_joins : n.edge.joins) ?? []
    const mine = n.edge.source === centre
    const cols: string[] = []
    for (const j of joins) {
      centreCols.add(mine ? j.left_column : j.right_column)
      cols.push(mine ? j.right_column : j.left_column)
    }
    return { id: n.other, joinColumns: [...new Set(cols)], via: n.on, declared: n.declared, count: n.count }
  })
  return { centre: { id: centre, joinColumns: [...centreCols], via: "", declared: false, count: 0 }, others }
}

// ── Concepts ────────────────────────────────────────────────────────────────────

export type ConceptHere = {
  concept: string
  pii: boolean
  parent: string | null
  /** This table's columns bound to the concept, with their role. */
  here: { column: string; role: Binding["role"]; filter_sql: string | null }[]
  /** Other tables holding the same concept (key or attribute), by table id. */
  elsewhere: { table: string; columns: string[]; role: Binding["role"] }[]
}

const idOf = (b: { catalog: string; namespace: string; table: string }) =>
  `${b.catalog}.${b.namespace}.${b.table}`.toLowerCase()

/** Approved concepts on the centre table and, for each, the other tables that hold it.
 *  Two tables that both hold a key of one concept are related through it — the logical
 *  relationship, derived from bindings rather than drawn by hand. */
export function conceptsAround(concepts: Concept[], bindings: Binding[], tableId: string): ConceptHere[] {
  const centre = tableId.toLowerCase()
  const approved = bindings.filter(b => b.status === "approved")
  const meta = new Map(concepts.map(c => [c.name, c]))
  const out = new Map<string, ConceptHere>()
  for (const b of approved) {
    if (idOf(b) !== centre) continue
    const c = out.get(b.concept) ?? { concept: b.concept, pii: !!meta.get(b.concept)?.pii,
      parent: meta.get(b.concept)?.parent ?? null, here: [], elsewhere: [] }
    c.here.push({ column: b.column, role: b.role, filter_sql: b.filter_sql })
    out.set(b.concept, c)
  }
  for (const c of out.values()) {
    const others = new Map<string, { table: string; columns: string[]; role: Binding["role"] }>()
    for (const b of approved) {
      if (b.concept !== c.concept || b.role === "filter" || idOf(b) === centre) continue
      const k = idOf(b)
      const o = others.get(k) ?? { table: k, columns: [], role: b.role }
      o.columns.push(b.column)
      if (b.role === "key") o.role = "key"
      others.set(k, o)
    }
    c.elsewhere = [...others.values()].sort((a, b) =>
      Number(b.role === "key") - Number(a.role === "key") || a.table.localeCompare(b.table))
  }
  return [...out.values()].sort((a, b) =>
    Number(b.here.some(h => h.role === "key")) - Number(a.here.some(h => h.role === "key"))
    || a.concept.localeCompare(b.concept))
}
