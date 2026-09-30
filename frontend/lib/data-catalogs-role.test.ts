import { test } from "node:test"
import assert from "node:assert/strict"
import { emptyForm, validateForm, configOf } from "./data-catalogs.ts"

const ROLE = "arn:aws:iam::210987654321:role/catalog-read"

function glue(over: Record<string, unknown>) {
  return { ...emptyForm("glue"), name: "partner", ...over } as ReturnType<typeof emptyForm>
}

test("a glue role ARN is checked, an empty one is fine", () => {
  assert.equal(validateForm(glue({}), { creating: true }).role_arn, undefined)
  assert.equal(validateForm(glue({ role_arn: ROLE }), { creating: true }).role_arn, undefined)
  assert.ok(validateForm(glue({ role_arn: "arn:aws:iam::12:role/x" }), { creating: true }).role_arn)
})

test("an external id needs a role and a sane value", () => {
  assert.ok(validateForm(glue({ external_id: "abc-123" }), { creating: true }).external_id)
  assert.equal(validateForm(glue({ role_arn: ROLE, external_id: "abc-123" }),
    { creating: true }).external_id, undefined)
  assert.ok(validateForm(glue({ role_arn: ROLE, external_id: "a" }), { creating: true }).external_id)
})

test("role fields are sent for glue and only glue", () => {
  assert.deepEqual(configOf(glue({ role_arn: ROLE, external_id: "abc-123" })),
    { role_arn: ROLE, external_id: "abc-123" })
  assert.deepEqual(configOf({ ...emptyForm("polaris"), role_arn: ROLE }), {})
})
