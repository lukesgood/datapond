/** Presentation logic for the support tier a capability carries, run by `npm test`
 *  (node:test). See capability-support.ts for the module docstring.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { supportBadge, supportTier } from "./capability-support.ts"

test("a capability the backend marks experimental returns that tier", () => {
  assert.equal(supportTier("streaming", { streaming: "experimental" }), "experimental")
})

test("a capability absent from the support map is supported — returns null", () => {
  assert.equal(supportTier("knowledge", { streaming: "experimental" }), null)
  assert.equal(supportTier("streaming", {}), null)
})

test("a tier this build does not know is not rendered as unlabelled text — returns null", () => {
  // A newer backend may one day send a third tier. Until this module knows the
  // word for it, showing the raw string would put unreviewed text in the UI.
  assert.equal(supportTier("streaming", { streaming: "beta" }), null)
})

test("supportBadge('preview') names the refusal", () => {
  const badge = supportBadge("preview")
  assert.equal(badge.label, "Preview")
  assert.match(badge.title, /refus/i)
})

test("supportBadge('experimental') says the wiring is supported and the upstream project is not", () => {
  const badge = supportBadge("experimental")
  assert.equal(badge.label, "Experimental")
  assert.match(badge.title, /wiring is supported/i)
  assert.match(badge.title, /project itself is not|not.*support/i)
})
