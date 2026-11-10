// The query engine's state as the Sources pages show it.
//
// A Trino-backed source (PostgreSQL, MySQL, SQL Server, Oracle, MongoDB) is a Trino
// catalog, and Trino reads its catalog files only at start: creating, re-configuring or
// deleting one restarts the engine (~1 min). GET /api/connectors/engine reports it;
// these helpers turn that answer into the one line a page shows and whether to ask again.

export type EngineStatus = {
  engine: "trino" | "none"
  ready: boolean | null
  restarting: boolean | null
  restarted_at?: string | null
  error?: string
}

export type EngineBanner = { tone: "info" | "warn"; text: string }

export const RESTARTING_TEXT =
  "Query engine restarting (~1 min) — the new source catalog appears when it is back."
export const NOT_READY_TEXT =
  "Query engine is not ready; sources cannot be browsed or synced until it is."

// The connector types that are Trino catalogs — the backend's TRINO_ENGINE_TYPES plus
// the legacy `database_url`, which is stored as one of them.
export const TRINO_ENGINE_TYPES = ["postgresql", "mysql", "sqlserver", "oracle", "mongodb", "database_url"]

export function isTrinoEngine(connectorType: string | null | undefined): boolean {
  return !!connectorType && TRINO_ENGINE_TYPES.includes(connectorType)
}

export function parseEngineStatus(raw: unknown): EngineStatus | null {
  if (!raw || typeof raw !== "object") return null
  const r = raw as Record<string, unknown>
  if (r.engine !== "trino" && r.engine !== "none") return null
  const flag = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null)
  return {
    engine: r.engine,
    ready: flag(r.ready),
    restarting: flag(r.restarting),
    restarted_at: typeof r.restarted_at === "string" ? r.restarted_at : null,
    error: typeof r.error === "string" ? r.error : undefined,
  }
}

export function engineBanner(s: EngineStatus | null): EngineBanner | null {
  if (!s || s.engine === "none") return null
  if (s.restarting) return { tone: "info", text: RESTARTING_TEXT }
  if (s.error) return { tone: "warn", text: `Query engine status unavailable (${s.error}).` }
  if (s.ready === false) return { tone: "warn", text: NOT_READY_TEXT }
  return null
}

// How long until the next poll; 0 means stop — there is nothing left to wait for.
export function pollDelayMs(s: EngineStatus | null): number {
  return s?.engine === "trino" && s.restarting ? 3000 : 0
}
