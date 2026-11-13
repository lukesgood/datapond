import { test } from "node:test"
import assert from "node:assert/strict"
import { evidenceResult, maskedColumns, parsePiiEvidence, type EvidenceTable } from "./pii-evidence.ts"

const base: EvidenceTable = {
  table: "iceberg.default.customers", source: "Shop", source_table: "customers", last_run_at: null,
  status: "ok", raw_columns: [],
  columns: [
    { column: "email", masked_at_sync: true, sampled: 200, raw_found: 0, types: [] },
    { column: "phone", masked_at_sync: false, sampled: 200, raw_found: 3, types: ["phone_kr"] },
    { column: "name", masked_at_sync: false, sampled: 200, raw_found: 0, types: [] },
  ],
}

test("ok, raw_found and unverified read as the sketch says", () => {
  assert.deepEqual(evidenceResult(base), { tone: "good", text: "No raw values in sample ✓" })
  assert.deepEqual(evidenceResult({ ...base, status: "raw_found", raw_columns: ["phone"] }),
    { tone: "warn", text: "Raw values in: phone (phone_kr) ⚠" })
  assert.deepEqual(evidenceResult({ ...base, status: "unverified", columns: [], error: "timeout" }),
    { tone: "muted", text: "Not verified: timeout" })
  assert.equal(evidenceResult({ ...base, status: "unverified" }).text, "Not verified")
})

test("masked columns are the ones masked at sync", () => {
  assert.deepEqual(maskedColumns(base), ["email"])
})

test("parse rejects a body without a summary", () => {
  assert.equal(parsePiiEvidence({}), null)
  assert.equal(parsePiiEvidence({ summary: { tables: 0, ok: 0, raw_found: 0, unverified: 0 }, tables: [] })?.tables.length, 0)
})
