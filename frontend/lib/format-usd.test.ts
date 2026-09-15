import { test } from "node:test"
import assert from "node:assert/strict"
import { formatUsd } from "./format-usd.ts"

test("cents are the precision", () => {
  assert.equal(formatUsd(0.2994), "$0.30")
  assert.equal(formatUsd(3.5), "$3.50")
  assert.equal(formatUsd(1234.5), "$1,234.50")
})

test("zero is zero, and less than a cent says so", () => {
  assert.equal(formatUsd(0), "$0.00")
  assert.equal(formatUsd(0.000053), "<$0.01")
  assert.equal(formatUsd(-0.004), "-<$0.01")
  assert.equal(formatUsd(-2), "-$2.00")
})

test("a non-number is not dressed up as money", () => {
  assert.equal(formatUsd(Number.NaN), "—")
  assert.equal(formatUsd(Number.POSITIVE_INFINITY), "—")
})
