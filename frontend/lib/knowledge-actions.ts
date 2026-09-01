/** Presentation logic for Knowledge → collection → Ingest / Schedule / Search / Ask.
 *
 *  Before B1 (backend/app/api/ai_vectors.py), `ingest-source` and `schedule` were
 *  `require_admin_or_internal` / `require_admin`, and this page hid them behind
 *  `getUser()?.role === "admin"` to match — which meant `ai_engineer`, the
 *  product's own stated target user, saw an Ingest tab whose "from S3/catalog"
 *  half (and the whole Schedule tab) 403'd for a role that was never going to be
 *  let in. Both routes are now gated on `knowledge:write` plus the same
 *  `_collection_id(write=True)` ownership/membership check every other write
 *  route on a collection already uses (backend/app/knowledge_access.py:
 *  may_write). `mayIngest` below mirrors that decision so the console can offer
 *  what the API actually accepts, not what a hardcoded admin check guessed at.
 *
 *  `mayAskQuestions` mirrors the simpler `ai:generate` gate on /ai/search and
 *  /ai/rag — the reason `business_analyst` (which holds knowledge:read but not
 *  ai:generate) can browse a collection's existence but not spend a model call
 *  against it.
 *
 *  Deliberately in terms of `permissions` (from `usePermissions()`, itself
 *  sourced from `GET /api/me/permissions`) rather than `getUser()?.role`: the
 *  console reads what the caller may do from the same source the API enforces
 *  from, not from the JWT sitting in localStorage.
 *
 *  `member_role` is the one input `mayIngest` cannot always be given: unlike
 *  ownership, a viewer's own `editor`/`reader` grant on *this* collection is not
 *  returned by `GET /ai/collections`, and — same as `lib/collection-members.ts`'s
 *  `canManageMembers` — nothing short of a membership lookup (which itself 403s
 *  for a plain reader, the exact case this is trying to distinguish) tells the
 *  client for certain. Pass it when the caller already has it; omitting it is
 *  honest, not a shortcut, and only ever makes this function say "no" when the
 *  real answer might be "yes" — the API's own 403 remains the actual boundary.
 */

export type MemberRole = "reader" | "editor"

export interface CollectionOwnership {
  owner_id: string | null
  /** This viewer's explicit ai_collection_members grant for this exact
   *  collection, when known. See the module docstring for why it is optional. */
  member_role?: MemberRole | null
}

export interface Viewer {
  id: string
  role: string
  permissions: Set<string>
}

/** May `viewer` ingest into, or schedule a refresh for, `collection`? The
 *  client-side twin of knowledge_access.may_write for the two routes B1 moved
 *  onto it. knowledge:write is checked first because both routes gate on it
 *  before ever resolving the collection — a caller who lacks it is refused
 *  before ownership/membership is even asked, same as `_collection_id` never
 *  runs for them. */
export function mayIngest(collection: CollectionOwnership, viewer: Viewer): boolean {
  if (!viewer.permissions.has("knowledge:write")) return false
  if (viewer.role === "admin") return true
  if (collection.owner_id === null) {
    // The legacy owner_id IS NULL "global" collection has no owner to delegate
    // write from — knowledge_access.may_write reserves it to an administrator,
    // already ruled out above.
    return false
  }
  return collection.owner_id === viewer.id || collection.member_role === "editor"
}

/** May `viewer` search or ask a question (spend a model call) against a
 *  collection they can already read? Matches the ai:generate gate on
 *  /ai/search and /ai/rag — independent of knowledge:write, which is why an
 *  ai_engineer and a business_analyst can disagree on it. Only needs the
 *  permission set, not identity or ownership, so it takes that alone rather
 *  than the full Viewer shape mayIngest needs. */
export function mayAskQuestions(viewer: Pick<Viewer, "permissions">): boolean {
  return viewer.permissions.has("ai:generate")
}
