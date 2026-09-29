import { test } from "node:test"
import assert from "node:assert/strict"
import { budgetStatus, parseCap, unlistedCallers } from "./caller-budgets.ts"

test("status: blocked wins, then over, ok, uncapped", () => {
  assert.equal(budgetStatus({ spend: 0, max_budget: 5, blocked: true }), "blocked")
  assert.equal(budgetStatus({ spend: 5, max_budget: 5, blocked: false }), "over")
  assert.equal(budgetStatus({ spend: 1, max_budget: 5, blocked: false }), "ok")
  assert.equal(budgetStatus({ spend: 99, max_budget: null, blocked: false }), "uncapped")
})

test("a cap of zero is a cap", () => {
  assert.deepEqual(parseCap("0"), { value: 0 })
  assert.equal(budgetStatus({ spend: 0, max_budget: 0, blocked: false }), "over")
})

test("bad cap text is refused", () => {
  for (const t of ["", "  ", "abc", "-1", "Infinity"]) assert.ok("error" in parseCap(t))
  assert.deepEqual(parseCap(" 12.5 "), { value: 12.5 })
})

test("callers already listed or repeated are not offered", () => {
  const listed = [{ user_id: "a", alias: null, spend: 0, max_budget: 1, blocked: false }]
  const out = unlistedCallers(
    [{ id: "a", label: "A" }, { id: "b", label: "B" }, { id: "b", label: "B" }], listed)
  assert.deepEqual(out, [{ id: "b", label: "B" }])
})
