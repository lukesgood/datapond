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
