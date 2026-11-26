// Types and data for connector marketplace

export interface ConnectorField {
  name: string
  label: string
  type: "text" | "number" | "password" | "boolean" | "select" | "textarea"
  required?: boolean
  default?: string | number | boolean
  options?: string[]
  placeholder?: string
  help?: string
  // Render at half width so two related fields (host+port, username+password)
  // pair on one row instead of each taking a full-width line.
  half?: boolean
  /** Show the field only when this holds for the current values (e.g. an auth header
   *  only for api_key). A hidden field is never required. */
  showIf?: (values: Record<string, unknown>) => boolean
}

export interface Connector {
  id: string
  name: string
  category: "database" | "storage" | "saas"
  icon: string
  description: string
  supported: boolean
  /** "preview": works, but not yet run against the real service in CI or live. */
  tier?: "preview"
  fields: ConnectorField[]
  features?: string[]
}

export interface Connection {
  id: string
  name: string
  connector_id: string
  connector_name: string
  status: "active" | "paused" | "error"
  last_sync?: string
  next_sync?: string
  config: Record<string, string | number | boolean | null>
  created_at: string
}

export interface SyncJob {
  id: string
  connection_id: string
  status: "running" | "success" | "failed"
  started_at: string
  completed_at?: string
  rows_synced?: number
  error_message?: string
}

/** Regions offered for an S3 source; Seoul first, as on the reference deployment. */
export const S3_REGIONS = [
  "ap-northeast-2", "ap-northeast-1", "ap-northeast-3", "ap-southeast-1", "ap-southeast-2", "ap-south-1",
  "us-east-1", "us-east-2", "us-west-1", "us-west-2", "ca-central-1",
  "eu-west-1", "eu-west-2", "eu-central-1", "eu-north-1", "sa-east-1",
]

/** Whether a sync of this source type can fetch only changed rows by a column. The
 *  Trino-backed databases can; S3, REST and custom Python read everything each time
 *  and either replace the table or merge by key columns (connectors/storage.py,
 *  rest.py, custom.py ignore the changed-rows column). S3 alone can also read only
 *  the files that arrived since the last sync — see S3_NEW_FILES_COLUMN. */
export function readsEverythingEachSync(connectorType: string | null | undefined): boolean {
  return connectorType === "s3" || connectorType === "rest_api" || connectorType === "custom"
}

/** An S3 table set to incremental on this "column" reads only files newer than the
 *  last one it read, by LastModified (connectors/storage.py NEW_FILES_COLUMN). */
export const S3_NEW_FILES_COLUMN = "_file_last_modified"

// The source kinds the console offers. The database kinds are Trino catalogs
// (`engine: trino` in GET /api/connectors/available); REST, custom Python and S3 are
// read by the backend.
export const availableConnectors: Connector[] = [
  {
    id: "postgresql",
    name: "PostgreSQL",
    category: "database",
    icon: "/connectors/postgresql.svg",
    description: "PostgreSQL as a Trino catalog: browse, sync and federate it with the query engine",
    supported: true,
    features: ["Trino federated query", "Incremental Sync", "Schema Discovery"],
    fields: [
      { half: true, name: "host", label: "Host", type: "text", required: true, placeholder: "localhost" },
      { half: true, name: "port", label: "Port", type: "number", default: 5432, required: true },
      { name: "database", label: "Database", type: "text", required: true, placeholder: "mydb" },
      { half: true, name: "username", label: "Username", type: "text", required: true },
      { half: true, name: "password", label: "Password", type: "password", required: true },
      { name: "ssl", label: "Use SSL/TLS", type: "boolean", default: false, help: "Encrypt the connection to the database (sslmode=require)" }
    ]
  },
  {
    id: "mysql",
    name: "MySQL",
    category: "database",
    icon: "/connectors/mysql.svg",
    description: "MySQL and MariaDB as a Trino catalog: browse, sync and federate with the query engine",
    supported: true,
    features: ["Trino federated query", "Incremental Sync", "Schema Discovery"],
    fields: [
      { half: true, name: "host", label: "Host", type: "text", required: true, placeholder: "localhost" },
      { half: true, name: "port", label: "Port", type: "number", default: 3306, required: true },
      { name: "database", label: "Default schema", type: "text", required: false, placeholder: "mydb", help: "Optional — Trino lists every schema the user can see" },
      { half: true, name: "username", label: "Username", type: "text", required: true },
      { half: true, name: "password", label: "Password", type: "password", required: true },
      { name: "ssl", label: "Use SSL/TLS", type: "boolean", default: false, help: "Encrypt the connection to the database (sslMode=REQUIRED)" }
    ]
  },
  {
    id: "sqlserver",
    name: "SQL Server",
    category: "database",
    icon: "/connectors/sqlserver.svg",
    description: "Microsoft SQL Server as a Trino catalog: browse, sync and federate with the query engine",
    supported: true,
    features: ["Trino federated query", "Incremental Sync", "Schema Discovery"],
    fields: [
      { half: true, name: "host", label: "Host", type: "text", required: true, placeholder: "localhost" },
      { half: true, name: "port", label: "Port", type: "number", default: 1433, required: true },
      { name: "database", label: "Database", type: "text", required: true, placeholder: "master" },
      { half: true, name: "username", label: "Username", type: "text", required: true },
      { half: true, name: "password", label: "Password", type: "password", required: true },
      { name: "ssl", label: "Use SSL/TLS", type: "boolean", default: false, help: "encrypt=true (the server certificate is trusted)" }
    ]
  },
  {
    id: "oracle",
    name: "Oracle",
    category: "database",
    icon: "/connectors/oracle.svg",
    description: "Oracle Database as a Trino catalog: browse, sync and federate with the query engine",
    supported: true,
    features: ["Trino federated query", "Incremental Sync", "Schema Discovery"],
    fields: [
      { half: true, name: "host", label: "Host", type: "text", required: true, placeholder: "localhost" },
      { half: true, name: "port", label: "Port", type: "number", default: 1521, required: true },
      { name: "database", label: "Service name", type: "text", required: true, placeholder: "ORCLPDB1", help: "The service name (not SID) of the database" },
      { half: true, name: "username", label: "Username", type: "text", required: true },
      { half: true, name: "password", label: "Password", type: "password", required: true },
      { name: "ssl", label: "Use SSL/TLS", type: "boolean", default: false, help: "Encrypt the connection to the database (TCPS)" }
    ]
  },
  {
    id: "mongodb",
    name: "MongoDB",
    category: "database",
    icon: "/connectors/mongodb.svg",
    description: "MongoDB as a Trino catalog: collections become tables with inferred schemas",
    supported: true,
    features: ["Trino federated query", "Incremental Sync", "Schema Discovery"],
    fields: [
      { half: true, name: "host", label: "Host", type: "text", required: true, placeholder: "localhost" },
      { half: true, name: "port", label: "Port", type: "number", default: 27017, required: true },
      { name: "database", label: "Database", type: "text", required: true },
      { half: true, name: "username", label: "Username", type: "text", required: true },
      { half: true, name: "password", label: "Password", type: "password", required: true },
      { name: "auth_source", label: "Auth database", type: "text", default: "admin", help: "authSource of the user (usually admin)" },
      { name: "ssl", label: "Use SSL/TLS", type: "boolean", default: false, help: "tls=true on the connection string" }
    ]
  },
  {
    id: "s3",
    name: "Amazon S3",
    category: "storage",
    icon: "/connectors/s3.svg",
    description: "Files in Amazon S3 or an S3-compatible store: each folder under the prefix becomes a table",
    supported: true,
    features: ["CSV · JSON · Parquet", "Folder = table", "New files only"],
    fields: [
      { half: true, name: "bucket", label: "Bucket", type: "text", required: true, placeholder: "my-bucket" },
      { half: true, name: "prefix", label: "Folder", type: "text", required: false, placeholder: "exports/", help: "Each folder inside it becomes one table. Blank = the bucket root." },
      {
        half: true,
        name: "region",
        label: "Region",
        type: "select",
        options: S3_REGIONS,
        default: "ap-northeast-2",
        required: true
      },
      { half: true, name: "endpoint_url", label: "Endpoint URL", type: "text", required: false, placeholder: "https://minio.internal:9000", help: "Only for S3-compatible stores (MinIO, R2). Blank for Amazon S3." },
      { half: true, name: "access_key", label: "Access key ID", type: "text", required: false, help: "Blank = the node's IAM role" },
      { half: true, name: "secret_key", label: "Secret access key", type: "password", required: false, showIf: v => !!v.access_key }
    ]
  },
  {
    id: "snowflake",
    name: "Snowflake",
    category: "database",
    icon: "/connectors/snowflake.svg",
    description: "Planned. Trino's Snowflake connector takes a password only (no key pair) and needs engine JVM settings",
    supported: false,
    features: ["Batch Sync", "Schema Discovery"],
    fields: [
      { name: "account", label: "Account", type: "text", required: true, placeholder: "xy12345.us-east-1" },
      { name: "warehouse", label: "Warehouse", type: "text", required: true },
      { name: "database", label: "Database", type: "text", required: true },
      { name: "schema", label: "Schema", type: "text", required: true },
      { half: true, name: "username", label: "Username", type: "text", required: true },
      { half: true, name: "password", label: "Password", type: "password", required: true }
    ]
  },
  {
    id: "redshift",
    name: "Amazon Redshift",
    category: "database",
    icon: "/connectors/redshift.svg",
    description: "Redshift (provisioned or Serverless) as a Trino catalog: browse, sync and federate it with the query engine",
    supported: true,
    features: ["Trino federated query", "Incremental Sync", "Schema Discovery"],
    fields: [
      { half: true, name: "host", label: "Host", type: "text", required: true, placeholder: "wh.abc123.ap-northeast-2.redshift.amazonaws.com" },
      { half: true, name: "port", label: "Port", type: "number", default: 5439, required: true },
      { name: "database", label: "Database", type: "text", required: true, placeholder: "dev" },
      { half: true, name: "username", label: "Username", type: "text", required: true },
      { half: true, name: "password", label: "Password", type: "password", required: true },
      { name: "ssl", label: "Use SSL/TLS", type: "boolean", default: true, help: "Encrypt the connection (the Redshift driver's default)" }
    ]
  },
  {
    id: "bigquery",
    name: "Google BigQuery",
    category: "database",
    icon: "/connectors/bigquery.svg",
    description: "A BigQuery project as a Trino catalog, read with a service account key. Preview",
    supported: true,
    tier: "preview",
    features: ["Trino federated query", "Batch Sync", "Schema Discovery"],
    fields: [
      { name: "project_id", label: "Project ID", type: "text", required: true, placeholder: "my-project-123" },
      { name: "database", label: "Dataset", type: "text", required: false, placeholder: "all datasets", help: "List only this dataset in the setup step. The catalog still covers the whole project." },
      { name: "parent_project_id", label: "Billing project", type: "text", required: false, help: "Project billed for queries, if not the one above" },
      { name: "credentials_key", label: "Service account key (JSON)", type: "password", required: true, help: "Paste the whole JSON key. The account needs BigQuery Data Viewer and Read Session User, and the project needs the BigQuery Storage Read API turned on." }
    ]
  },
  {
    id: "rest_api",
    name: "REST API",
    category: "saas",
    icon: "/connectors/rest.svg",
    description: "Pull JSON from an HTTP API, with an auth header and a path to the records",
    supported: true,
    features: ["Bearer · Basic · API key", "Pagination", "Merge by key"],
    fields: [
      {
        name: "base_url",
        label: "Base URL",
        type: "text",
        required: true,
        placeholder: "https://api.example.com/v1"
      },
      {
        name: "auth_type",
        label: "Authentication",
        type: "select",
        options: ["none", "bearer", "basic", "api_key", "api_key_query"],
        default: "none"
      },
      {
        name: "auth_value",
        label: "Credential",
        type: "password",
        placeholder: "token / user:password / key",
        help: "bearer: the token · basic: user:password · api_key / api_key_query: the key",
        // Only with an auth type: it showed (and was sent) for "none" too.
        showIf: v => (v.auth_type ?? "none") !== "none",
      },
      {
        name: "auth_header",
        label: "Header name",
        type: "text",
        default: "Authorization",
        showIf: v => v.auth_type === "api_key",
        help: "The header that carries the key"
      },
      {
        name: "auth_param",
        label: "Query parameter",
        type: "text",
        default: "api_key",
        showIf: v => v.auth_type === "api_key_query",
        help: "The query parameter that carries the key (?api_key=…)"
      },
      {
        name: "data_path",
        label: "Records path",
        type: "text",
        placeholder: "data.items",
        half: true,
        help: "Where the list of records is in the JSON response. Blank = the whole response."
      },
      {
        name: "pagination",
        label: "Pagination",
        type: "select",
        options: ["none", "page", "offset", "cursor", "next_link"],
        default: "none",
        help: "How the API splits a long list. none reads one response."
      },
      { half: true, name: "page_param", label: "Page parameter", type: "text", default: "page", showIf: v => v.pagination === "page", help: "Sent as 1, 2, 3…" },
      { half: true, name: "page_size_param", label: "Page size parameter", type: "text", placeholder: "per_page", showIf: v => v.pagination === "page", help: "Optional. With a size, a short page ends paging." },
      { half: true, name: "offset_param", label: "Offset parameter", type: "text", default: "offset", showIf: v => v.pagination === "offset" },
      { half: true, name: "limit_param", label: "Limit parameter", type: "text", default: "limit", showIf: v => v.pagination === "offset" },
      { half: true, name: "page_size", label: "Page size", type: "number", placeholder: "100", showIf: v => v.pagination === "page" || v.pagination === "offset" },
      { half: true, name: "cursor_param", label: "Cursor parameter", type: "text", default: "cursor", showIf: v => v.pagination === "cursor" },
      { half: true, name: "cursor_path", label: "Next cursor path", type: "text", default: "next_cursor", showIf: v => v.pagination === "cursor", help: "Where the next token is in the response" },
      { half: true, name: "next_path", label: "Next URL path", type: "text", placeholder: "links.next", showIf: v => v.pagination === "next_link", help: "Blank = the Link header. Only links on the same host are followed." },
      { half: true, name: "max_pages", label: "Stop after pages", type: "number", default: 500, showIf: v => (v.pagination ?? "none") !== "none", help: "The sync fails at this many pages rather than load part of the list" },
      {
        name: "table_name",
        label: "Table name",
        type: "text",
        placeholder: "root",
        half: true,
        help: "The table the records land in"
      }
    ]
  },
  {
    id: "custom",
    name: "Custom Python",
    category: "saas",
    icon: "/connectors/python.svg",
    description: "Build a small table in plain Python: calendars, code lists, mappings. No imports or network access",
    supported: true,
    features: ["Any source", "Internal APIs", "Merge by key"],
    fields: [
      {
        name: "code",
        label: "Python Code",
        type: "textarea",
        required: true,
        placeholder: "def fetch_data():\n    # fetch the records and return them\n    return [{\"id\": 1, \"name\": \"example\"}]",
        help: "Define fetch_data(); it must return a list of dicts. Built-in Python only: no imports, no names starting with _, and it stops after 2 minutes."
      }
    ]
  }
]

export function getConnector(id: string): Connector | undefined {
  return availableConnectors.find(c => c.id === id)
}

export function getConnectorsByCategory(category: string): Connector[] {
  if (category === "all") return availableConnectors
  return availableConnectors.filter(c => c.category === category)
}

export interface ConfigRow { key: string; label: string; value: string; mono: boolean; muted: boolean }

/** A saved source's settings as the form names them, in the form's order; keys the form
 *  does not know follow under their own name. Secrets read "Stored encrypted", Python
 *  code reads as its line count, empty values as "—". */
export function configRows(connectorType: string, config: Record<string, unknown>): ConfigRow[] {
  const fields = getConnector(connectorType)?.fields ?? []
  const known = new Set(fields.map(f => f.name))
  const rows: ConfigRow[] = []
  const add = (key: string, label: string, raw: unknown, field?: ConnectorField) => {
    const empty = raw === undefined || raw === null || raw === ""
    if (field?.showIf && !field.showIf(config)) return
    if (field?.type === "password" || (typeof raw === "string" && raw.startsWith("••"))) {
      rows.push({ key, label, value: empty ? "Not set" : "Stored encrypted", mono: false, muted: true }); return
    }
    if (field?.type === "boolean" || typeof raw === "boolean") {
      rows.push({ key, label, value: raw ? "On" : "Off", mono: false, muted: !raw }); return
    }
    if (field?.type === "textarea" && typeof raw === "string") {
      const n = raw.split("\n").length
      rows.push({ key, label, value: `${n} line${n === 1 ? "" : "s"}`, mono: false, muted: false }); return
    }
    const fallback = field?.default ?? (field?.placeholder && field.name === "table_name" ? field.placeholder : undefined)
    const shown = empty ? fallback : raw
    rows.push({ key, label, value: shown === undefined || shown === "" ? "—" : String(shown), mono: !empty || fallback !== undefined, muted: empty })
  }
  fields.forEach(f => { if (f.name in config) add(f.name, f.label, config[f.name], f) })
  Object.entries(config).forEach(([k, v]) => {
    if (!known.has(k)) add(k, k.replace(/_/g, " ").replace(/^./, c => c.toUpperCase()), v)
  })
  return rows
}

/** GET /api/connectors/{id}/delete-impact. */
export type DeleteImpact = {
  lake_tables: string[]
  catalog: string | null
  scheduled: boolean
  impact_checked: number
  built_on: { metrics: string[]; concepts: string[]; dashboards: string[]; queries: number }
  /** Built on the live catalog itself: these stop working outright. */
  breaks?: { metrics: string[]; concepts: string[]; dashboards: string[]; queries: number }
}

function listed(names: string[], max = 4): string {
  return names.length <= max ? names.join(", ") : `${names.slice(0, max).join(", ")} and ${names.length - max} more`
}

function usesOf(b: DeleteImpact["built_on"]): string[] {
  const uses: string[] = []
  if (b.metrics.length) uses.push(`metrics ${listed(b.metrics)}`)
  if (b.concepts.length) uses.push(`concepts ${listed(b.concepts)}`)
  if (b.dashboards.length) uses.push(`dashboards ${listed(b.dashboards)}`)
  if (b.queries) uses.push(`${b.queries} quer${b.queries === 1 ? "y" : "ies"} in the last 30 days`)
  return uses
}

/** The delete confirmation: what goes, what stays, and what is built on what stays.
 *  `null` (the impact could not be read) still says what deleting always does. */
export function deleteImpactMessage(impact: DeleteImpact | null): string {
  const lines: string[] = []
  const goes = ["its connection settings", "sync jobs", "sync history"]
  if (impact?.scheduled) goes.push("schedule")
  lines.push(`Removes ${goes.slice(0, -1).join(", ")} and ${goes.at(-1)}. This can't be undone.`)
  if (impact?.catalog) {
    lines.push(`Its query catalog ${impact.catalog} goes too: saved queries that name it stop working, and the query engine restarts (about a minute).`)
    const live = impact.breaks ? usesOf(impact.breaks) : []
    if (live.length) lines.push(`Stops working, because it reads ${impact.catalog} directly: ${live.join("; ")}.`)
  }
  if (!impact) {
    lines.push("Tables it already loaded into the lake stay.")
    return lines.join("\n\n")
  }
  const n = impact.lake_tables.length
  if (n === 0) {
    lines.push("It has not loaded any lake tables.")
    return lines.join("\n\n")
  }
  lines.push(`The ${n} lake table${n === 1 ? "" : "s"} it loaded stay, but stop updating: ${listed(impact.lake_tables.map(t => t.split(".").slice(-2).join(".")))}.`)
  const uses = usesOf(impact.built_on)
  if (uses.length) lines.push(`Built on those tables: ${uses.join("; ")}. They keep reading the last data loaded.`)
  else if (impact.impact_checked > 0) lines.push("Nothing you can see is built on those tables.")
  if (impact.impact_checked > 0 && impact.impact_checked < n) lines.push(`Checked the first ${impact.impact_checked} tables for what is built on them.`)
  return lines.join("\n\n")
}

/** The setup preview of a few rows: one header per key seen (in first-seen order), and
 *  the columns about to be masked shown as "masked", so the preview never shows what the
 *  lake will not keep. `mask` is the comma-separated box the person edits. */
export function previewRows(sample: Record<string, unknown>[], mask: string): { headers: string[]; rows: string[][]; masked: Set<string> } {
  const masked = new Set(mask.split(",").map(m => m.trim().toLowerCase()).filter(Boolean))
  const headers: string[] = []
  for (const r of sample) for (const k of Object.keys(r)) if (!headers.includes(k)) headers.push(k)
  const show = (v: unknown) => v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v)
  const rows = sample.map(r => headers.map(h => masked.has(h.toLowerCase()) ? "masked" : show(r[h])))
  return { headers, rows, masked: new Set(headers.filter(h => masked.has(h.toLowerCase()))) }
}
