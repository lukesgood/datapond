/** Presentation logic for Knowledge → collection → Ingest/Schedule tabs, run by
 *  `npm test` (node:test). See knowledge-actions.ts for the module docstring.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { mayAskQuestions, mayIngest, mayWriteCollection } from "./knowledge-actions.ts"

// Every ingest route requires knowledge:write AND ai:generate — the second because
// all three of them spend model tokens. These four callers hold both, so the tests
// below are about ownership and membership, which is what they were written for; the
// caller who holds only the first has its own test at the bottom of the file.
const BOTH = ["knowledge:write", "ai:generate"]
const ADMIN = { id: "u-admin", role: "admin", permissions: new Set(BOTH) }
const OWNER = { id: "u-owner", role: "ai_engineer", permissions: new Set(BOTH) }
const EDITOR = { id: "u-editor", role: "ai_engineer", permissions: new Set(BOTH) }
const READER = { id: "u-reader", role: "ai_engineer", permissions: new Set(BOTH) }
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

test("a knowledge:write holder without ai:generate may not ingest — every ingest route embeds", () => {
  // E1 put ai:generate on POST /ai/collections/{name}/ingest, and the final-review
  // fix put it on ingest-source and schedule too: all three spend model tokens, one
  // of them (schedule) forever. A caller holding knowledge:write and not ai:generate
  // — a service-account key scoped to the first alone — gets a 403 from the API, so
  // offering them the control is offering a button that cannot work.
  const scoped = { id: "u-scoped", role: "ai_engineer", permissions: new Set(["knowledge:write"]) }
  assert.equal(mayIngest({ owner_id: scoped.id }, scoped), false)
  const admin = { id: "u-a", role: "admin", permissions: new Set(["knowledge:write"]) }
  assert.equal(mayIngest({ owner_id: null }, admin), false)
})

test("mayWriteCollection is knowledge:write plus ownership, without the spend permission", () => {
  // Deleting a collection, cancelling its schedule, and managing its members are all
  // knowledge:write alone on the API — none of them embeds anything. Folding
  // ai:generate into those controls would hide "cancel the schedule that is costing
  // us money" from exactly the caller most likely to want it.
  const scoped = { id: "u-scoped", role: "ai_engineer", permissions: new Set(["knowledge:write"]) }
  assert.equal(mayWriteCollection({ owner_id: scoped.id }, scoped), true)
  assert.equal(mayIngest({ owner_id: scoped.id }, scoped), false)
})

test("mayWriteCollection still refuses a caller without knowledge:write, and a stranger", () => {
  assert.equal(mayWriteCollection({ owner_id: VIEWER_NO_WRITE.id }, VIEWER_NO_WRITE), false)
  assert.equal(mayWriteCollection({ owner_id: OWNER.id }, READER), false)
  assert.equal(mayWriteCollection({ owner_id: OWNER.id, member_role: "editor" }, EDITOR), true)
  assert.equal(mayWriteCollection({ owner_id: null }, ADMIN), true)
  assert.equal(mayWriteCollection({ owner_id: null }, OWNER), false)
})
