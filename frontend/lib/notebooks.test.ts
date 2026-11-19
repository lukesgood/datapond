import { test } from "node:test"
import assert from "node:assert/strict"
import { ago, jupyterState, kernelLabel, labUrl, sessionFor, sortNotebooks, withIpynb } from "./notebooks.ts"

const rows = [
  { name: "b.ipynb", path: "analysis/b.ipynb", last_modified: "2026-11-01T00:00:00Z" },
  { name: "a.ipynb", path: "a.ipynb", last_modified: "2026-11-18T00:00:00Z" },
]

test("sortNotebooks by change or name, filtered by path", () => {
  assert.deepEqual(sortNotebooks(rows, "changed", "").map(r => r.name), ["a.ipynb", "b.ipynb"])
  assert.deepEqual(sortNotebooks(rows, "name", "").map(r => r.name), ["a.ipynb", "b.ipynb"])
  assert.deepEqual(sortNotebooks(rows, "changed", "analysis").map(r => r.name), ["b.ipynb"])
})

test("kernels come from sessions, never a default", () => {
  const s = [{ id: "s1", name: "b", path: "analysis/b.ipynb", type: "notebook", kernel: { id: "k", name: "python3" } }]
  assert.equal(sessionFor("analysis/b.ipynb", s)?.id, "s1")
  assert.equal(sessionFor("a.ipynb", s), null)
  assert.equal(kernelLabel("python3"), "Python 3")
  assert.equal(kernelLabel("ir"), "ir")
  assert.equal(kernelLabel(undefined), "")
})

test("ago, jupyterState, withIpynb, labUrl", () => {
  const now = new Date("2026-11-19T00:00:00Z")
  assert.equal(ago("2026-11-18T23:48:00Z", now), "12 min ago")
  assert.equal(ago("2026-11-16T00:00:00Z", now), "3 days ago")
  assert.equal(ago(null, now), "—")
  assert.equal(jupyterState("managed").canOpen, true)
  assert.notEqual(jupyterState("managed").label, "offline")
  assert.equal(jupyterState("unhealthy").canOpen, false)
  assert.equal(withIpynb(" churn "), "churn.ipynb")
  assert.equal(labUrl("https://x/jupyter", "my dir/a b.ipynb"), "https://x/jupyter/lab/tree/my%20dir/a%20b.ipynb")
})
