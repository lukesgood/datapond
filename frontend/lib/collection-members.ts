/** Presentation logic for Knowledge → collection → Members.
 *
 *  Kept out of the component so it can be tested: `tsc` and `eslint` both pass on a
 *  member list that is ordered wrong, an owner row that looks like a removable
 *  member, or an "add member" form offered to someone whose POST would 403.
 *
 *  The access model this mirrors lives in backend/app/knowledge_access.py
 *  (may_read/may_write): admin, then owner, then an explicit
 *  ai_collection_members grant (editor > reader), then — read only — the legacy
 *  owner_id IS NULL "global" collection. GET/POST/DELETE
 *  /ai/collections/{name}/members (backend/app/api/ai_vectors.py) are all gated on
 *  may_write for that exact collection, same as ingest — not on knowledge:write
 *  alone and not on may_read. That is why `canManageMembers` below only recognises
 *  admin and owner: those are the two cases this module can know client-side
 *  without a round trip. An *editor* member also passes may_write on the server,
 *  but nothing short of asking the server tells us a given viewer is one — so the
 *  component treats a successful GET /members as the authoritative "yes" for that
 *  case, and this function's "no" only ever gates the optimistic, no-network path
 *  (skip showing the add form before ever risking a 403 for a plain reader).
 */

export type MemberRole = "reader" | "editor"

export interface RawMember {
  username: string
  role: MemberRole
  granted_at: string | null
}

export interface CollectionOwnership {
  owner_id: string | null
}

export interface Viewer {
  id: string
  role: string
}

export interface NamedViewer {
  id: string
  username: string
}

export interface OwnerRow {
  kind: "owner"
  isViewer: boolean
  // Known only when the viewer IS the owner — list_collections gives us owner_id,
  // never the owner's username, so anyone else's owner row cannot honestly show a
  // name. See buildAccessRows.
  username: string | null
}

export interface MemberRow {
  kind: "member"
  username: string
  role: MemberRole
  grantedAt: string | null
}

export type AccessRow = OwnerRow | MemberRow

/** Owner first (if any — a legacy owner_id IS NULL collection has none), then
 * members sorted by username so the list order doesn't depend on the order the
 * API happened to return rows in. */
export function buildAccessRows(
  collection: CollectionOwnership,
  viewer: NamedViewer,
  members: RawMember[],
): AccessRow[] {
  const rows: AccessRow[] = []
  if (collection.owner_id !== null) {
    const isViewer = collection.owner_id === viewer.id
    rows.push({ kind: "owner", isViewer, username: isViewer ? viewer.username : null })
  }
  const sorted = [...members].sort((a, b) => a.username.localeCompare(b.username))
  for (const m of sorted) {
    rows.push({ kind: "member", username: m.username, role: m.role, grantedAt: m.granted_at })
  }
  return rows
}

/** The fast, no-network answer to "may this viewer manage membership at all?" —
 * true only where the client already knows the answer for certain (admin, or the
 * owner of this exact collection). See the module docstring for why an editor
 * member is deliberately NOT covered here. */
export function canManageMembers(collection: CollectionOwnership, viewer: Viewer): boolean {
  if (viewer.role === "admin") return true
  return collection.owner_id !== null && collection.owner_id === viewer.id
}

export function roleLabel(role: MemberRole): string {
  return role === "editor" ? "Editor" : "Reader"
}

// A sentence a person can act on, not a permissions table. Matches
// knowledge_access.may_read/may_write exactly: reader → read-only; editor → read
// plus ingest/schedule/settings (write). Neither may delete the collection or
// manage membership beyond what an editor's may_write grant already covers.
export const ROLE_EXPLANATION =
  "Readers can search and ask. Editors can also ingest and change settings."
