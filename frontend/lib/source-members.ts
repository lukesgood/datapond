/** Presentation logic for a source's Access panel — a connector, or a saved transform.
 *
 *  The access model this mirrors is backend/app/resource_access.py, `SOURCE` and
 *  `TRANSFORM`: admin, then owner, then an explicit connector_members /
 *  transform_members grant (editor > reader), then — for a source, unlike a
 *  collection — an *unowned* row, which stays readable by everyone and writable by
 *  anyone holding the kind's write permission. That last branch is not a detail: every
 *  connector and transform that predates migration 0006 is unowned, so a UI that
 *  treated unowned as "admins only" would hide working controls from every data
 *  engineer on every existing deployment.
 *
 *  Deliberately separate from lib/collection-members.ts rather than sharing its
 *  functions. The two differ in what the API tells us and in what the rules are:
 *  GET /connectors/{id}/members returns the owner's *username*, which the collection
 *  endpoint does not, and the unowned branch above has no equivalent there. Sharing
 *  the code would mean a parameter for each of those differences and a function that
 *  reads as neither rule — the backend shares the decision because it is genuinely one
 *  decision; here it is two presentations of it.
 */

export type MemberRole = "reader" | "editor"

export interface RawMember {
  username: string
  role: MemberRole
  granted_at: string | null
}

/** What `GET /{connectors|transforms}/{id}/members` says about ownership. */
export interface SourceOwnership {
  owner_id: string | null
  /** The owner's username, or null when the source has no owner. */
  owner: string | null
}

export interface Viewer {
  id: string
  role: string
  permissions: Set<string>
}

export interface OwnerRow {
  kind: "owner"
  isViewer: boolean
  username: string | null
}

export interface MemberRow {
  kind: "member"
  username: string
  role: MemberRole
  grantedAt: string | null
}

export type AccessRow = OwnerRow | MemberRow

/** Owner first when there is one, then members sorted by username so the order does
 *  not depend on what order the API happened to return rows in. */
export function buildSourceAccessRows(
  ownership: SourceOwnership,
  viewer: { id: string },
  members: RawMember[],
): AccessRow[] {
  const rows: AccessRow[] = []
  if (ownership.owner_id !== null) {
    rows.push({
      kind: "owner",
      isViewer: ownership.owner_id === viewer.id,
      username: ownership.owner,
    })
  }
  for (const m of [...members].sort((a, b) => a.username.localeCompare(b.username))) {
    rows.push({ kind: "member", username: m.username, role: m.role, grantedAt: m.granted_at })
  }
  return rows
}

/** May this viewer add and remove people on this source?
 *
 *  The client-side twin of resource_access.may_write for a source. Unlike the
 *  collection panel, this one can answer the unowned case with certainty, because the
 *  rule for it is a permission the client already knows it holds — so the panel does
 *  not have to discover it from a 403.
 *
 *  An *editor* grant also passes on the server and is still not decidable here; the
 *  panel treats a successful GET /members as the authoritative yes for that case, the
 *  same way the collection panel does.
 */
export function canManageSourceMembers(
  ownership: SourceOwnership,
  viewer: Viewer,
  writePermission: string,
): boolean {
  if (viewer.role === "admin") return true
  if (ownership.owner_id !== null) return ownership.owner_id === viewer.id
  return viewer.permissions.has(writePermission)
}

/** One sentence saying whose source this is — the question the panel exists to answer.
 *
 *  An owner whose username the API did not return still reads as someone else's, never
 *  as unowned: "ask that person" and "help yourself" are different answers and must not
 *  collapse into each other when a name is missing.
 */
export function ownershipSummary(ownership: SourceOwnership, viewer: { id: string }): string {
  if (ownership.owner_id === null) {
    return "Nobody owns this source, so everyone signed in can see it. Sources created from now on belong to whoever creates them."
  }
  if (ownership.owner_id === viewer.id) return "You own this source."
  return ownership.owner
    ? `Owned by ${ownership.owner}.`
    : "Owned by someone else."
}

export function roleLabel(role: MemberRole): string {
  return role === "editor" ? "Editor" : "Reader"
}

// What the two roles actually do on a source, per resource_access.may_read/may_write:
// a reader sees it and its sync history; an editor also runs and changes it.
export const SOURCE_ROLE_EXPLANATION =
  "Readers can see this source and its sync history. Editors can also sync, edit and schedule it."
