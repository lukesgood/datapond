/** What the pipeline builders write when someone fills in the Quality Check field.
 *
 *  The defect this pins: both builders emitted `@quality(table="x")` on a separate
 *  `check_x()` function. That call form does not exist in the DSL, and even if it did,
 *  a separate function attaches to no table — so every quality check configured in the
 *  console was silently dropped from the compiled pipeline.
 *
 *  `backend/tests/test_pipeline_quality_checks.py` holds the other half: it runs the
 *  literal produced here through the real compiler and asserts the check arrives on the
 *  table definition. Both sides quote the same string on purpose.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { qualityCheckName, qualityDecorator } from "./pipeline-quality.ts"

test("a condition becomes the decorator the DSL actually defines", () => {
  assert.equal(
    qualityDecorator("bronze_orders", "amount > 0"),
    '@quality.expect_or_fail("bronze_orders_quality", "amount > 0")',
  )
})

test("it is expect_or_fail, because the field says it halts on failure", () => {
  // expect() logs and expect_or_drop() filters rows — different promises from the one
  // the console's help text makes.
  const line = qualityDecorator("orders", "id IS NOT NULL")
  assert.match(line!, /expect_or_fail/)
  assert.doesNotMatch(line!, /expect_or_drop|expect\(/)
})

test("the dead call form is gone", () => {
  // The exact shape that shipped for months and reached no pipeline.
  assert.doesNotMatch(qualityDecorator("orders", "amount > 0")!, /@quality\(/)
})

test("no condition means no decorator, not an empty one", () => {
  assert.equal(qualityDecorator("orders", ""), null)
  assert.equal(qualityDecorator("orders", "   "), null)
  assert.equal(qualityDecorator("orders", undefined as unknown as string), null)
})

test("a condition is trimmed before it is written into Python", () => {
  assert.equal(
    qualityDecorator("orders", "  amount > 0  "),
    '@quality.expect_or_fail("orders_quality", "amount > 0")',
  )
})

test("quotes and backslashes survive as Python, not as a syntax error", () => {
  // A condition like status IN ("active") would otherwise close the string early and
  // produce a module that does not parse — the builder's output has to be valid Python
  // for the compiler to read anything at all.
  assert.equal(
    qualityDecorator("orders", 'status IN ("active")'),
    '@quality.expect_or_fail("orders_quality", "status IN (\\"active\\")")',
  )
  assert.equal(
    qualityDecorator("orders", "path LIKE 'a\\b%'"),
    '@quality.expect_or_fail("orders_quality", "path LIKE \'a\\\\b%\'")',
  )
})

test("the check carries a name a person can find in a report", () => {
  assert.equal(qualityCheckName("bronze_orders"), "bronze_orders_quality")
})


// ── the builders themselves ─────────────────────────────────────────────────

import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..")
const BUILDERS = [
  "app/pipelines/new/page.tsx",
  "components/pipelines/create-pipeline-modal.tsx",
]

for (const file of BUILDERS) {
  test(`${file} writes quality checks through the one helper`, () => {
    // Two builders, one DSL. They emitted the same wrong decorator independently,
    // which is the argument for both reading it from the same place — and for this
    // test naming both files rather than trusting a reviewer to notice the second.
    const source = readFileSync(join(ROOT, file), "utf8")
    assert.doesNotMatch(source, /@quality\(table=/, "still emits the call form the DSL has never defined")
    assert.match(source, /qualityDecorator/, "does not use lib/pipeline-quality.ts")
  })
}
