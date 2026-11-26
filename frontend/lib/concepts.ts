/** Concept bindings on the Metrics page (backend app/api/concepts.py).
 *
 *  A concept ("고객") is tied to columns: keys, attributes, or a segment filter. The
 *  Concepts tab shows them as a matrix — concepts down, tables across — so an empty
 *  row (a concept bound nowhere) and a waiting cell (a suggestion or proposal) stand
 *  out. Pure helpers; the panel renders them.
 */

export type Concept = { name: string; parent: string | null; pii: boolean; description?: string | null; terms: string[] }
export type Role = "key" | "attribute" | "filter"
export type Binding = {
  id: number; concept: string; catalog: string; namespace: string; table: string; column: string
  role: Role; filter_sql: string | null; status: "proposed" | "approved"; source: string; evidence: string
  proposed_by_name?: string | null; decided_by_name?: string | null
}
export type Suggestion = {
  concept: string; catalog: string; namespace: string; table: string; column: string
  role: Role; source: string; evidence: string
}
export type ConceptViewer = { can_approve: boolean; can_propose: boolean; openmetadata?: boolean }

type Placed = { catalog: string; namespace: string; table: string }
export const tableKey = (x: Placed) => `${x.catalog}.${x.namespace}.${x.table}`.toLowerCase()

/** Concepts in tree order (each parent before its children), with depth. A parent that
 *  is not itself a concept makes its children roots; a cycle stops at the first repeat. */
export function conceptRows(concepts: Concept[]): { concept: Concept; depth: number }[] {
  const names = new Set(concepts.map(c => c.name))
  const kids = new Map<string, Concept[]>()
  const roots: Concept[] = []
  for (const c of concepts) {
    if (c.parent && names.has(c.parent) && c.parent !== c.name) {
      kids.set(c.parent, [...(kids.get(c.parent) ?? []), c])
    } else roots.push(c)
  }
  const byName = (a: Concept, b: Concept) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0)
  const out: { concept: Concept; depth: number }[] = []
  const seen = new Set<string>()
  const visit = (c: Concept, depth: number) => {
    if (seen.has(c.name)) return
    seen.add(c.name)
    out.push({ concept: c, depth })
    for (const k of (kids.get(c.name) ?? []).sort(byName)) visit(k, depth + 1)
  }
  for (const r of roots.sort(byName)) visit(r, 0)
  for (const c of concepts) if (!seen.has(c.name)) visit(c, 0)   // members of a cycle
  return out
}

/** Tables that carry any binding or suggestion, most-bound first. */
export function matrixTables(bindings: Placed[], suggestions: Placed[]): string[] {
  const n = new Map<string, number>()
  for (const x of [...bindings, ...suggestions]) n.set(tableKey(x), (n.get(tableKey(x)) ?? 0) + 1)
  return [...n.keys()].sort((a, b) => (n.get(b)! - n.get(a)!) || a.localeCompare(b))
}

/** A table key as short as the set allows: no catalog when there is one catalog, no
 *  namespace either when there is also one namespace. */
export function tableLabel(key: string, all: string[]): string {
  const parts = (s: string) => s.split(".")
  const cats = new Set(all.map(k => parts(k)[0]))
  const nss = new Set(all.map(k => parts(k).slice(0, 2).join(".")))
  const [cat, ns, t] = parts(key)
  if (cats.size > 1) return key
  return nss.size > 1 ? `${ns}.${t}` : t ?? `${cat}`
}

export type Cell = { approved: Binding[]; proposed: Binding[]; suggested: Suggestion[] }

export function cell(concept: string, table: string, bindings: Binding[], suggestions: Suggestion[]): Cell {
  const here = (x: Placed & { concept: string }) => x.concept === concept && tableKey(x) === table
  const b = bindings.filter(here)
  return { approved: b.filter(x => x.status === "approved"), proposed: b.filter(x => x.status === "proposed"),
           suggested: suggestions.filter(here) }
}

export function coverage(concepts: Concept[], bindings: Binding[], suggestions: Suggestion[]) {
  const bound = new Set(bindings.filter(b => b.status === "approved").map(b => b.concept))
  return {
    waiting: bindings.filter(b => b.status === "proposed").length + suggestions.length,
    unbound: concepts.filter(c => !bound.has(c.name)).map(c => c.name),
  }
}

/** What a binding means, in one line: `customers.tier = 'VIP'` for a segment. */
export function bindingText(b: { table: string; column: string; role: Role; filter_sql?: string | null }): string {
  return b.role === "filter" && b.filter_sql ? `${b.table}: ${b.filter_sql}` : `${b.table}.${b.column}`
}

export function matchesSearch(c: Concept, q: string, bindings: Binding[]): boolean {
  const s = q.trim().toLowerCase()
  if (!s) return true
  if ([c.name, ...c.terms].some(t => t.toLowerCase().includes(s))) return true
  return bindings.some(b => b.concept === c.name && `${b.table}.${b.column}`.toLowerCase().includes(s))
}

/** POST /api/semantic/concepts/bindings body for a suggestion. */
export function suggestionBody(s: Suggestion, status: "approved" | "rejected") {
  return { concept: s.concept, catalog: s.catalog, table: `${s.namespace}.${s.table}`, column: s.column,
           role: s.role, source: s.source, evidence: s.evidence, status }
}

/** A binding as /ai/sql reports it, shortened for a chip: the catalog and namespace go,
 *  `iceberg.default.customers WHERE tier = 'platinum'` → `customers: tier = 'platinum'`. */
export function shortUse(use: string): string {
  const m = use.match(/^[^.\s]+\.[^.\s]+\.([^.\s]+)(?:\.(\S+)| WHERE (.+))$/)
  if (!m) return use
  return m[3] ? `${m[1]}: ${m[3]}` : `${m[1]}.${m[2]}`
}

/** The answer's concept chips: one per concept the assistant was given. */
export function conceptChips(provided: { name: string; uses: string[] }[] | undefined) {
  return (provided ?? []).map(c => ({ name: c.name, uses: c.uses.map(shortUse) }))
}

/** A column bound to a PII concept that no column mask covers (GET /semantic/concepts/pii-gaps). */
export type PiiGap = { concept: string; catalog: string; namespace: string; table: string; column: string; key: boolean }

/** Governance › Access policies with a new mask for this column filled in. */
export const maskHref = (g: PiiGap) =>
  `/governance?tab=access-control&mask=${encodeURIComponent(`${g.catalog}.${g.namespace}.${g.table}.${g.column}`)}`

/** `catalog.schema.table.column` from the mask link, or null. */
export function parseMaskParam(v: string | null): { catalog: string; schema: string; table: string; column: string } | null {
  const p = (v ?? "").split(".")
  if (p.length !== 4 || p.some(x => !/^[A-Za-z0-9_$-]+$/.test(x))) return null
  return { catalog: p[0], schema: p[1], table: p[2], column: p[3] }
}

/** Approved segments on one table, for the metric editor's "Only rows where". `catalog`
 *  is the engine's name (bindings store it); `table` is namespace.table. */
export function segmentsFor(bindings: Binding[], catalog: string, table: string): { concept: string; filter_sql: string }[] {
  const want = `${catalog}.${table}`.toLowerCase()
  return bindings
    .filter(b => b.status === "approved" && b.role === "filter" && b.filter_sql && tableKey(b) === want)
    .map(b => ({ concept: b.concept, filter_sql: b.filter_sql as string }))
    .sort((a, b) => (a.concept < b.concept ? -1 : a.concept > b.concept ? 1 : 0))
}

/** The filter with a segment's condition added (AND); unchanged when it is already there. */
export function addCondition(current: string, cond: string): string {
  const c = /\bor\b/i.test(cond) ? `(${cond})` : cond
  const cur = current.trim()
  if (!cur) return c
  if (cur.includes(cond)) return cur
  return `${/\bor\b/i.test(cur) ? `(${cur})` : cur} AND ${c}`
}

/** Concept words that also match a metric label, as /ai/sql matches them: a one-word
 *  term of a concept stands for its concept's other one-word terms. */
export function conceptWordsFor(label: string, concepts: Concept[]): string[] {
  const words = label.toLowerCase().split(/\s+/).filter(Boolean)
  const out: string[] = []
  for (const c of concepts) {
    // Same rule as the backend's alias_map: one word, three letters if Latin, two otherwise.
    const group = [c.name, ...c.terms].map(t => t.trim())
      .filter(t => t && !/\s/.test(t) && t.length >= (/^[\x00-\x7f]+$/.test(t) ? 3 : 2))
    const lower = group.map(t => t.toLowerCase())
    if (!words.some(w => lower.includes(w))) continue
    for (const t of group) if (!words.includes(t.toLowerCase()) && !out.includes(t)) out.push(t)
  }
  return out
}

/** GET /semantic/concepts/feedback: what /ai/sql questions suggest (governance readers). */
export type FeedbackWord = { word: string; questions: number; examples: string[] }
export type FeedbackJoin = { join: string; seen: number; unrepaired: number; example: string }
export type FeedbackValue = {
  table: string; column: string; value: string; questions: number; example: string; segments_on_column: boolean
  /** Checked against the data through the governed path: rows with the exact value, and the
   *  stored spelling when only another case exists ('VIP' asked, 'vip' stored). */
  checked?: boolean; exists?: boolean; rows?: number; actual?: string; actual_rows?: number
}

/** The value a segment should hold: the stored spelling when the data has it in another case. */
export const segmentValue = (v: FeedbackValue) => v.actual ?? v.value

/** False only when the data was checked and holds no such value in any case. */
export const canBecomeSegment = (v: FeedbackValue) => !(v.checked && v.exists === false)
export type FeedbackKind = "word" | "value" | "join"
export type FeedbackDismissal = { kind: FeedbackKind; key: string; by?: string | null; at?: string | null }
export type Feedback = { questions: number; days: number; words: FeedbackWord[]; joins: FeedbackJoin[]; values: FeedbackValue[]; concept_use: Record<string, number>; dismissed?: FeedbackDismissal[] }

/** The key a value suggestion is dismissed under (backend concept_feedback.value_key). */
export const valueKey = (v: Pick<FeedbackValue, "table" | "column" | "value">) => `${v.table}.${v.column}=${v.value}`

/** How a dismissed suggestion reads in the restore list. */
export function dismissalText(d: FeedbackDismissal): string {
  if (d.kind === "value") {
    const i = d.key.lastIndexOf("=")
    const col = d.key.slice(0, i).split(".").slice(-2).join(".")
    return `${col} = '${d.key.slice(i + 1)}'`
  }
  return d.key
}

/** The condition a value suggestion becomes: `tier = 'vip'`, or `is_active = true`. */
export function valueCondition(v: Pick<FeedbackValue, "column" | "value">): string {
  if (v.value === "true" || v.value === "false") return `${v.column} = ${v.value}`
  return `${v.column} = '${v.value.replace(/'/g, "''")}'`
}

/** POST /semantic/concepts/bindings body making a value suggestion a segment of `concept`. */
export function segmentBody(v: FeedbackValue, concept: string) {
  const [catalog, namespace, table] = v.table.split(".")
  return {
    concept, catalog, table: `${namespace}.${table}`, column: v.column, role: "filter" as const,
    filter_sql: valueCondition({ column: v.column, value: segmentValue(v) }), source: "feedback" as const,
    evidence: `used in ${v.questions} questions to /ai/sql`, status: "approved" as const,
  }
}

/** Names of every concept below `name` in the tree: none of them may become its parent. */
export function descendants(concepts: Concept[], name: string): Set<string> {
  const out = new Set<string>()
  let frontier = [name]
  while (frontier.length) {
    const next = concepts.filter(c => c.parent && frontier.includes(c.parent) && !out.has(c.name)).map(c => c.name)
    next.forEach(n => out.add(n))
    frontier = next
  }
  return out
}

export type ConceptDraft = { name: string; description: string; parent: string; pii: boolean }

/** PATCH /semantic/concepts/{name} body: only what the draft changes. */
export function editBody(c: Concept, d: ConceptDraft): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (d.name.trim() && d.name.trim() !== c.name) out.name = d.name.trim()
  if ((d.description.trim() || null) !== (c.description ?? null)) out.description = d.description.trim() || null
  if ((d.parent || null) !== (c.parent ?? null)) out.parent = d.parent || null
  if (d.pii !== c.pii) out.pii = d.pii
  return out
}
