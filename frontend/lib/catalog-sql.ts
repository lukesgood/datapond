// The statement "Open in Analytics" puts in the editor. Pure, so node --test reaches it.

/** A SQL identifier, double-quoted with embedded quotes doubled. */
export function quoteIdent(s: string): string {
  return `"${s.replace(/"/g, '""')}"`
}

/** SELECT * from a catalog table. Without an engine catalog the two-part name resolves
 *  against the default catalog — right only when the table is in it. A table opened from
 *  another catalog (?catalog=) needs the three-part name, or Analytics silently reads the
 *  default catalog's table of the same name, or none. */
export function tableSelectSql(namespace: string, table: string, engineCatalog?: string | null, limit = 100): string {
  const parts = engineCatalog ? [engineCatalog, namespace, table] : [namespace, table]
  return `SELECT * FROM ${parts.map(quoteIdent).join(".")} LIMIT ${limit}`
}

/** The engine catalog name of a registry entry, or null when it is unknown. */
export function engineCatalogOf(catalogs: { name: string; engine_catalog?: string | null }[], name: string): string | null {
  const c = catalogs.find(x => x.name === name)
  return c?.engine_catalog || null
}
