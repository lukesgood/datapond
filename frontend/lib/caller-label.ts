/** How a caller is written in audit and spend tables.
 *
 *  The backend attaches a readable name (username, display name, or email) when the id
 *  belongs to a DataPond account. Without one, a bare UUID is shortened so the column
 *  stays scannable; the full id is kept for the hover title, never dropped.
 */
export type CallerLabel = { text: string; title?: string }

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function callerLabel(name: string | null | undefined, id: string | null | undefined): CallerLabel {
  if (name) return id && id !== name ? { text: name, title: id } : { text: name }
  if (!id) return { text: "—" }
  return UUID.test(id) ? { text: `${id.slice(0, 8)}…`, title: id } : { text: id }
}
