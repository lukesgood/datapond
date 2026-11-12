/** "Last rows" per table on a connection page.
 *
 *  Each table shows the row count from the newest sync session that included it — not
 *  only from the newest session overall, which made every table a single-table sync did
 *  not touch read "—" (seen live 2026-11-12). Sessions arrive newest first. A table
 *  entry without a count (it failed) does not hide an older count.
 */
export type SessionTables = { tables?: Array<{ table: string; rows?: number | null }> }

export function latestRowsByTable(sessions: SessionTables[]): Map<string, number> {
  const rows = new Map<string, number>()
  for (const session of sessions) {
    for (const t of session.tables ?? []) {
      if (t.rows != null && !rows.has(t.table)) rows.set(t.table, t.rows)
    }
  }
  return rows
}
