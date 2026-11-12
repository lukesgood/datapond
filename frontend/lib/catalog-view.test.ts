import { test } from "node:test"
import assert from "node:assert/strict"
import { catalogTypeOf, chipKey, inChip, namespaceChips } from "./catalog-view.ts"

const tables = [
  { name: "a", namespace: "public", catalog: "iceberg" },
  { name: "b", namespace: "public", catalog: "src_shop" },
  { name: "c", namespace: "public", catalog: "src_shop" },
  { name: "d", namespace: "lake", catalog: "iceberg" },
]
const namespaces = [
  { name: "public", catalog: "iceberg" }, { name: "lake", catalog: "iceberg" },
  { name: "public", catalog: "src_shop" },
]

test("chips are per catalog and namespace with their own counts", () => {
  const chips = namespaceChips(tables, namespaces)
  assert.equal(chips.length, 3)
  const byKey = Object.fromEntries(chips.map(c => [c.key, c]))
  assert.equal(byKey[chipKey("iceberg", "public")].count, 1)
  assert.equal(byKey[chipKey("src_shop", "public")].count, 2)
  assert.equal(byKey[chipKey("iceberg", "lake")].label, "lake")
})

test("the catalog shows in the label only when the namespace name repeats", () => {
  const labels = namespaceChips(tables, namespaces).map(c => c.label).sort()
  assert.deepEqual(labels, ["iceberg.public", "lake", "src_shop.public"])
})

test("filtering uses both catalog and namespace", () => {
  const sel = chipKey("src_shop", "public")
  assert.deepEqual(tables.filter(t => inChip(sel, t)).map(t => t.name), ["b", "c"])
  assert.equal(tables.filter(t => inChip("all", t)).length, 4)
})

test("a table in a namespace the listing missed still gets a chip", () => {
  const chips = namespaceChips([{ name: "x", namespace: "n", catalog: "c" }], [])
  assert.equal(chips[0].count, 1)
})

test("tables of a Trino source catalog are typed source", () => {
  const reg = [{ name: "shop", kind: "trino_source", engine_catalog: "src_shop" },
    { name: "lake", kind: "glue", engine_catalog: "iceberg" }]
  assert.equal(catalogTypeOf({ catalog: "src_shop" }, reg), "source")
  assert.equal(catalogTypeOf({ catalog: "iceberg" }, reg), "managed")
  assert.equal(catalogTypeOf({ catalog: "iceberg", catalog_type: "external" }, reg), "external")
})
