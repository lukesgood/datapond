import { test } from "node:test"
import assert from "node:assert/strict"
import { canApply, exportBody, mirrorTone, summaryLine, type ExportResult } from "./catalog-export.ts"

const plan = (actions: string[], applied = false): ExportResult => ({
  source: "a", target: "b", applied, mode: "mirror", summary: {}, allowed_locations_needed: [],
  tables: actions.map((action, i) => ({ schema: "s", table: `t${i}`, action })),
})

test("the body omits a blank schema and carries mode and apply", () => {
  assert.deepEqual(exportBody({ target: "b", schema: " ", mode: "mirror", apply: false }),
    { target: "b", mode: "mirror", apply: false })
  assert.deepEqual(exportBody({ target: "b", schema: "sales", mode: "move", apply: true }),
    { target: "b", mode: "move", apply: true, schema: "sales" })
})

test("a plan is applicable only when something would be registered", () => {
  assert.equal(canApply(null), false)
  assert.equal(canApply(plan(["exists", "skip"])), false)
  assert.equal(canApply(plan(["register", "exists"])), true)
  assert.equal(canApply(plan(["registered"], true)), false)
})

test("summary and mirror tone read plainly", () => {
  assert.equal(summaryLine({ registered: 3, failed: 1, exists: 0 }), "3 registered, 1 failed")
  assert.equal(summaryLine({}), "nothing to do")
  assert.equal(mirrorTone("fresh"), "good")
  assert.equal(mirrorTone("diverged"), "warn")
  assert.equal(mirrorTone("error"), "bad")
})
