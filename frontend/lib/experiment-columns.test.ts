import { test } from "node:test"
import assert from "node:assert/strict"
import { metricColumns, mlflowErrorText } from "../components/experiments/compare-runs.ts"

const run = (...keys: string[]) => ({ data: { metrics: keys.map(key => ({ key })) } })

test("metricColumns: most-logged first, ties by name, capped", () => {
  assert.deepEqual(metricColumns([run("auc", "f1", "loss"), run("auc", "f1"), run("auc", "zeta")], 2), ["auc", "f1"])
  assert.deepEqual(metricColumns([run("b"), run("a")]), ["a", "b"])
  assert.deepEqual(metricColumns([]), [])
})

test("metricColumns counts a key once per run", () => {
  assert.deepEqual(metricColumns([run("x", "x", "x"), run("y"), run("y")], 1), ["y"])
})

test("mlflowErrorText never shows a bare status", () => {
  assert.equal(mlflowErrorText(502, "load experiments"), "MLflow is not reachable. Check Infrastructure.")
  assert.equal(mlflowErrorText(403, "delete this experiment"), "You may not delete this experiment.")
  assert.match(mlflowErrorText(500, "load runs"), /Could not load runs \(MLflow answered 500\)/)
})
