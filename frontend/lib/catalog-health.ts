/** Per-catalog health on the Services page (GET /api/catalogs/health). The backend
 *  probes each enabled catalog the caller may use, with a short deadline, and caches
 *  the answer for up to a minute; this file only reads what it says. */

export interface CatalogHealth {
  name: string
  kind: string
  is_default: boolean
  status: "reachable" | "error"
  error: string | null
  latency_ms: number | null
  checked_at?: string
}

/** The catalogs list from a response body, or [] for anything else — a Services
 *  page must never break because this optional group could not be read. */
export function parseCatalogHealth(body: unknown): CatalogHealth[] {
  const list = (body as { catalogs?: unknown } | null)?.catalogs
  if (!Array.isArray(list)) return []
  return list.filter(
    (c): c is CatalogHealth =>
      !!c && typeof c === "object" && typeof (c as CatalogHealth).name === "string" &&
      ((c as CatalogHealth).status === "reachable" || (c as CatalogHealth).status === "error"),
  )
}

/** The dot's colour token: good for reachable, bad for an error. */
export function healthDotClass(c: CatalogHealth): string {
  return c.status === "reachable" ? "bg-[var(--dp-good)]" : "bg-[var(--dp-bad)]"
}

/** One line under the catalog's name. */
export function healthDetail(c: CatalogHealth): string {
  if (c.status === "reachable") {
    return c.latency_ms == null ? "Reachable" : `Reachable · ${c.latency_ms} ms`
  }
  return c.error || "The catalog did not answer."
}

export function healthCounts(list: CatalogHealth[]): { reachable: number; error: number } {
  const reachable = list.filter((c) => c.status === "reachable").length
  return { reachable, error: list.length - reachable }
}
