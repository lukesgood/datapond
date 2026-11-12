import test from "node:test"
import assert from "node:assert/strict"
import { latestRowsByTable } from "./sync-table-rows.ts"

// Sessions arrive newest first, like the connection page's history.
const sessions = [
  { tables: [{ table: "public.api_events", rows: 9000 }] },
  { tables: [{ table: "public.customers", rows: 1200 }] },
  { tables: [{ table: "public.customers", rows: 1100 }, { table: "public.orders", rows: 6000 }] },
]

test("each table shows the rows of the newest session that synced it", () => {
  // Live 2026-11-12: a single-table sync of api_events made every other table read "—".
  const rows = latestRowsByTable(sessions)
  assert.equal(rows.get("public.api_events"), 9000)
  assert.equal(rows.get("public.customers"), 1200)
  assert.equal(rows.get("public.orders"), 6000)
})

test("a failed table without a row count does not hide an older count", () => {
  const rows = latestRowsByTable([
    { tables: [{ table: "public.orders" }] },
    { tables: [{ table: "public.orders", rows: 6000 }] },
  ])
  assert.equal(rows.get("public.orders"), 6000)
})

test("no history means no counts", () => {
  assert.equal(latestRowsByTable([]).size, 0)
  assert.equal(latestRowsByTable([{}]).size, 0)
})
