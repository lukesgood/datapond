/** Presentation logic for the support tier a capability carries, run by `npm test`
 *  (node:test). See capability-support.ts for the module docstring.
 */
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { supportBadge, supportTier } from "./capability-support.ts"

test("a capability the backend marks experimental returns that tier", () => {
  assert.equal(supportTier("streaming", { streaming: "experimental" }), "experimental")
})

test("a capability absent from the support map is supported — returns null", () => {
  assert.equal(supportTier("knowledge", { streaming: "experimental" }), null)
  assert.equal(supportTier("streaming", {}), null)
})

test("a tier this build does not know is not rendered as unlabelled text — returns null", () => {
  // A newer backend may one day send a third tier. Until this module knows the
  // word for it, showing the raw string would put unreviewed text in the UI.
  assert.equal(supportTier("streaming", { streaming: "beta" }), null)
})

test("supportBadge('preview') names the refusal", () => {
  const badge = supportBadge("preview")
  assert.equal(badge.label, "Preview")
  assert.match(badge.title, /refus/i)
})

test("supportBadge('experimental') says the wiring is supported and the upstream project is not", () => {
  const badge = supportBadge("experimental")
  assert.equal(badge.label, "Experimental")
  assert.match(badge.title, /wiring is supported/i)
  assert.match(badge.title, /project itself is not|not.*support/i)
})

// ── Repo-wide scan: the five surfaces where a tiered capability meets a person ──
//
// Same shape as lib/permission-source.test.ts's own repo-wide rule: name the exact
// files a plan requires, then read them back rather than trusting that an edit
// landed. Governance's Lineage tab is deliberately NOT in this list — it does not
// exist, and neither does the capability any more: `lineage` was retired from
// /api/capabilities once it turned out to gate nothing a person could open. The only
// "Lineage" UI in the app is a card on app/knowledge/page.tsx over a different,
// ungated endpoint (/api/ai/lineage, connector→table→collection lineage) that works
// on the Portable Core, with or without OpenMetadata.
{
  const FRONTEND_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..")

  test("the sidebar and the four pages with a support tier import supportBadge", () => {
    const files = [
      "components/app-sidebar.tsx",
      "app/streaming/page.tsx",
      "app/notebooks/page.tsx",
      "app/experiments/page.tsx",
      "app/pipelines/page.tsx",
    ]
    const missing = files.filter(
      (f) => !readFileSync(path.join(FRONTEND_ROOT, f), "utf8").includes("supportBadge"),
    )
    assert.deepEqual(
      missing,
      [],
      `these file(s) should render a support-tier badge but do not import supportBadge:\n  ${missing.join("\n  ")}`,
    )
  })
}

test("a capability with no tier renders nothing — the eleven untouched capabilities all resolve to null, even alongside a full support map", () => {
  // This is the point of the whole feature: absence must stay absence. A capability
  // that carries no tier today (the Portable Core, plus query/dashboards/catalog/
  // connectors, which have a supported AWS backend) must render exactly as it did
  // before this change — no badge, no line, no layout shift — regardless of what
  // other capabilities the same payload carries a tier for.
  const support = {
    pipelines: "preview",
    streaming: "experimental",
    notebooks: "experimental",
    experiments: "experimental",
  }
  const untouched = [
    "knowledge", "ai", "settings", "governance", "storage", "services", "system",
    "dashboard", "dashboards", "connectors", "catalog", "query",
  ]
  for (const capability of untouched) {
    assert.equal(supportTier(capability, support), null, `${capability} unexpectedly carries a tier`)
  }
})
