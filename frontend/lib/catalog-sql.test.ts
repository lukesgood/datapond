import test from "node:test"
import assert from "node:assert/strict"
import { engineCatalogOf, quoteIdent, tableSelectSql } from "./catalog-sql.ts"

test("default catalog: two-part name", () => {
  assert.equal(tableSelectSql("default", "orders"), 'SELECT * FROM "default"."orders" LIMIT 100')
})

test("another catalog: three-part name with the engine catalog", () => {
  assert.equal(tableSelectSql("default", "orders", "polaris_lake"), 'SELECT * FROM "polaris_lake"."default"."orders" LIMIT 100')
})

test("quotes are escaped", () => {
  assert.equal(quoteIdent('a"b'), '"a""b"')
})

test("engine catalog lookup", () => {
  const cats = [{ name: "AwsDataCatalog", engine_catalog: "iceberg" }, { name: "lake2", engine_catalog: "" }]
  assert.equal(engineCatalogOf(cats, "AwsDataCatalog"), "iceberg")
  assert.equal(engineCatalogOf(cats, "lake2"), null)
  assert.equal(engineCatalogOf(cats, "missing"), null)
})

test("engine catalog lookup by the engine name, as table cards link", () => {
  const cats = [{ name: "AwsDataCatalog", engine_catalog: "iceberg" }, { name: "polaris", engine_catalog: "polaris_lake" }]
  assert.equal(engineCatalogOf(cats, "iceberg"), "iceberg")
  assert.equal(engineCatalogOf(cats, "POLARIS_LAKE"), "polaris_lake")
  assert.equal(engineCatalogOf(cats, "awsdatacatalog"), "iceberg")
})
