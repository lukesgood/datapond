/** Catalog page view logic: namespace filter chips and per-table source type, as data. */

export interface ViewTable { name: string; namespace: string; catalog: string; catalog_type?: string }
export interface ViewNamespace { name: string; catalog?: string }
export interface RegistryEntry { name: string; kind: string; engine_catalog: string }

export interface NamespaceChip {
  /** Unique key: `<catalog>\u0000<namespace>`. */
  key: string
  catalog: string
  namespace: string
  /** `namespace`, or `catalog.namespace` when the namespace name is not unique. */
  label: string
  count: number
}

export const chipKey = (catalog: string, namespace: string) => `${catalog}\u0000${namespace}`

/** One chip per (catalog, namespace) with its own table count. The label carries the
 *  catalog only when the same namespace name exists in more than one catalog. */
export function namespaceChips(tables: ViewTable[], namespaces: ViewNamespace[]): NamespaceChip[] {
  const seen = new Map<string, { catalog: string; namespace: string }>()
  for (const n of namespaces) {
    const catalog = n.catalog ?? ""
    seen.set(chipKey(catalog, n.name), { catalog, namespace: n.name })
  }
  const counts = new Map<string, number>()
  for (const t of tables) {
    const k = chipKey(t.catalog ?? "", t.namespace)
    counts.set(k, (counts.get(k) ?? 0) + 1)
    if (!seen.has(k)) seen.set(k, { catalog: t.catalog ?? "", namespace: t.namespace })
  }
  const byName = new Map<string, number>()
  for (const { namespace } of seen.values()) byName.set(namespace, (byName.get(namespace) ?? 0) + 1)
  return [...seen.entries()].map(([key, v]) => ({
    key, catalog: v.catalog, namespace: v.namespace,
    label: (byName.get(v.namespace) ?? 0) > 1 && v.catalog ? `${v.catalog}.${v.namespace}` : v.namespace,
    count: counts.get(key) ?? 0,
  }))
}

/** True when a table belongs to the selected chip ("all" selects everything). */
export function inChip(selected: string, t: Pick<ViewTable, "catalog" | "namespace">): boolean {
  return selected === "all" || chipKey(t.catalog ?? "", t.namespace) === selected
}

/** "source" for tables of a Trino-backed connection (live, federated), else what the
 *  backend said (default "managed"). The backend labels every catalog "managed". */
export function catalogTypeOf(table: Pick<ViewTable, "catalog" | "catalog_type">, registry: RegistryEntry[]): string {
  const hit = registry.find(e => e.engine_catalog === table.catalog)
  if (hit?.kind === "trino_source") return "source"
  return table.catalog_type || "managed"
}

/** What a catalog is, for the badge beside its name. Every screen names a catalog by its
 *  engine name — the one SQL uses (`iceberg`, `polaris_lake`) — and shows this beside it;
 *  the registry name (`AwsDataCatalog`) appears only in Settings as "Registered as". */
export const KIND_SHORT: Record<string, string> = {
  glue: "Glue",
  polaris: "Polaris",
  iceberg_rest: "Iceberg REST",
  trino_source: "Source",
}

export function kindShort(kind: string | null | undefined): string | null {
  return kind ? KIND_SHORT[kind] ?? null : null
}

/** Source catalogs (a connection's live database) are listed apart from lake catalogs. */
export function isSourceKind(kind: string | null | undefined): boolean {
  return kind === "trino_source"
}

/** The catalog browser's state as it lives in the URL, so a view can be shared,
 *  reloaded and returned to: ?catalog=iceberg&ns=iceberg.default&q=ord&table=iceberg.default.orders
 *  `ns` and `table` carry their catalog, since a namespace name may exist in several. */
export interface BrowserState { catalog: string; chip: string; query: string; selected: string | null }

const KEY_SEP = "\u0000"

export function browserStateFrom(params: { get(name: string): string | null }): BrowserState {
  const catalog = params.get("catalog") || "all"
  const ns = params.get("ns")
  let chip = "all"
  if (ns) {
    const i = ns.indexOf(".")
    chip = i > 0 ? chipKey(ns.slice(0, i), ns.slice(i + 1)) : chipKey(catalog === "all" ? "" : catalog, ns)
  }
  const table = params.get("table")
  let selected: string | null = null
  if (table) {
    const first = table.indexOf("."), last = table.lastIndexOf(".")
    if (first > 0 && last > first) selected = [table.slice(0, first), table.slice(first + 1, last), table.slice(last + 1)].join(KEY_SEP)
  }
  return { catalog, chip, query: params.get("q") || "", selected }
}

export function browserQuery(s: BrowserState): string {
  const p = new URLSearchParams()
  if (s.catalog !== "all") p.set("catalog", s.catalog)
  if (s.chip !== "all") p.set("ns", s.chip.split(KEY_SEP).filter(Boolean).join("."))
  if (s.query.trim()) p.set("q", s.query)
  if (s.selected) p.set("table", s.selected.split(KEY_SEP).join("."))
  const q = p.toString()
  return q ? `?${q}` : ""
}

/** What the catalog list and table page say about a table besides its name. */
export interface TableFacts {
  mirror_of?: string | null
  synced_from?: { connection_id: string; connection: string; last_run_at: string; rows?: number | null; status?: string | null } | null
  live?: boolean
}

/** "3 h ago", "2 days ago", "just now" — for a sync time. */
export function ago(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—"
  const ms = now.getTime() - new Date(iso).getTime()
  if (!Number.isFinite(ms)) return "—"
  const min = Math.round(ms / 60000)
  if (min < 1) return "just now"
  if (min < 60) return `${min} min ago`
  const h = Math.round(min / 60)
  if (h < 48) return `${h} h ago`
  return `${Math.round(h / 24)} days ago`
}

/** Catalog browser link to one table ("catalog.namespace.table"). */
export function browserHref(fullName: string): string {
  const first = fullName.indexOf("."), last = fullName.lastIndexOf(".")
  if (first <= 0 || last <= first) return "/catalog"
  const cat = fullName.slice(0, first), ns = fullName.slice(first + 1, last)
  return `/catalog${browserQuery({ catalog: cat, chip: chipKey(cat, ns), query: "", selected: [cat, ns, fullName.slice(last + 1)].join("\u0000") })}`
}

/** Where a search looked, for "No match in …". */
export function searchScope(catalog: string, chipLabel: string | null): string {
  if (catalog === "all" && !chipLabel) return "any catalog"
  if (chipLabel) return catalog === "all" ? chipLabel : `${catalog} · ${chipLabel}`
  return catalog
}
