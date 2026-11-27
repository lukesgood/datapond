import { test } from "node:test"
import assert from "node:assert/strict"
import { ageLabel, diagnosisActions, groupIssues, headline, issueView, parseOpsStatus, staleSummary, statusFacts, type Diagnosis, type OpsIssue } from "./ops-status.ts"

const diag = (action: string): Diagnosis => ({ code: "x", action, title: "T", detail: "D", advice: "A" })
const writer = new Set(["connector:write", "connector:read"])
const reader = new Set(["connector:read"])

test("recreate and retry need connector:write", () => {
  assert.deepEqual(diagnosisActions("c1", "public.t", diag("recreate"), writer),
    [{ type: "recreate", label: "Recreate target table", connectionId: "c1", table: "public.t" }])
  assert.deepEqual(diagnosisActions("c1", "public.t", diag("recreate"), reader), [])
  assert.equal(diagnosisActions("c1", "t", diag("retry"), writer)[0].type, "sync")
  assert.deepEqual(diagnosisActions("c1", "t", diag("retry"), reader), [])
})

test("credential, network, grant and target problems link to the connection", () => {
  for (const a of ["edit_connection", "check_connection", "grant_source", "change_target"]) {
    const acts = diagnosisActions("c 1", "t", diag(a), reader)
    assert.equal(acts.length, 1)
    const first = acts[0]
    assert.equal(first.type === "link" && first.href, "/connectors/connections/c%201")
  }
  assert.deepEqual(diagnosisActions("c1", "t", null, writer), [])
  assert.deepEqual(diagnosisActions("c1", "t", diag("unknown"), writer), [])
})

test("a failed sync shows the diagnosis title and advice", () => {
  const issue: OpsIssue = { kind: "sync_failed", connection_id: "c1", source: "Shop", table: "public.api_events", diagnosis: diag("recreate") }
  const v = issueView(issue, writer)
  assert.match(v.title, /Shop · public.api_events: T/)
  assert.equal(v.advice, "A")
  assert.equal(v.actions[0].type, "recreate")
  assert.equal(issueView(issue, reader).actions.length, 0)
})

test("an undiagnosed failure still links to the connection with the raw error", () => {
  const v = issueView({ kind: "sync_failed", connection_id: "c1", source: "S", table: "t", error: "boom", diagnosis: null }, reader)
  assert.equal(v.detail, "boom")
  assert.equal(v.actions[0].type, "link")
})

test("stale source offers Sync now only to writers", () => {
  const issue: OpsIssue = { kind: "stale_source", connection_id: "c1", source: "S", hours: 30 }
  assert.deepEqual(issueView(issue, writer).actions.map((a) => a.label), ["Sync now", "Open connection"])
  assert.deepEqual(issueView(issue, reader).actions.map((a) => a.label), ["Open connection"])
})

test("catalog_unreachable points admins to Data catalogs and others to Catalog", () => {
  const issue: OpsIssue = { kind: "catalog_unreachable", catalog: "polaris_lake" }
  const admin = issueView(issue, new Set(["settings:write"])).actions[0]
  const other = issueView(issue, reader).actions[0]
  assert.equal(admin.type === "link" && admin.href, "/settings?tab=catalogs")
  assert.equal(other.type === "link" && other.href, "/catalog")
})

test("engine restarting is information without buttons", () => {
  const v = issueView({ kind: "engine_restarting" }, writer)
  assert.equal(v.tone, "info")
  assert.equal(v.actions.length, 0)
})

test("headline and facts", () => {
  const ok = { state: "ok" as const, queries_24h: 312, issues: [], checked_at: "t",
    syncs: { window_hours: 24, tables_ok: 14, tables_failed: 0 } }
  assert.equal(headline(ok).label, "Healthy")
  assert.deepEqual(statusFacts(ok), ["14 tables synced ok (24h)", "312 queries today"])
  const bad = { ...ok, state: "attention" as const, issues: [{ kind: "engine_restarting" as const }, { kind: "engine_restarting" as const }] }
  assert.equal(headline(bad).label, "2 to check")
  assert.deepEqual(statusFacts({ ...bad, syncs: { window_hours: 24, tables_ok: 1, tables_failed: 2 }, queries_24h: null }),
    ["1 table synced ok · 2 failed (24h)"])
})

test("parse rejects junk", () => {
  assert.equal(parseOpsStatus(null), null)
  assert.equal(parseOpsStatus({ state: "weird" }), null)
  assert.deepEqual(parseOpsStatus({ state: "ok", issues: [1, { kind: "engine_restarting" }] })?.issues, [{ kind: "engine_restarting" }])
})

// ── dashboard checklist: grouped, compact ───────────────────────────────────────

const stale = (id: string, hours: number | null): OpsIssue =>
  ({ kind: "stale_source", connection_id: id, source: `Source ${id}`, hours })

test("stale sources become one group, other issues stay single and come first", () => {
  const failed: OpsIssue = { kind: "sync_failed", connection_id: "c9", source: "Shop", table: "orders" }
  const groups = groupIssues([stale("a", 68), failed, stale("b", 142), { kind: "engine_restarting" }])
  assert.deepEqual(groups.map((g) => g.kind), ["single", "single", "stale"])
  const g = groups[2]
  assert.equal(g.kind, "stale")
  if (g.kind === "stale") {
    // longest-stale first: the most overdue is what to look at
    assert.deepEqual(g.items.map((i) => i.connection_id), ["b", "a"])
  }
})

test("a lone stale source still groups, and never-synced sorts first", () => {
  const groups = groupIssues([stale("a", 5), stale("n", null)])
  assert.equal(groups.length, 1)
  if (groups[0].kind === "stale") assert.deepEqual(groups[0].items.map((i) => i.connection_id), ["n", "a"])
  assert.deepEqual(groupIssues([]), [])
})

test("ages read as hours under two days, then days", () => {
  assert.equal(ageLabel(null), "never synced")
  assert.equal(ageLabel(1), "1 hour ago")
  assert.equal(ageLabel(47), "47 hours ago")
  assert.equal(ageLabel(68), "3 days ago")
  assert.equal(ageLabel(142), "6 days ago")
})

test("one query is singular", () => {
  const s = { state: "ok" as const, queries_24h: 1, issues: [], checked_at: "2026-11-16T00:00:00Z" }
  assert.deepEqual(statusFacts(s), ["1 query today"])
})

// ── Overview shows only what needs action; staleness is one line ──────────────

test("a missed scheduled run counts in the headline like any other issue", () => {
  const base = { state: "attention" as const, queries_24h: null, checked_at: "t" }
  assert.deepEqual(headline({ ...base, issues: [stale("a", 50), stale("b", 90)] }), { label: "2 to check", tone: "warn" })
  assert.deepEqual(headline({ ...base, issues: [] }), { label: "Healthy", tone: "good" })
})

test("the stale line names how many and says where to look", () => {
  assert.equal(staleSummary([stale("a", 50)]), "1 source missed a scheduled sync")
  assert.equal(staleSummary([stale("a", 50), stale("b", null)]), "2 sources missed a scheduled sync")
  assert.equal(staleSummary([]), null)
})

test("paused sources are not an Overview fact (they live on Sources)", () => {
  const s = { state: "ok" as const, queries_24h: null, issues: [], checked_at: "x",
              syncs: { window_hours: 24, tables_ok: 3, tables_failed: 0, paused_sources: 5 } }
  assert.deepEqual(statusFacts(s), ["3 tables synced ok (24h)"])
})

test("a source table synced by two jobs explains the drift and links the connection", () => {
  const v = issueView({ kind: "duplicate_sync", connection_id: "c1", source: "Sample E-Commerce DB", table: "default.customers",
    jobs: [{ source_table: "customers", catalog: "iceberg", last_run_at: null },
           { source_table: "public.customers", catalog: "polaris_lake", last_run_at: null }] }, new Set())
  assert.equal(v.title, "Sample E-Commerce DB · default.customers is synced by 2 jobs")
  assert.match(v.detail, /drift apart.*iceberg \(customers\) and polaris_lake \(public\.customers\)/)
  assert.deepEqual(v.actions, [{ type: "link", label: "Open connection", href: "/connectors/connections/c1" }])
  const same = issueView({ kind: "duplicate_sync", connection_id: "c1", source: "S", table: "default.t",
    jobs: [{ source_table: "t", catalog: "iceberg", last_run_at: null }, { source_table: "public.t", catalog: "iceberg", last_run_at: null }] }, new Set())
  assert.match(same.detail, /overwrite each other/)
})

test("a scheduled run that never synced says whether it was skipped or errored", () => {
  const skipped = issueView({ kind: "schedule_failed", connection_id: "c1", source: "Shop", reason: "skipped",
    detail: "whoever set this schedule is no longer an active user" }, reader)
  assert.equal(skipped.title, "Shop: scheduled sync did not run")
  assert.equal(skipped.detail, "Skipped: whoever set this schedule is no longer an active user.")
  assert.match(skipped.advice ?? "", /save its schedule again/)
  const error = issueView({ kind: "schedule_failed", connection_id: "c1", source: "Shop", reason: "error", detail: "Sync failed: timeout" }, reader)
  assert.equal(error.title, "Shop: scheduled sync failed")
  assert.equal(error.detail, "Sync failed: timeout")
  assert.deepEqual(error.actions, [{ type: "link", label: "Open connection", href: "/connectors/connections/c1" }])
})
