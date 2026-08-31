/** Presentation logic for Knowledge → collection → Members, run by `npm test` (node:test).
 *
 *  Split out of the component for the same reason system-events was: `tsc` and
 *  `eslint` both pass on a member list that is ordered wrong or a permission check
 *  that shows an add form to a reader whose POST would 403.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { buildAccessRows, canManageMembers, ROLE_EXPLANATION, roleLabel } from "./collection-members.ts"

const ADMIN = { id: "u-admin", role: "admin" }
const OWNER = { id: "u-owner", role: "data_scientist" }
const OTHER = { id: "u-other", role: "data_scientist" }

test("the owner appears first and is not a removable member row", () => {
  const rows = buildAccessRows(
    { owner_id: OWNER.id },
    { id: OWNER.id, username: "alice" },
    [{ username: "bob", role: "reader", granted_at: null }],
  )
  assert.equal(rows.length, 2)
  assert.deepEqual(rows[0], { kind: "owner", isViewer: true, username: "alice" })
  assert.equal(rows[1].kind, "member")
})

test("members sort by username, independent of the order the API returned them in", () => {
  const rows = buildAccessRows(
    { owner_id: OWNER.id },
    { id: OTHER.id, username: "carol" },
    [
      { username: "zed", role: "editor", granted_at: null },
      { username: "amy", role: "reader", granted_at: null },
    ],
  )
  const members = rows.filter(r => r.kind === "member")
  assert.deepEqual(members.map(m => (m as { username: string }).username), ["amy", "zed"])
})

test("the viewer's own owner row is not left anonymous", () => {
  const rows = buildAccessRows({ owner_id: OWNER.id }, { id: OWNER.id, username: "alice" }, [])
  assert.deepEqual(rows[0], { kind: "owner", isViewer: true, username: "alice" })
})

test("someone else's owner row carries no username the caller was never given", () => {
  // list_collections returns owner_id, never the owner's username, for anyone but
  // the owner themself — inventing one here would show a name nobody confirmed.
  const rows = buildAccessRows({ owner_id: OWNER.id }, { id: OTHER.id, username: "carol" }, [])
  assert.deepEqual(rows[0], { kind: "owner", isViewer: false, username: null })
})

test("a legacy global collection (owner_id null) has no owner row at all", () => {
  const rows = buildAccessRows({ owner_id: null }, { id: OTHER.id, username: "carol" },
    [{ username: "bob", role: "reader", granted_at: null }])
  assert.equal(rows.every(r => r.kind !== "owner"), true)
  assert.equal(rows.length, 1)
})

test("an admin may manage membership on a collection they neither own nor belong to", () => {
  assert.equal(canManageMembers({ owner_id: OWNER.id }, ADMIN), true)
})

test("the owner may manage their own collection's membership", () => {
  assert.equal(canManageMembers({ owner_id: OWNER.id }, OWNER), true)
})

test("someone who is neither owner nor admin does not get an add form offered client-side", () => {
  // The server also lets an *editor* member manage membership (may_write), which
  // this quick client-side check cannot know without asking — the component treats
  // a successful GET /members as the authoritative override for that case. This
  // check exists so a plain reader never even sees the form fire off a POST that
  // would 403.
  assert.equal(canManageMembers({ owner_id: OWNER.id }, OTHER), false)
})

test("role labels and the explanatory sentence match the server's actual rules", () => {
  assert.equal(roleLabel("reader"), "Reader")
  assert.equal(roleLabel("editor"), "Editor")
  assert.match(ROLE_EXPLANATION, /search and ask/)
  assert.match(ROLE_EXPLANATION, /ingest/)
})
