/** Source type definitions and the saved-settings view (./connectors.ts). */
import assert from "node:assert/strict"
import { test } from "node:test"
import { availableConnectors, configRows, deleteImpactMessage, getConnector, previewRows, readsEverythingEachSync, S3_REGIONS } from "./connectors.ts"

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

test("the delete confirmation says what goes, what stays and what is built on it", () => {
  const msg = deleteImpactMessage({
    lake_tables: ["iceberg.default.orders", "iceberg.default.items"], catalog: "src_shop", scheduled: true,
    impact_checked: 2, built_on: { metrics: ["Revenue"], concepts: ["주문"], dashboards: [], queries: 3 },
    breaks: { metrics: ["Live orders"], concepts: [], dashboards: ["Ops"], queries: 0 },
  })
  assert.match(msg, /Stops working, because it reads src_shop directly: metrics Live orders; dashboards Ops\./)
  assert.match(msg, /connection settings, sync jobs, sync history and schedule\. This can't be undone\./)
  assert.match(msg, /query catalog src_shop goes too/)
  assert.match(msg, /The 2 lake tables it loaded stay, but stop updating: default\.orders, default\.items\./)
  assert.match(msg, /Built on those tables: metrics Revenue; concepts 주문; 3 queries in the last 30 days\./)

  const quiet = deleteImpactMessage({ lake_tables: ["iceberg.default.a"], catalog: null, scheduled: false,
    impact_checked: 1, built_on: { metrics: [], concepts: [], dashboards: [], queries: 0 } })
  assert.match(quiet, /sync jobs and sync history\./)
  assert.doesNotMatch(quiet, /catalog/)
  assert.match(quiet, /Nothing you can see is built on those tables\./)

  assert.match(deleteImpactMessage(null), /Tables it already loaded into the lake stay\./)
  assert.match(deleteImpactMessage({ lake_tables: [], catalog: null, scheduled: false, impact_checked: 0,
    built_on: { metrics: [], concepts: [], dashboards: [], queries: 0 } }), /has not loaded any lake tables/)
})

test("the setup preview hides the columns about to be masked", () => {
  const p = previewRows([{ id: 1, Email: "a@x", tags: ["t"] }, { id: 2, phone: null }], "email, phone")
  assert.deepEqual(p.headers, ["id", "Email", "tags", "phone"])
  assert.deepEqual(p.rows, [["1", "masked", '["t"]', "masked"], ["2", "masked", "", "masked"]])
  assert.deepEqual([...p.masked], ["Email", "phone"])
  assert.deepEqual(previewRows([], "").headers, [])
})
