/** One column, drilled into (Data Map step 3b).
 *
 *  GET /api/catalog/tables/{ns}/{t}/columns/{col}/values gives the top values by rows,
 *  read through the governed query path; a masked or PII-bound column comes back
 *  `hidden`, counts only. Around that: what the column means (segments defined on it),
 *  what it joins to (declared keys), and two ways to give it meaning from here — make a
 *  value a segment, or bind the column to a concept. A segment is written from the value
 *  as stored, so 'Cancelled' can never become a segment that matches nothing.
 */
import type { Binding, Concept } from "./concepts.ts"
import type { TableKeys } from "./table-profile.ts"

export type ColumnValues = {
  column: string; type: string; rows: number; nulls: number; null_fraction: number | null
  distinct: number | null; values: { value: string | null; rows: number }[]
  hidden: boolean; reason: string | null; restricted: boolean; top: number
}

export function valuesUrl(tableId: string, column: string): string {
  const [catalog, namespace, ...rest] = tableId.split(".")
  const table = rest.join(".")
  return `/api/catalog/tables/${encodeURIComponent(namespace)}/${encodeURIComponent(table)}` +
    `/columns/${encodeURIComponent(column)}/values?catalog=${encodeURIComponent(catalog)}`
}

const NUMERIC = /^(tinyint|smallint|integer|int|bigint|long|decimal|numeric)\b/i

/** The SQL condition matching one stored value, typed so the engine accepts it:
 *  numbers and booleans bare, dates as DATE literals, everything else quoted. */
export function conditionFor(column: string, value: string, type: string): string {
  const t = (type || "").trim().toLowerCase()
  if (NUMERIC.test(t) && /^-?\d+(\.\d+)?$/.test(value)) return `${column} = ${value}`
  if ((t.startsWith("boolean") || t.startsWith("bool")) && (value === "true" || value === "false")) return `${column} = ${value}`
  if (t.startsWith("date") && /^\d{4}-\d{2}-\d{2}$/.test(value)) return `${column} = DATE '${value}'`
  return `${column} = '${value.replace(/'/g, "''")}'`
}

/** Share of rows holding a value, "49%" / "<1%" / "0%". */
export function share(rows: number, total: number): string {
  if (!total) return "—"
  const p = (rows / total) * 100
  if (p > 0 && p < 1) return "<1%"
  return `${Math.round(p)}%`
}

const idOf = (b: { catalog: string; namespace: string; table: string }) => `${b.catalog}.${b.namespace}.${b.table}`.toLowerCase()

/** Segments defined on this column, and the column's own concept bindings. */
export function meaningOf(bindings: Binding[], tableId: string, column: string) {
  const mine = bindings.filter(b => b.status === "approved" && idOf(b) === tableId.toLowerCase()
    && b.column.toLowerCase() === column.toLowerCase())
  return {
    segments: mine.filter(b => b.role === "filter").map(b => ({ concept: b.concept, filter_sql: b.filter_sql ?? "" })),
    concepts: mine.filter(b => b.role !== "filter").map(b => ({ concept: b.concept, role: b.role })),
  }
}

/** Columns this one joins to, from keys the source database declares. */
export function joinPartners(keys: TableKeys | null, column: string): { table: string; column: string; direction: "refers to" | "referred to by" }[] {
  if (!keys || !Array.isArray(keys.foreign) || !Array.isArray(keys.referenced_by)) return []
  const c = column.toLowerCase()
  return [
    ...keys.foreign.filter(f => f.column.toLowerCase() === c)
      .map(f => ({ table: f.ref_table, column: f.ref_column, direction: "refers to" as const })),
    ...keys.referenced_by.filter(r => r.ref_column.toLowerCase() === c)
      .map(r => ({ table: r.table, column: r.column, direction: "referred to by" as const })),
  ]
}

/** The concept a new segment most likely narrows: the one this table's key is bound to
 *  (orders.id → 주문, so 'cancelled' suggests a child of 주문). */
export function parentSuggestion(bindings: Binding[], tableId: string): string | null {
  const keys = bindings.filter(b => b.status === "approved" && b.role === "key" && idOf(b) === tableId.toLowerCase())
  const own = keys.find(b => b.column.toLowerCase() === "id") ?? keys[0]
  return own?.concept ?? null
}

/** Why a new concept name cannot be used, or null. Creating a concept that already
 *  exists would overwrite its description and parent, so an existing name is refused
 *  here rather than sent. */
export function newConceptProblem(name: string, concepts: Concept[]): string | null {
  const n = name.trim()
  if (!n) return "Name the segment."
  if (n.length > 80) return "Keep the name under 80 characters."
  if (concepts.some(c => c.name.toLowerCase() === n.toLowerCase())) return `“${n}” already exists — pick it from the list instead.`
  return null
}

/** POST /api/semantic/concepts/bindings body for a segment or a column binding. */
export function bindingBody(tableId: string, column: string, concept: string,
                            role: "filter" | "key" | "attribute", filter_sql: string | null, evidence: string) {
  const [catalog, namespace, ...rest] = tableId.split(".")
  return {
    concept, catalog, table: `${namespace}.${rest.join(".")}`, column, role,
    filter_sql: role === "filter" ? filter_sql : null, source: "manual" as const, evidence, status: "approved" as const,
  }
}
