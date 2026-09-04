/** When the confirm button may be pressed.
 *
 *  The server checks this again — this is not the gate, it is the part that stops a
 *  person submitting a mismatch and being told off for it. The two must agree, so
 *  the forgiveness here matches the server's: case and surrounding quotes.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { canConfirm } from "./destructive-card-state.ts"

test("the exact name confirms", () => {
  assert.equal(canConfirm("crm.customers", "crm.customers"), true)
})

test("a different name does not", () => {
  assert.equal(canConfirm("crm.orders", "crm.customers"), false)
})

test("nothing typed does not", () => {
  assert.equal(canConfirm("", "crm.customers"), false)
  assert.equal(canConfirm("   ", "crm.customers"), false)
})

test("case and surrounding quotes are forgiven, exactly as the server forgives them", () => {
  for (const typed of [' "CRM.Customers" ', "`crm.customers`", "CRM.CUSTOMERS"]) {
    assert.equal(canConfirm(typed, "crm.customers"), true, typed)
  }
})

test("a partial name does not confirm", () => {
  assert.equal(canConfirm("customers", "crm.customers"), false)
})

test("an absent target never confirms, whatever is typed", () => {
  // A card with no target is a card the server will refuse. Do not let the button
  // look pressable.
  assert.equal(canConfirm("anything", ""), false)
})

test("a single layer of surrounding quotes and spaces confirms, not just bare quotes", () => {
  assert.equal(canConfirm(" 'crm.customers' ", "crm.customers"), true)
})

test("nested quotes of different kinds, with spaces outside them, confirm", () => {
  assert.equal(canConfirm('  "`crm.customers`"  ', "crm.customers"), true)
})

test("a partial name still does not confirm", () => {
  assert.equal(canConfirm("customers", "crm.customers"), false)
})

test("an empty target still does not confirm whatever is typed", () => {
  assert.equal(canConfirm("crm.customers", ""), false)
})
