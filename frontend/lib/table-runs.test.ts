/** Per-table run state on a source page (./table-runs.ts). */
import assert from "node:assert/strict"
import { test } from "node:test"
import { runLabel, runStates } from "./table-runs.ts"

test("a table left behind by the last sync is called out (the live customers case)", () => {
  const s = runStates([
    { name: "public.orders", enabled: true, last_run_at: "2026-11-20T03:19:00", last_run_status: "success" },
    { name: "public.customers", enabled: true, last_run_at: "2026-11-13T02:09:00", last_run_status: "success" },
    { name: "public.agents", enabled: true, last_run_at: "2026-11-19T22:00:00", last_run_status: "failed" },
    { name: "public.new", enabled: true, last_run_at: null },
    { name: "public.off", enabled: false, last_run_at: "2026-09-29T08:00:00" },
  ])
  assert.deepEqual(s, { "public.orders": "ok", "public.customers": "behind", "public.agents": "failed",
                        "public.new": "never", "public.off": "off" })
  assert.equal(runLabel("behind", "2026-11-13T02:09:00Z").endsWith("not refreshed by the last sync"), true)
  assert.equal(runLabel("never"), "not run yet")
})
