import { test } from "node:test"
import assert from "node:assert/strict"
import { isInvalidRule, isRule, ruleError } from "./chunk-rule.ts"

test("letters, digits and underscores up to 64 are accepted", () => {
  assert.equal(ruleError({ metadata_key: "dept_1", user_attribute: "Department" }), null)
  assert.equal(ruleError({ metadata_key: "a".repeat(64), user_attribute: "b" }), null)
})

test("empty, spaced, punctuated or overlong names are refused", () => {
  for (const bad of ["", "bad key", "a-b", "a.b", "a".repeat(65)]) {
    assert.ok(ruleError({ metadata_key: bad, user_attribute: "d" }))
    assert.ok(ruleError({ metadata_key: "d", user_attribute: bad }))
  }
})

test("a stored rule is told apart from none and from an unreadable one", () => {
  assert.equal(isRule({ metadata_key: "dept", user_attribute: "department" }), true)
  assert.equal(isRule(null), false)
  assert.equal(isRule({ invalid: true }), false)
  assert.equal(isInvalidRule({ invalid: true }), true)
  assert.equal(isInvalidRule(null), false)
})
