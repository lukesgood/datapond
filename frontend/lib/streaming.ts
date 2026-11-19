/** The New stream form's pure parts: what it sends, what stops Create, what it makes. */

export type StreamKind = "cdc" | "kafka" | "kinesis"

export type CdcCheck = { key: string; ok: boolean; label: string; detail: string | null }
export type CdcTest = {
  success: boolean
  ready?: boolean
  checks?: CdcCheck[]
  tables: string[]
  error?: string | null
}

export type StreamForm = {
  kind: StreamKind
  name: string
  /** an existing PostgreSQL source's id, or "manual" */
  connectionId: string
  host: string; port: string; database: string; user: string; password: string; schema: string
  tables: string[]
  namespace: string
  topic: string; bootstrap: string
  stream: string; region: string
  format: "json" | "avro" | "csv"
  columns: string
}

export const MANUAL = "manual"

export function emptyStream(kind: StreamKind = "cdc"): StreamForm {
  return { kind, name: "", connectionId: "", host: "", port: "5432", database: "", user: "", password: "",
           schema: "public", tables: [], namespace: "raw", topic: "", bootstrap: "", stream: "",
           region: "us-east-1", format: "json", columns: "data JSONB" }
}

const IDENT = /^[A-Za-z_][A-Za-z0-9_]{0,62}$/

/** The connection part of cdc-test / cdc-pipeline: a source id, or what was typed. */
export function cdcConnection(f: StreamForm): Record<string, unknown> {
  if (f.connectionId && f.connectionId !== MANUAL) return { connection_id: f.connectionId, db_schema: f.schema || "public" }
  return { db_host: f.host.trim(), db_port: Number(f.port) || 5432, db_name: f.database.trim(),
           db_user: f.user.trim(), db_password: f.password, db_schema: f.schema.trim() || "public" }
}

export function canTestCdc(f: StreamForm): boolean {
  if (f.connectionId && f.connectionId !== MANUAL) return true
  return f.connectionId === MANUAL && !!(f.host.trim() && f.database.trim() && f.user.trim())
}

/** The first reason Create would be refused, in words, or null. */
export function streamProblem(f: StreamForm, test: CdcTest | null): string | null {
  if (!IDENT.test(f.name.trim())) return "Name: a letter or _, then letters, digits or _."
  if (f.kind === "cdc") {
    if (!canTestCdc(f)) return "Choose a source."
    if (!test) return "Checking whether the database can stream…"
    if (!test.success) return "The database could not be reached."
    const failed = (test.checks ?? []).find(c => !c.ok)
    if (failed) return `${failed.label}: fix it on the database, then check again.`
    if (f.tables.length === 0) return "Choose at least one table."
    return null
  }
  if (f.kind === "kafka" && !(f.topic.trim() && f.bootstrap.trim())) return "Topic and bootstrap servers are needed."
  if (f.kind === "kinesis" && !(f.stream.trim() && f.region.trim())) return "Stream name and region are needed."
  return null
}

export function createRequest(f: StreamForm): { url: string; body: Record<string, unknown> } {
  if (f.kind === "cdc") {
    return { url: "/api/streaming/cdc-pipeline",
             body: { pipeline_name: f.name.trim(), tables: f.tables, iceberg_schema: f.namespace, ...cdcConnection(f) } }
  }
  return { url: "/api/streaming/event-pipeline", body: {
    pipeline_name: f.name.trim(), source_type: f.kind, iceberg_schema: f.namespace, format: f.format,
    columns_sql: f.columns.trim() || "data JSONB",
    ...(f.kind === "kafka" ? { topic: f.topic.trim(), bootstrap_servers: f.bootstrap.trim() }
                           : { stream_name: f.stream.trim(), aws_region: f.region.trim() }),
  } }
}

/** The RisingWave objects Create makes, for the rail. */
export function objectsMade(f: StreamForm): string[] {
  const n = f.name.trim() || "name"
  if (f.kind !== "cdc") return [`${n}_src`, `${n}_mv`, `${n}_sink`]
  return f.tables.flatMap(t => [`${n}_${t.toLowerCase()}_src`, `${n}_${t.toLowerCase()}_mv`, `${n}_${t.toLowerCase()}_sink`])
}

/** For each table, a stream that already captures a table of that name. Names only:
 *  RisingWave's definitions do not tell which database, so this informs, never blocks. */
export function streamedTables(sourceNames: string[], tables: string[]): Map<string, string> {
  const out = new Map<string, string>()
  for (const t of tables) {
    const hit = sourceNames.find(s => s.endsWith(`_${t.toLowerCase()}_src`))
    if (hit) out.set(t, hit.slice(0, -(`_${t.toLowerCase()}_src`.length)))
  }
  return out
}
