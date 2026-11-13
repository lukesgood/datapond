/** Ops status line and sync-failure actions (design thinking C1/C2).
 *
 *  GET /api/ops/status lists what needs a person's attention; every issue maps here to a
 *  title, a detail and the buttons that fix it. The same mapping serves the failed-table
 *  rows on a connection page (`diagnosisActions`). Hiding an action the caller lacks the
 *  permission for is a courtesy — the API refuses regardless.
 */

export type Diagnosis = {
  code: string
  action: string
  title: string
  detail: string
  advice: string
}

export type OpsIssue =
  | { kind: "engine_restarting" }
  | { kind: "catalog_unreachable"; catalog: string; error?: string | null }
  | { kind: "mirror"; mirror: string; owner?: string | null; status: string; detail?: string | null }
  | { kind: "sync_failed"; connection_id: string; source: string; table: string; error?: string | null; diagnosis?: Diagnosis | null }
  | { kind: "stale_source"; connection_id: string; source: string; hours?: number | null }

export type OpsStatus = {
  state: "ok" | "attention"
  syncs?: { window_hours: number; tables_ok: number; tables_failed: number }
  queries_24h: number | null
  issues: OpsIssue[]
  checked_at: string
}

/** What a button does. `link` navigates; the others call the API from the page. */
export type OpsAction =
  | { type: "recreate"; label: string; connectionId: string; table: string }
  | { type: "sync"; label: string; connectionId: string; table?: string }
  | { type: "link"; label: string; href: string }

export type IssueView = {
  tone: "warn" | "info"
  title: string
  detail: string
  advice?: string
  actions: OpsAction[]
}

export const RECREATE_LABEL = "Recreate target table"

const LINK_LABELS: Record<string, string> = {
  change_target: "Change target catalog",
  edit_connection: "Edit connection",
  check_connection: "Check connection",
  grant_source: "Open connection",
}

function connectionHref(id: string): string {
  return `/connectors/connections/${encodeURIComponent(id)}`
}

/** Buttons for a diagnosed sync failure of one table. */
export function diagnosisActions(
  connectionId: string, table: string, diagnosis: Diagnosis | null | undefined, perms: Set<string>,
): OpsAction[] {
  if (!diagnosis) return []
  const canWrite = perms.has("connector:write")
  switch (diagnosis.action) {
    case "recreate":
      return canWrite ? [{ type: "recreate", label: RECREATE_LABEL, connectionId, table }] : []
    case "retry":
      return canWrite ? [{ type: "sync", label: "Retry sync", connectionId, table }] : []
    case "change_target":
    case "edit_connection":
    case "check_connection":
    case "grant_source":
      return [{ type: "link", label: LINK_LABELS[diagnosis.action], href: connectionHref(connectionId) }]
    default:
      return []
  }
}

export function issueView(issue: OpsIssue, perms: Set<string>): IssueView {
  switch (issue.kind) {
    case "engine_restarting":
      return {
        tone: "info",
        title: "Query engine is restarting",
        detail: "Trino is reloading its catalogs after a source change (about a minute). Queries and syncs resume on their own.",
        actions: [],
      }
    case "catalog_unreachable":
      return {
        tone: "warn",
        title: `Catalog ${issue.catalog} is unreachable`,
        detail: issue.error || "The catalog did not answer its health check.",
        actions: [perms.has("settings:write")
          ? { type: "link", label: "Open Data catalogs", href: "/settings?tab=catalogs" }
          : { type: "link", label: "Open Catalog", href: "/catalog" }],
      }
    case "mirror":
      return {
        tone: "warn",
        title: `Mirror ${issue.mirror} is ${issue.status}`,
        detail: issue.detail || (issue.owner ? `Its owner is ${issue.owner}.` : "Check the mirror against its owner."),
        actions: [perms.has("settings:write")
          ? { type: "link", label: "Open mirrors", href: "/settings?tab=catalogs" }
          : { type: "link", label: "Open Catalog", href: "/catalog" }],
      }
    case "sync_failed": {
      const d = issue.diagnosis
      return {
        tone: "warn",
        title: d ? `${issue.source} · ${issue.table}: ${d.title}` : `${issue.source} · ${issue.table}: sync failed`,
        detail: d ? d.detail : issue.error || "The last sync of this table failed.",
        advice: d?.advice,
        actions: d
          ? diagnosisActions(issue.connection_id, issue.table, d, perms)
          : [{ type: "link", label: "Open connection", href: connectionHref(issue.connection_id) }],
      }
    }
    case "stale_source": {
      const actions: OpsAction[] = []
      if (perms.has("connector:write")) actions.push({ type: "sync", label: "Sync now", connectionId: issue.connection_id })
      actions.push({ type: "link", label: "Open connection", href: connectionHref(issue.connection_id) })
      return {
        tone: "warn",
        title: `${issue.source} has not synced`,
        detail: issue.hours != null ? `No sync for ${issue.hours} hours.` : "It has never synced.",
        actions,
      }
    }
  }
}

export function headline(status: OpsStatus): { label: string; tone: "good" | "warn" } {
  const n = status.issues.length
  return status.state === "ok" && n === 0
    ? { label: "Healthy", tone: "good" }
    : { label: `${n} to check`, tone: "warn" }
}

/** Only the facts the caller was sent (syncs need connector:read; queries may be null). */
export function statusFacts(status: OpsStatus): string[] {
  const facts: string[] = []
  if (status.syncs) {
    const { tables_ok: ok, tables_failed: failed, window_hours: h } = status.syncs
    facts.push(`${ok} table${ok === 1 ? "" : "s"} synced ok${failed ? ` · ${failed} failed` : ""} (${h}h)`)
  }
  if (status.queries_24h != null) facts.push(`${status.queries_24h.toLocaleString("en-US")} queries today`)
  return facts
}

/** Tolerant parse: anything unexpected becomes null so the line simply does not render. */
export function parseOpsStatus(raw: unknown): OpsStatus | null {
  if (!raw || typeof raw !== "object") return null
  const r = raw as Record<string, unknown>
  if (r.state !== "ok" && r.state !== "attention") return null
  const issues = Array.isArray(r.issues)
    ? (r.issues as OpsIssue[]).filter((i) => i && typeof i.kind === "string") : []
  return { ...(r as unknown as OpsStatus), issues }
}
