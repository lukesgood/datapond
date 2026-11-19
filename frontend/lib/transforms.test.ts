import { test } from "node:test"
import assert from "node:assert/strict"
import { dagIdFor, emptyForm, formProblem, previewSql, runStrip, runSummary, saveBody, tablesRead } from "./transforms.ts"

const good = { ...emptyForm(), name: "daily revenue", target_table: "daily_revenue",
  sql: "SELECT date(o.ordered_at) AS day FROM refined.orders o JOIN refined.customers c USING (customer_id)" }

test("formProblem mirrors the API's refusals", () => {
  assert.equal(formProblem(good, true), null)
  assert.match(formProblem({ ...good, name: "bad;name" }, true)!, /Name/)
  assert.equal(formProblem({ ...good, name: "bad;name" }, false), null, "name is fixed when editing")
  assert.match(formProblem({ ...good, target_table: "1x" }, true)!, /Table/)
  assert.match(formProblem({ ...good, target_namespace: "refined" }, true)!, /different/)
  assert.match(formProblem({ ...good, sql: "DROP TABLE x" }, true)!, /SELECT/)
  assert.match(formProblem({ ...good, sql: "SELECT 1; SELECT 2" }, true)!, /one statement/)
  assert.equal(formProblem({ ...good, sql: "-- note\nWITH a AS (SELECT 1) SELECT * FROM a;" }, true), null)
})

test("saveBody sends name only when creating, never overwriting another", () => {
  const c = saveBody(good, true)
  assert.equal(c.name, "daily revenue"); assert.equal(c.overwrite, false)
  const e = saveBody({ ...good, description: "  " }, false)
  assert.equal("name" in e, false); assert.equal(e.description, null)
})

test("dagIdFor matches the backend", () => {
  assert.equal(dagIdFor("Daily Revenue-1"), "transform_daily_revenue_1")
})

test("previewSql wraps and limits", () => {
  assert.equal(previewSql("SELECT 1;"), "SELECT * FROM (\nSELECT 1\n) AS preview LIMIT 50")
})

test("tablesRead lists FROM/JOIN tables, not CTEs", () => {
  assert.deepEqual(tablesRead(good.sql), ["refined.orders", "refined.customers"])
  assert.deepEqual(tablesRead("WITH paid AS (SELECT * FROM raw.orders) SELECT * FROM paid JOIN raw.users u ON true"),
                   ["raw.orders", "raw.users"])
})

test("runStrip and runSummary", () => {
  const cells = runStrip([{ state: "success", end_date: "a" }, { state: "failed", execution_date: "b" }])
  assert.deepEqual(cells, [{ state: "success", at: "a" }, { state: "failed", at: "b" }])
  assert.equal(runSummary(cells), "Last 2 runs: 1 failed")
  assert.equal(runSummary([]), "No runs yet.")
  assert.equal(runSummary([cells[0]]), "Last 1 run: all succeeded")
})
