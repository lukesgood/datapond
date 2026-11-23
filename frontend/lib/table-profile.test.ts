import assert from "node:assert/strict"
import { test } from "node:test"
import { distinctLabel, keyBadges, nullPct, snapshotLabel } from "./table-profile.ts"

test("null fraction reads as a percentage", () => {
  assert.equal(nullPct(null), "—")
  assert.equal(nullPct(0), "0%")
  assert.equal(nullPct(0.0004), "<0.1%")
  assert.equal(nullPct(0.034), "3.4%")
  assert.equal(nullPct(0.999), "99.9%")
  assert.equal(nullPct(1), "100%")
  assert.equal(nullPct(0.5), "50%")
  assert.equal(distinctLabel(1199.6), "≈ 1,200")
  assert.equal(distinctLabel(undefined), "—")
})

test("key badges per column", () => {
  const b = keyBadges({
    primary: ["id"],
    foreign: [{ column: "Customer_ID", ref_table: "iceberg.default.customers", ref_column: "id", via: "lake" }],
    referenced_by: [],
  })
  assert.deepEqual(b.id.map(x => x.label), ["PK"])
  assert.equal(b.customer_id[0].label, "FK → customers.id")
  assert.match(b.customer_id[0].title, /synced from/)
  assert.deepEqual(keyBadges(null), {})
})

test("snapshot label", () => {
  assert.equal(snapshotLabel({ at: "", operation: "append", added_records: 1200, total_records: 5 }), "+1,200 rows")
  assert.equal(snapshotLabel({ at: "", operation: "overwrite", added_records: 3, total_records: 3 }), "overwrite")
})
