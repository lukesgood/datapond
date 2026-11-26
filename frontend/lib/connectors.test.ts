/** Source type definitions and the saved-settings view (./connectors.ts). */
import assert from "node:assert/strict"
import { test } from "node:test"
import { availableConnectors, configRows, getConnector, readsEverythingEachSync, S3_REGIONS } from "./connectors.ts"

test("S3 offers Seoul and starts there; the secret shows only once an access key is typed", () => {
  const s3 = getConnector("s3")!
  const region = s3.fields.find(f => f.name === "region")!
  assert.equal(region.default, "ap-northeast-2")
  assert.deepEqual(region.options, S3_REGIONS)
  const secret = s3.fields.find(f => f.name === "secret_key")!
  assert.equal(secret.showIf!({}), false)
  assert.equal(secret.showIf!({ access_key: "AKIA" }), true)
})

test("a REST source names its table instead of landing in `root`", () => {
  assert.ok(getConnector("rest_api")!.fields.some(f => f.name === "table_name"))
})

test("only the Trino databases fetch changed rows; files, REST and Python read everything", () => {
  assert.deepEqual(availableConnectors.filter(c => readsEverythingEachSync(c.id)).map(c => c.id).sort(), ["custom", "rest_api", "s3"])
  for (const c of availableConnectors.filter(c => readsEverythingEachSync(c.id))) {
    assert.ok(!c.features?.some(f => /incremental/i.test(f)), `${c.id} still claims incremental sync`)
  }
})

test("saved settings read by the form's labels; secrets, switches and code read as words", () => {
  const rows = configRows("rest_api", {
    base_url: "https://api.x/v1", auth_type: "bearer", auth_value: "••••••••", auth_header: "Authorization",
    data_path: "", legacy_flag: "x",
  })
  assert.deepEqual(rows.map(r => [r.label, r.value]), [
    ["Base URL", "https://api.x/v1"], ["Authentication", "bearer"], ["Credential", "Stored encrypted"],
    ["Records path", "—"], ["Legacy flag", "x"],
  ])
  assert.deepEqual(configRows("redshift", { ssl: false }).map(r => r.value), ["Off"])
  assert.deepEqual(configRows("custom", { code: "def fetch_data():\n    return []" }).map(r => r.value), ["2 lines"])
})
