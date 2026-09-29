/** Table-centred reading of GET /api/catalog/relationships.
 *
 *  The whole-catalog ring was unreadable past a dozen tables. What a person asks this
 *  screen is about one table — what does it join to, on what, and how often was that
 *  join actually run — so everything here starts from a table.
 */

export type RelColumn = { name: string; type: string }
export type RelNode = { id: string; query_count: number; columns: RelColumn[] }
export type RelJoin = { left_column: string; right_column: string; count: number }
export type RelEdge = {
  source: string
  target: string
  count: number
  evidence: "observed" | "candidate"
  reason?: string
  join_sql?: string
  joins: RelJoin[]
}
export type RelGraph = {
  nodes: RelNode[]
  edges: RelEdge[]
  statements_scanned?: number
  window_days?: number
  tables_inspected?: number
}

export type Hub = { id: string; observed: number; candidates: number; queries: number }

/** Tables ranked by how many joins people ran against them, then by use. */
export function hubs(graph: RelGraph, limit = 10): Hub[] {
  const out = new Map<string, Hub>(
    graph.nodes.map(n => [n.id, { id: n.id, observed: 0, candidates: 0, queries: n.query_count }]))
  for (const e of graph.edges) {
    for (const id of [e.source, e.target]) {
      const h = out.get(id)
      if (!h) continue
      if (e.evidence === "observed") h.observed += 1
      else h.candidates += 1
    }
  }
  return [...out.values()]
    .filter(h => h.observed + h.candidates > 0)
    .sort((a, b) => b.observed - a.observed || b.queries - a.queries || a.id.localeCompare(b.id))
    .slice(0, limit)
}

export type Neighbour = {
  other: string
  evidence: "observed" | "candidate"
  count: number
  /** Join condition written from the selected table's side of the edge. */
  on: string
  reason?: string
  joinSql?: string
  edge: RelEdge
}

/** The tables `table` joins to. Observed joins first, most-run first; candidates —
 *  guesses from column naming — only when asked for, and always after. */
export function neighbours(graph: RelGraph, table: string,
                           opts: { includeCandidates?: boolean } = {}): Neighbour[] {
  const rows: Neighbour[] = []
  for (const e of graph.edges) {
    if (e.source !== table && e.target !== table) continue
    if (e.evidence === "candidate" && !opts.includeCandidates) continue
    const j = e.joins[0]
    // Edges are undirected (source/target sorted by name); the join keys belong to
    // source on the left and target on the right.
    const on = j ? `${e.source}.${j.left_column} = ${e.target}.${j.right_column}` : ""
    rows.push({
      other: e.source === table ? e.target : e.source,
      evidence: e.evidence, count: e.count, on,
      reason: e.reason, joinSql: e.join_sql, edge: e,
    })
  }
  return rows.sort((a, b) =>
    (a.evidence === b.evidence ? 0 : a.evidence === "observed" ? -1 : 1)
    || b.count - a.count || a.other.localeCompare(b.other))
}

export type LaidOut = { id: string; position: { x: number; y: number } }

/** The selected table in the middle, its first `max` neighbours around it. A ring
 *  of one table's neighbours has no crossing edges; the rest stay in the list. */
export function egoLayout(center: string, around: Neighbour[], max = 12):
    { nodes: LaidOut[]; hidden: number } {
  const shown = around.slice(0, max)
  const radius = Math.max(180, shown.length * 28)
  const nodes: LaidOut[] = [{ id: center, position: { x: 0, y: 0 } }]
  shown.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(shown.length, 1) - Math.PI / 2
    nodes.push({ id: n.other,
                 position: { x: Math.round(radius * Math.cos(angle)), y: Math.round(radius * Math.sin(angle)) } })
  })
  return { nodes, hidden: Math.max(0, around.length - shown.length) }
}

/** Tables whose `schema.table` contains the query. Empty query, no results. */
export function searchTables(graph: RelGraph, q: string, limit = 20): RelNode[] {
  const needle = q.trim().toLowerCase()
  if (!needle) return []
  return graph.nodes.filter(n => n.id.toLowerCase().includes(needle)).slice(0, limit)
}
