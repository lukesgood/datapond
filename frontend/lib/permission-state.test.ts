/** permissionState (./permission-state.ts), run by `npm test` (node:test).
 *
 *  The whole point of this function is the case a plain boolean cannot express: a
 *  failed permissions fetch and an honest "no" both used to read as `allowed: false`.
 *  These tests exist to pin the one distinction that matters — `error` (or not yet
 *  `loaded`) always wins over `allowed`, so a refusal never gets reported as a
 *  connectivity problem and a connectivity problem never gets reported as a refusal.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { permissionState } from "./permission-state.ts"

test("allowed once loaded, without error, and the permission is held", () => {
  assert.equal(permissionState({ loaded: true, error: false, allowed: true }), "allowed")
})

test("denied once loaded, without error, and the permission is not held", () => {
  assert.equal(permissionState({ loaded: true, error: false, allowed: false }), "denied")
})

test("unknown when the fetch failed, even though allowed is false — the case a boolean can't express", () => {
  assert.equal(permissionState({ loaded: false, error: true, allowed: false }), "unknown")
})

test("error still wins even if a stale `loaded: true` and `allowed: true` linger from an earlier successful fetch", () => {
  // Belt-and-braces: the caller (PermissionProvider) should never produce this
  // combination, but the rule itself must not depend on that — an error means the
  // current picture cannot be trusted, whatever loaded/allowed happen to say.
  assert.equal(permissionState({ loaded: true, error: true, allowed: true }), "unknown")
})

test("unknown while still loading and nothing has failed yet", () => {
  assert.equal(permissionState({ loaded: false, error: false, allowed: false }), "unknown")
})

test("denied is not the same value as unknown", () => {
  const denied = permissionState({ loaded: true, error: false, allowed: false })
  const unknown = permissionState({ loaded: false, error: true, allowed: false })
  assert.notEqual(denied, unknown)
})
