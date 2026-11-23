/** Each table's own last run on a source page (GET /api/connectors/{id}/tables).
 *
 *  The source's "last synced" is its newest run, which hid a table left behind: live on
 *  2026-11-23 every e-commerce table was synced on 11-20 except customers (11-13), and
 *  nothing on the page said so. A table is "behind" when it is enabled and its last run
 *  is more than a day older than the newest run of the source's tables.
 */

export type TableRun = { name: string; enabled: boolean; last_run_at?: string | null; last_run_status?: string | null }

export type RunState = "ok" | "failed" | "behind" | "never" | "off"

const DAY = 86_400_000

export function runStates(tables: TableRun[]): Record<string, RunState> {
  const times = tables.filter(t => t.enabled && t.last_run_at).map(t => new Date(t.last_run_at as string).getTime())
  const newest = times.length ? Math.max(...times) : null
  const out: Record<string, RunState> = {}
  for (const t of tables) {
    if (!t.enabled) out[t.name] = "off"
    else if (!t.last_run_at) out[t.name] = "never"
    else if (t.last_run_status === "failed") out[t.name] = "failed"
    else if (newest !== null && newest - new Date(t.last_run_at).getTime() > DAY) out[t.name] = "behind"
    else out[t.name] = "ok"
  }
  return out
}

/** "11-20" in the viewer's time zone. */
export function shortDate(iso: string): string {
  const d = new Date(iso.endsWith("Z") || /[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z")
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

export function runLabel(state: RunState, at?: string | null): string {
  const when = at ? shortDate(at) : ""
  switch (state) {
    case "failed": return `failed ${when}`
    case "behind": return `${when} · not refreshed by the last sync`
    case "never": return "not run yet"
    case "off": return when ? `off · last ${when}` : "off"
    default: return when
  }
}
