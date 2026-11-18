import test from "node:test"
import assert from "node:assert/strict"
import { breadcrumbs, joinKey, looksLikeTable } from "./storage-path.ts"

test("breadcrumbs walk the prefix", () => {
  assert.deepEqual(breadcrumbs(""), [])
  assert.deepEqual(breadcrumbs("warehouse/default.db/"), [
    { name: "warehouse", prefix: "warehouse/" },
    { name: "default.db", prefix: "warehouse/default.db/" },
  ])
})

test("upload key goes into the current folder", () => {
  assert.equal(joinKey("", "a.csv"), "a.csv")
  assert.equal(joinKey("in/box/", "a.csv"), "in/box/a.csv")
})

test("table hint: a table root or its data/metadata folders", () => {
  assert.equal(looksLikeTable("warehouse/default.db/orders/", ["data", "metadata"]), true)
  assert.equal(looksLikeTable("warehouse/default.db/orders/data/", []), true)
  assert.equal(looksLikeTable("warehouse/default.db/orders/data/region=kr/", []), true)
  assert.equal(looksLikeTable("warehouse/default.db/", ["orders", "customers"]), false)
  assert.equal(looksLikeTable("exports/", ["data"]), false)
})
