import test from "node:test"
import assert from "node:assert/strict"
import { effectivePii, lowersPii, lowersSensitivity, piiReason } from "./collection-protection.ts"

test("effective PII is the strictest of deployment, own mode and label floor", () => {
  assert.equal(effectivePii("mask", null, null), "mask")
  assert.equal(effectivePii("mask", "block", null), "block")
  assert.equal(effectivePii("off", null, "confidential"), "mask")
  assert.equal(effectivePii("mask", "mask", "restricted"), "block")
  assert.equal(effectivePii("off", "off", "internal"), "off")
})

test("lowering matches the backend ordering, inherit lowest", () => {
  assert.ok(lowersPii("block", "mask") && lowersPii("mask", null))
  assert.ok(!lowersPii(null, "off") && !lowersPii("mask", "block"))
  assert.ok(lowersSensitivity("restricted", "confidential") && lowersSensitivity("public", null))
  assert.ok(!lowersSensitivity("internal", "restricted"))
})

test("the reason names what raised the mode", () => {
  assert.equal(piiReason("mask", null, null), "inherited from the deployment")
  assert.equal(piiReason("off", "mask", "restricted"), "raised to block by the restricted label")
  assert.equal(piiReason("mask", "off", null), "the deployment default mask is stricter")
  assert.equal(piiReason("mask", "block", null), null)
})
