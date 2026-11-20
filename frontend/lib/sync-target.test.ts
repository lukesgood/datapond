import { test } from "node:test"
import assert from "node:assert/strict"
import { alsoSyncedLine, hasDataLine, targetRefusal } from "./sync-target.ts"

test("a 409 target_has_data becomes the move-or-leave choice", () => {
  const r = targetRefusal(409, { code: "target_has_data", table: "default.customers", from: "iceberg", to: "polaris_lake", rows: 1200, last_run_at: "2026-11-13T02:09:16Z" })
  assert.deepEqual(r, { kind: "has_data", table: "default.customers", from: "iceberg", to: "polaris_lake", rows: 1200, lastRunAt: "2026-11-13T02:09:16Z" })
  assert.equal(hasDataLine(r as never), "1,200 rows, last synced Nov 13.")
})

test("a duplicate is a message; anything else is not a refusal", () => {
  assert.deepEqual(targetRefusal(409, { code: "duplicate_target", message: "x lands in y" }), { kind: "duplicate", message: "x lands in y" })
  assert.equal(targetRefusal(409, "plain"), null)
  assert.equal(targetRefusal(400, { code: "target_has_data", from: "a", to: "b" }), null)
})

test("also synced line lists enabled jobs only", () => {
  assert.equal(alsoSyncedLine([{ source_table: "public.customers", catalog: "polaris_lake", enabled: true, last_run_at: null }]),
    "also synced as public.customers → polaris_lake")
  assert.equal(alsoSyncedLine([{ source_table: "public.customers", catalog: "polaris_lake", enabled: false, last_run_at: null }]), null)
  assert.equal(alsoSyncedLine(undefined), null)
})
