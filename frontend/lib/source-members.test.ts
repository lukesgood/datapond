/** Presentation logic for a source's Access panel, run by `npm test` (node:test).
 *
 *  The rules here are not the collection rules, and that is the whole reason this
 *  file exists: an *unowned* source is the state every connector and transform is in
 *  until someone creates a new one, and anyone holding the write permission may still
 *  manage it — see backend/app/resource_access.py's SOURCE / TRANSFORM rules. Getting
 *  that wrong in the UI means either hiding controls that work or offering ones that
 *  403.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import {
  buildSourceAccessRows, canManageSourceMembers, ownershipSummary,
  SOURCE_ROLE_EXPLANATION,
} from "./source-members.ts"

const ADMIN = { id: "u-admin", role: "admin", permissions: new Set<string>() }
const OWNER = { id: "u-owner", role: "data_engineer", permissions: new Set(["connector:write"]) }
const OTHER = { id: "u-other", role: "data_engineer", permissions: new Set(["connector:write"]) }
const VIEWER = { id: "u-viewer", role: "viewer", permissions: new Set<string>() }

const OWNED = { owner_id: OWNER.id, owner: "alice" }
const UNOWNED = { owner_id: null, owner: null }

test("the owner is named from the API, not guessed from the viewer", () => {
  // Unlike the collection endpoint, GET /connectors/{id}/members returns the owner's
  // username — so a viewer who is not the owner still sees whose source it is, which
  // is the whole point of showing ownership at all.
  const rows = buildSourceAccessRows(OWNED, OTHER, [])
  assert.deepEqual(rows[0], { kind: "owner", isViewer: false, username: "alice" })
})

test("an unowned source has no owner row to show", () => {
  const rows = buildSourceAccessRows(UNOWNED, OTHER, [
    { username: "bob", role: "reader", granted_at: null },
  ])
  assert.equal(rows.length, 1)
  assert.equal(rows[0].kind, "member")
})

test("members sort by username, independent of what order the API returned", () => {
  const rows = buildSourceAccessRows(OWNED, OWNER, [
    { username: "zed", role: "editor", granted_at: null },
    { username: "amy", role: "reader", granted_at: null },
  ])
  const members = rows.filter(r => r.kind === "member") as Array<{ username: string }>
  assert.deepEqual(members.map(m => m.username), ["amy", "zed"])
})

test("the owner and an admin may manage sharing", () => {
  assert.equal(canManageSourceMembers(OWNED, OWNER, "connector:write"), true)
  assert.equal(canManageSourceMembers(OWNED, ADMIN, "connector:write"), true)
})

test("a stranger holding the write permission may not manage someone else's source", () => {
  // The exact hole D2 closed on the API: connector:write is not a key to every
  // connector. Offering the controls here would just produce a 403.
  assert.equal(canManageSourceMembers(OWNED, OTHER, "connector:write"), false)
})

test("an unowned source stays manageable by whoever holds the write permission", () => {
  // Compatibility, and the case that would break a live deployment if the UI got it
  // wrong: every connector that predates 0006 is unowned, and the data engineers who
  // manage them are not admins.
  assert.equal(canManageSourceMembers(UNOWNED, OTHER, "connector:write"), true)
  assert.equal(canManageSourceMembers(UNOWNED, VIEWER, "connector:write"), false)
})

test("the transform permission is a parameter, not a second copy of the rule", () => {
  const engineer = { id: "u-e", role: "data_engineer", permissions: new Set(["pipeline:write"]) }
  assert.equal(canManageSourceMembers(UNOWNED, engineer, "pipeline:write"), true)
  assert.equal(canManageSourceMembers(UNOWNED, engineer, "connector:write"), false)
})

test("ownership is summarised in a sentence, not a permissions table", () => {
  assert.match(ownershipSummary(OWNED, OWNER), /^You own this/)
  assert.match(ownershipSummary(OWNED, OTHER), /alice/)
  assert.match(ownershipSummary(UNOWNED, OTHER), /everyone|anyone/i)
})

test("an owner the API did not name is still reported as someone else's", () => {
  // Falls back rather than claiming the source is unowned — the difference matters:
  // one means "ask that person", the other means "help yourself".
  const summary = ownershipSummary({ owner_id: "u-someone", owner: null }, OTHER)
  assert.match(summary, /someone else/i)
  assert.doesNotMatch(summary, /everyone/i)
})

test("the role explanation describes what the two roles actually do here", () => {
  assert.match(SOURCE_ROLE_EXPLANATION, /sync/i)
})
