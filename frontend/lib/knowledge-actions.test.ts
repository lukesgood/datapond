/** Presentation logic for Knowledge → collection → Ingest/Schedule tabs, run by
 *  `npm test` (node:test). See knowledge-actions.ts for the module docstring.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { mayAskQuestions, mayIngest } from "./knowledge-actions.ts"

const ADMIN = { id: "u-admin", role: "admin", permissions: new Set(["knowledge:write"]) }
const OWNER = { id: "u-owner", role: "ai_engineer", permissions: new Set(["knowledge:write"]) }
const EDITOR = { id: "u-editor", role: "ai_engineer", permissions: new Set(["knowledge:write"]) }
const READER = { id: "u-reader", role: "ai_engineer", permissions: new Set(["knowledge:write"]) }
const VIEWER_NO_WRITE = { id: "u-viewer", role: "viewer", permissions: new Set<string>() }

test("an admin may ingest into any collection, owned or not", () => {
  assert.equal(mayIngest({ owner_id: OWNER.id }, ADMIN), true)
  assert.equal(mayIngest({ owner_id: null }, ADMIN), true)
})

test("the owner may ingest into their own collection", () => {
  assert.equal(mayIngest({ owner_id: OWNER.id }, OWNER), true)
})

test("an editor member may ingest, even though they don't own the collection", () => {
  assert.equal(
    mayIngest({ owner_id: OWNER.id, member_role: "editor" }, EDITOR),
    true,
  )
})

test("a reader member may not ingest", () => {
  assert.equal(
    mayIngest({ owner_id: OWNER.id, member_role: "reader" }, READER),
    false,
  )
})

test("a caller without knowledge:write may not ingest, even if they own the collection", () => {
  // Mirrors the backend: since B1, require_permission("knowledge:write") runs
  // before _collection_id ever resolves ownership.
  assert.equal(mayIngest({ owner_id: VIEWER_NO_WRITE.id }, VIEWER_NO_WRITE), false)
})

test("a knowledge:write holder who is neither owner nor a known member may not ingest", () => {
  assert.equal(mayIngest({ owner_id: OWNER.id }, READER), false)
})

test("nobody but an admin may write the legacy unowned/global collection", () => {
  assert.equal(mayIngest({ owner_id: null }, OWNER), false)
  assert.equal(mayIngest({ owner_id: null }, ADMIN), true)
})

test("mayAskQuestions follows ai:generate, independent of knowledge:write", () => {
  const analyst = { id: "u-ba", role: "business_analyst", permissions: new Set(["knowledge:read"]) }
  assert.equal(mayAskQuestions(analyst), false)
  const withGenerate = { id: "u-ba2", role: "business_analyst", permissions: new Set(["ai:generate"]) }
  assert.equal(mayAskQuestions(withGenerate), true)
})
