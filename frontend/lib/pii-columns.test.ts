/** Name-based personal-data guesses for the setup page (./pii-columns.ts). */
import assert from "node:assert/strict"
import { test } from "node:test"
import { likelyPii, suggestedMasks } from "./pii-columns.ts"

test("personal columns are guessed by whole name parts", () => {
  for (const c of ["email", "customer_email", "phone_number", "mobile", "first_name", "name", "home_address", "zip", "birth_date", "dob", "card_number", "rrn", "ip"]) {
    assert.ok(likelyPii(c), c)
  }
  for (const c of ["hotel", "company", "panel_id", "status", "product_name", "account_id", "updated_at", "zipped", "tier", "detail"]) {
    assert.ok(!likelyPii(c), c)
  }
})

test("Korean column names count", () => {
  assert.ok(likelyPii("고객_전화번호"))
  assert.ok(likelyPii("주민등록번호"))
  assert.ok(!likelyPii("주문일자"))
})

test("a table's suggestion keeps the column order", () => {
  assert.deepEqual(suggestedMasks([{ name: "id" }, { name: "email" }, { name: "tier" }, { name: "phone" }]), ["email", "phone"])
})
