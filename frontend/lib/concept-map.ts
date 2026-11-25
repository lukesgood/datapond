/** Concept page, ontology map and downstream impact (Data Map step 4).
 *
 *  Everything here is derived from approved bindings — never drawn by hand. Two concepts
 *  are related when one table holds keys of both (orders: 주문 by id, 고객 by
 *  customer_id), and that table's column is the "via". A segment (a concept bound only by
 *  a filter) hangs off its parent as a satellite. Impact is what GET /api/catalog/impact
 *  returns for a table: metrics, concepts, dashboards and how often it was queried.
 */
import type { Binding, Concept } from "./concepts.ts"
import type { Flow } from "./flow-map.ts"

export const conceptHref = (name: string) => `/metrics/concepts/${encodeURIComponent(name)}`

const idOf = (b: { catalog: string; namespace: string; table: string }) => `${b.catalog}.${b.namespace}.${b.table}`.toLowerCase()
const approved = (bs: Binding[]) => bs.filter(b => b.status === "approved")
const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase()

// ── Concept page ────────────────────────────────────────────────────────────────

export type Related = { concept: string; via: { table: string; column: string }[] }

/** Concepts that share a table with this one by key, with the column of this concept
 *  that ties them there ("주문 via orders.customer_id" on 고객's page). */
export function relatedConcepts(name: string, bindings: Binding[]): Related[] {
  const keys = approved(bindings).filter(b => b.role === "key")
  const mine = keys.filter(b => same(b.concept, name))
  const out = new Map<string, Related>()
  for (const m of mine) {
    const t = idOf(m)
    for (const o of keys) {
      if (same(o.concept, name) || idOf(o) !== t) continue
      const r = out.get(o.concept) ?? { concept: o.concept, via: [] }
      if (!r.via.some(v => v.table === t && v.column === m.column)) r.via.push({ table: t, column: m.column })
      out.set(o.concept, r)
    }
  }
  return [...out.values()].sort((a, b) => b.via.length - a.via.length || a.concept.localeCompare(b.concept))
}

export function narrower(name: string, concepts: Concept[]): Concept[] {
  return concepts.filter(c => c.parent && same(c.parent, name) && !same(c.name, name))
    .sort((a, b) => a.name.localeCompare(b.name))
}

export type BoundColumn = { table: string; column: string; filter_sql: string | null }

/** This concept's approved columns by role. */
export function columnsByRole(name: string, bindings: Binding[]) {
  const mine = approved(bindings).filter(b => same(b.concept, name))
  const of = (role: Binding["role"]) => mine.filter(b => b.role === role)
    .map(b => ({ table: idOf(b), column: b.column, filter_sql: b.filter_sql }))
    .sort((a, b) => a.table.localeCompare(b.table) || a.column.localeCompare(b.column))
  return { keys: of("key"), attributes: of("attribute"), segments: of("filter") }
}

/** Tables this concept is bound in, key tables first (at most `max`, for one impact call). */
export function conceptTables(name: string, bindings: Binding[], max = 12): string[] {
  const { keys, attributes, segments } = columnsByRole(name, bindings)
  const seen: string[] = []
  for (const c of [...keys, ...attributes, ...segments]) if (!seen.includes(c.table)) seen.push(c.table)
  return seen.slice(0, max)
}

/** Where each table's rows come from: the sync source or stream that writes it, from the
 *  flow map (which keys tables namespace.table). Tables nothing writes are left out. */
export function sourcesOf(flow: Flow | null, tables: string[]): { table: string; from: string; kind: string }[] {
  if (!flow) return []
  const name = new Map(flow.nodes.map(n => [n.id, n]))
  const out: { table: string; from: string; kind: string }[] = []
  for (const t of tables) {
    const parts = t.split(".")
    const key = parts.slice(1).join(".")
    for (const e of flow.edges) {
      if (e.to !== key || e.kind === "transform") continue
      const src = name.get(e.from)
      out.push({ table: t, from: src ? src.name : e.from, kind: e.kind })
    }
  }
  return out
}

// ── Ontology map ────────────────────────────────────────────────────────────────

export type OntologyNode = { name: string; pii: boolean; segment: boolean; parent: string | null; tables: number }
export type OntologyEdge = { from: string; to: string; kind: "shares" | "narrower"; via: string[] }

/** Concepts as nodes; a "shares" line where one table holds keys of both, and a
 *  "narrower" line from a concept to each child. A concept with no key or attribute
 *  binding but a filter one is a segment. Concepts bound nowhere still appear, so a gap
 *  shows. */
export function ontologyGraph(concepts: Concept[], bindings: Binding[]): { nodes: OntologyNode[]; edges: OntologyEdge[] } {
  const ok = approved(bindings)
  const names = new Set(concepts.map(c => c.name))
  const nodes = concepts.map(c => {
    const mine = ok.filter(b => same(b.concept, c.name))
    const segment = mine.length > 0 && mine.every(b => b.role === "filter")
    return { name: c.name, pii: c.pii, segment, parent: c.parent && names.has(c.parent) ? c.parent : null,
             tables: new Set(mine.map(idOf)).size }
  }).sort((a, b) => a.name.localeCompare(b.name))
  const byTable = new Map<string, Set<string>>()
  for (const b of ok) if (b.role === "key" && names.has(b.concept)) {
    const t = idOf(b)
    byTable.set(t, (byTable.get(t) ?? new Set()).add(b.concept))
  }
  const shares = new Map<string, OntologyEdge>()
  for (const [t, cs] of byTable) {
    const list = [...cs].sort()
    for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) {
      const k = `${list[i]}|${list[j]}`
      const e = shares.get(k) ?? { from: list[i], to: list[j], kind: "shares" as const, via: [] }
      e.via.push(t.split(".").pop() ?? t)
      shares.set(k, e)
    }
  }
  const edges: OntologyEdge[] = [...shares.values()]
  for (const n of nodes) if (n.parent && n.parent !== n.name) edges.push({ from: n.parent, to: n.name, kind: "narrower", via: [] })
  return { nodes, edges }
}

/** Main concepts on a ring, each segment just outside its parent. `centre`, when given,
 *  sits in the middle with its neighbours (depth 1) on the ring and the rest left out. */
export function ontologyLayout(graph: { nodes: OntologyNode[]; edges: OntologyEdge[] }, centre?: string | null) {
  let nodes = graph.nodes
  let edges = graph.edges
  if (centre) {
    const near = new Set([centre])
    for (const e of edges) { if (e.from === centre) near.add(e.to); if (e.to === centre) near.add(e.from) }
    nodes = nodes.filter(n => near.has(n.name))
    edges = edges.filter(e => near.has(e.from) && near.has(e.to) && (e.from === centre || e.to === centre))
  }
  const isSatellite = (n: OntologyNode) => n.segment && !!n.parent && nodes.some(m => m.name === n.parent) && n.name !== centre
  const main = nodes.filter(n => !isSatellite(n) && n.name !== centre)
  const sats = nodes.filter(isSatellite)
  const R = Math.max(170, main.length * 34)
  const pos: Record<string, { x: number; y: number }> = {}
  if (centre && nodes.some(n => n.name === centre)) pos[centre] = { x: 0, y: 0 }
  main.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(main.length, 1) - Math.PI / 2
    pos[n.name] = { x: Math.round(R * Math.cos(a)), y: Math.round(R * Math.sin(a)) }
  })
  const kids = new Map<string, OntologyNode[]>()
  for (const s of sats) kids.set(s.parent!, [...(kids.get(s.parent!) ?? []), s])
  for (const [parent, list] of kids) {
    const p = pos[parent] ?? { x: 0, y: 0 }
    const base = p.x === 0 && p.y === 0 ? Math.PI / 2 : Math.atan2(p.y, p.x)
    list.forEach((s, i) => {
      const a = base + (i - (list.length - 1) / 2) * 0.45
      pos[s.name] = { x: Math.round(p.x + 120 * Math.cos(a)), y: Math.round(p.y + 120 * Math.sin(a)) }
    })
  }
  return { nodes, edges, pos }
}

// ── Downstream impact ───────────────────────────────────────────────────────────

export type Impact = {
  metrics: { name: string; label: string; version: number | null }[]
  concepts: { concept: string; column: string; role: string; filter_sql: string | null }[]
  dashboards: { id: string; name: string }[]
  queries: { calls: number; people: number; services: number; service_calls: number; callers: { name: string; kind: string; calls: number }[] }
}
export type ImpactResponse = { tables: Record<string, Impact>; days: number }

export function impactUrl(tables: string[]): string {
  return `/api/catalog/impact?${tables.map(t => `table=${encodeURIComponent(t)}`).join("&")}`
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** One short line per kind that has anything, for the Lineage panel and graph. */
export function impactLines(i: Impact | null | undefined, days: number): { kind: string; text: string }[] {
  if (!i) return []
  const out: { kind: string; text: string }[] = []
  if (i.metrics.length) out.push({ kind: "metrics", text: i.metrics.map(m => m.version ? `${m.name} v${m.version}` : m.name).join(", ") })
  const cs = [...new Set(i.concepts.map(c => c.concept))]
  if (cs.length) out.push({ kind: "concepts", text: cs.join(" · ") })
  if (i.dashboards.length) out.push({ kind: "dashboards", text: plural(i.dashboards.length, "dashboard") })
  const q = i.queries
  if (q.calls) {
    const parts = [plural(q.people, "person", "people")]
    if (q.services) parts.push(`${plural(q.services, "key")} (${q.service_calls}×)`)
    out.push({ kind: "queries", text: `${q.calls}× in ${days} days · ${parts.join(", ")}` })
  }
  return out
}

/** Metrics across several tables, once each (a concept page's "Measured by"). */
export function metricsAcross(r: ImpactResponse | null): Impact["metrics"] {
  if (!r) return []
  const seen = new Map<string, Impact["metrics"][number]>()
  for (const i of Object.values(r.tables)) for (const m of i.metrics) seen.set(m.name, m)
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name))
}

const q = (ident: string) => `"${ident.replace(/"/g, '""')}"`
const tableRef = (id: string) => id.split(".").map(q).join(".")

/** A first query for "Ask in Analytics": a segment counts its rows, any other concept
 *  counts distinct values of its key (the table's own `id` key first). Null when the
 *  concept is bound to no key or segment. */
export function askSql(name: string, bindings: Binding[]): string | null {
  const { keys, segments } = columnsByRole(name, bindings)
  if (segments.length) {
    const s = segments[0]
    return `SELECT count(*) AS ${q(name)}\nFROM ${tableRef(s.table)}\nWHERE ${s.filter_sql}`
  }
  const k = keys.find(x => same(x.column, "id")) ?? keys[0]
  if (!k) return null
  return `SELECT count(DISTINCT ${q(k.column)}) AS ${q(name)}\nFROM ${tableRef(k.table)}`
}
