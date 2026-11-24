/** Catalog search results (GET /api/catalog/search, backend app/catalog_search.py).
 *
 *  A word is matched against table names, column names, concepts (name and aliases)
 *  and metrics. A concept brings the columns bound to it and its segments, so 고객
 *  finds customers.id and orders.customer_id though no table says 고객. Every hit says
 *  why it is there; this module turns that into the line and chips the Catalog shows.
 */

export type FoundTable = {
  catalog: string; namespace: string; table: string
  score: number; why: string[]; columns: string[]
}
export type FoundColumn = {
  catalog: string; namespace: string; table: string
  column: string; type?: string | null; why: string
}
export type FoundConcept = {
  name: string; description?: string | null; pii: boolean; terms: string[]
  parent?: string | null; matched: string[]; keys: string[]; attributes: string[]; segments: number
}
export type FoundSegment = {
  concept: string; catalog: string; namespace: string; table: string; column: string
  filter_sql?: string | null
}
export type FoundMetric = { name: string; label?: string | null; base_table: string; matched: string[] }

export type SearchResult = {
  query: string; words: string[]
  tables: FoundTable[]; columns: FoundColumn[]
  table_total?: number; column_total?: number
  concepts: FoundConcept[]; segments: FoundSegment[]; metrics: FoundMetric[]
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** "7 tables · 11 columns · concepts 고객, 고객 문의 · 3 segments · 2 metrics", leaving
 *  out what is zero; null when nothing was found. */
export function summaryLine(r: SearchResult): string | null {
  const tables = r.table_total ?? r.tables.length
  const cols = r.column_total ?? r.columns.length
  const parts: string[] = []
  if (tables) parts.push(plural(tables, "table"))
  if (cols) parts.push(plural(cols, "column"))
  if (r.concepts.length) {
    const names = r.concepts.map(c => c.name)
    const shown = names.slice(0, 3).join(", ") + (names.length > 3 ? ` +${names.length - 3}` : "")
    parts.push(`${r.concepts.length === 1 ? "concept" : "concepts"} ${shown}`)
  }
  if (r.segments.length) parts.push(plural(r.segments.length, "segment"))
  if (r.metrics.length) parts.push(plural(r.metrics.length, "metric"))
  return parts.length ? parts.join(" · ") : null
}

export const foundKey = (x: { catalog: string; namespace: string; table: string }) =>
  `${x.catalog}.${x.namespace}.${x.table}`.toLowerCase()

/** Why a listed table matched, or null when the search did not find it. A table found
 *  only by its own name says nothing extra — the list already shows the name. */
export function whyFor(r: SearchResult | null, t: { catalog: string; namespace: string; name: string }): string[] | null {
  if (!r) return null
  const hit = r.tables.find(x => foundKey(x) === foundKey({ catalog: t.catalog, namespace: t.namespace, table: t.name }))
  if (!hit) return null
  return hit.why.filter(w => w !== "name")
}

/** The column hits of one table, as "column (why)" for a tooltip. */
export function columnsOf(r: SearchResult, key: string): FoundColumn[] {
  return r.columns.filter(c => foundKey(c) === key)
}
