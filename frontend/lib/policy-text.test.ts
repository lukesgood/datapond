import test from "node:test"
import assert from "node:assert/strict"
import { describeMask, describeRowPolicy } from "./policy-text.ts"

test("row policy in words", () => {
  assert.equal(
    describeRowPolicy({ filter_expression: "region = 'x'", roles: ["business_analyst"], exempt_roles: ["auditor"], enabled: true }),
    "business_analyst see only rows where region = 'x'. auditor see every row. Everyone else is not affected by this policy.")
  assert.match(describeRowPolicy({ filter_expression: "a", roles: [], exempt_roles: [], enabled: true }), /filters nobody/)
  assert.match(describeRowPolicy({ filter_expression: "a", roles: ["x"], exempt_roles: [], enabled: false }), /^Off/)
})

test("mask in words", () => {
  assert.equal(describeMask({ masking_type: "hash", column_name: "email", roles: ["viewer", "analyst"], enabled: true }),
    "For viewer and analyst, email is replaced by a hash (joins still work). Everyone else sees the stored value.")
  assert.match(describeMask({ masking_type: "full", column_name: "email", roles: [], enabled: true }), /masks nothing/)
})
