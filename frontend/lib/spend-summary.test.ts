/** What the AI Gateway page shows for "Total spend" (./spend-summary.ts).
 *
 *  GET /api/settings/ai/spend answers `{total_spend, keys_with_spend}` when the gateway
 *  can be read and `{unavailable}` when it cannot. Commit 0efb679 made that split so an
 *  unreadable gateway stops looking like a month with no spend, but the Virtual keys card
 *  kept reading `spend.total_spend.toFixed(4)` unconditionally — so every `unavailable`
 *  answer threw during render and took the AI Gateway page down with it. These tests pin
 *  the one property the page needs: any shape the endpoint can send renders, and only a
 *  real measurement renders as a dollar figure.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { totalSpendLabel } from "./spend-summary.ts"

test("a measured total renders as dollars", () => {
  assert.deepEqual(totalSpendLabel({ total_spend: 3.5, keys_with_spend: 2 }), { text: "$3.5000", measured: true })
})

test("a measured zero is still a measurement", () => {
  assert.deepEqual(totalSpendLabel({ total_spend: 0, keys_with_spend: 0 }), { text: "$0.0000", measured: true })
})

test("an unreadable gateway renders as not measured, with the reason, instead of throwing", () => {
  // The exact shape the live endpoint returned while the page was crashing.
  const label = totalSpendLabel({ unavailable: "gateway returned HTTP 422" })
  assert.equal(label.text, "—")
  assert.equal(label.measured, false)
  assert.match(label.title ?? "", /HTTP 422/)
})

test("no answer yet, or a failed fetch, is not zero either", () => {
  assert.deepEqual(totalSpendLabel(null), { text: "—", measured: false, title: "Not measured" })
})

test("a shape the endpoint should never send still renders, and never as a measurement", () => {
  for (const odd of [{}, { total_spend: "3.5" }, { total_spend: null }, { total_spend: Number.NaN }, [], "x", 42, undefined]) {
    assert.doesNotThrow(() => totalSpendLabel(odd), `threw for ${String(JSON.stringify(odd))}`)
    assert.equal(totalSpendLabel(odd).measured, false, `treated ${String(JSON.stringify(odd))} as a measurement`)
  }
})
