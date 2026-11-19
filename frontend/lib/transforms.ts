/** The SQL transform editor's pure parts: the form, what Save sends, what the rail says. */

export const NAMESPACES = ["raw", "refined", "serving"] as const

export type TransformForm = {
  name: string
  description: string
  source_namespace: string
  target_namespace: string
  target_table: string
  sql: string
  schedule: string | null
}

export type SavedTransform = Partial<TransformForm> & {
  id: string
  name: string
  dag_id?: string | null
  status?: string
  last_run_state?: string | null
  last_run_at?: string | null
}

export function emptyForm(): TransformForm {
  return { name: "", description: "", source_namespace: "refined", target_namespace: "serving",
           target_table: "", sql: "SELECT\n  \nFROM refined.", schedule: "0 3 * * *" }
}

export function formFrom(t: SavedTransform): TransformForm {
  return {
    name: t.name, description: t.description ?? "",
    source_namespace: t.source_namespace ?? "refined", target_namespace: t.target_namespace ?? "serving",
    target_table: t.target_table ?? "", sql: t.sql ?? "", schedule: t.schedule ?? null,
  }
}

const NAME = /^[A-Za-z0-9 _-]{1,64}$/
const TABLE = /^[A-Za-z_][A-Za-z0-9_]{0,127}$/

/** The first reason Save would be refused, in words, or null. Mirrors the API. */
export function formProblem(f: TransformForm, creating: boolean): string | null {
  if (creating && !NAME.test(f.name.trim())) return "Name: letters, digits, spaces, _ or -, up to 64."
  if (!TABLE.test(f.target_table.trim())) return "Table: a letter or _, then letters, digits or _."
  if (f.source_namespace === f.target_namespace) return "Reads from and writes to must be different namespaces."
  const head = stripComments(f.sql).trim().split(/\s+/)[0]?.toUpperCase()
  if (head !== "SELECT" && head !== "WITH") return "The SQL must be one SELECT (or WITH … SELECT)."
  if (stripComments(f.sql).trim().replace(/;\s*$/, "").includes(";")) return "Only one statement."
  return null
}

/** What POST /api/transforms (creating) or PATCH (editing) takes. */
export function saveBody(f: TransformForm, creating: boolean): Record<string, unknown> {
  const body: Record<string, unknown> = {
    description: f.description.trim() || null,
    source_namespace: f.source_namespace,
    target_namespace: f.target_namespace,
    target_table: f.target_table.trim(),
    sql: f.sql.trim().replace(/;\s*$/, ""),
    schedule: f.schedule,
  }
  if (creating) { body.name = f.name.trim(); body.overwrite = false }
  return body
}

/** The Airflow job id the API will give this name (transforms._safe_id). */
export function dagIdFor(name: string): string {
  return `transform_${name.toLowerCase().replace(/[^a-z0-9_]/g, "_")}`
}

/** Fifty rows of the SELECT through the governed query path (masking and RLS apply). */
export function previewSql(sql: string): string {
  return `SELECT * FROM (\n${sql.trim().replace(/;\s*$/, "")}\n) AS preview LIMIT 50`
}

function stripComments(sql: string): string {
  return sql.replace(/--[^\n]*/g, " ").replace(/\/\*[\s\S]*?\*\//g, " ")
}

/** Tables named after FROM or JOIN, for the rail. A reading aid, not a parser:
 *  CTE names are left out; anything odd is simply not listed. */
export function tablesRead(sql: string): string[] {
  const s = stripComments(sql)
  const ctes = new Set([...s.matchAll(/(?:\bWITH\b|,)\s*([A-Za-z_][\w]*)\s+AS\s*\(/gi)].map(m => m[1].toLowerCase()))
  const out: string[] = []
  for (const m of s.matchAll(/\b(?:FROM|JOIN)\s+((?:"?[A-Za-z_][\w]*"?\.){0,2}"?[A-Za-z_][\w]*"?)/gi)) {
    const name = m[1].replace(/"/g, "")
    if (ctes.has(name.toLowerCase())) continue
    if (!out.includes(name)) out.push(name)
  }
  return out
}

export type RunCell = { state: string; at: string | null }

/** Last runs, newest first, as cells for the strip. */
export function runStrip(runs: { state?: string; end_date?: string | null; execution_date?: string | null }[], n = 10): RunCell[] {
  return runs.slice(0, n).map(r => ({ state: r.state ?? "unknown", at: r.end_date ?? r.execution_date ?? null }))
}

export function runSummary(cells: RunCell[]): string {
  if (cells.length === 0) return "No runs yet."
  const failed = cells.filter(c => c.state === "failed").length
  if (failed === 0) return `Last ${cells.length} run${cells.length === 1 ? "" : "s"}: all succeeded`
  return `Last ${cells.length} runs: ${failed} failed`
}
