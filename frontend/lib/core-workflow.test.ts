import { test } from "node:test"
import assert from "node:assert/strict"
import { coreWorkflowSteps } from "./core-workflow.ts"
import { BOTTOM_ITEMS, NAV_SECTIONS } from "./nav-items.ts"

/** The dashboard's workflow and the menu have to agree. When they drift, the first
 *  thing a new user does is follow a step to a page the menu files somewhere else, or
 *  under a different name.
 *
 *  This check used to live in backend/tests/test_dashboard_workflow_matches_nav.py,
 *  which read both lists out of the TSX with regexes — so a frontend refactor broke
 *  backend CI (it did, on 2026-09-15, when per-step colours were removed and the
 *  parser's anchor disappeared). Both lists are data now, and the check runs where
 *  they live. */
const LEAN = { sourcesEnabled: false, catalogEnabled: false, catalogBackend: "collections" }
const FULL = { sourcesEnabled: true, catalogEnabled: true, catalogBackend: "glue" }
const navUrls = new Map([...NAV_SECTIONS.flatMap((s) => s.items), ...BOTTOM_ITEMS].map((i) => [i.url, i.title]))

test("the strip has five steps in both shapes", () => {
  assert.equal(coreWorkflowSteps(LEAN).length, 5)
  assert.equal(coreWorkflowSteps(FULL).length, 5)
})

test("every step leads somewhere the menu has", () => {
  for (const inputs of [LEAN, FULL]) {
    const missing = coreWorkflowSteps(inputs).filter((s) => !navUrls.has(s.href))
    assert.deepEqual(missing, [], "a step links to a page with no menu item")
  }
})

test("no menu item takes a name a workflow step already uses", () => {
  const stepTitles = new Set(coreWorkflowSteps(FULL).map((s) => s.title.toLowerCase()))
  const clashes = [...navUrls.values()].filter((t) => stepTitles.has(t.toLowerCase()))
  assert.deepEqual(clashes, [], "menu items reuse a workflow step's name")
})

test("the steps that do not branch point at the expected page", () => {
  const byTitle = new Map(coreWorkflowSteps(FULL).map((s) => [s.title, s.href]))
  assert.equal(navUrls.get(byTitle.get("Ground")!), "Knowledge")
  assert.equal(navUrls.get(byTitle.get("Connect your agent")!), "API")
  assert.equal(navUrls.get(byTitle.get("Govern")!), "Governance")
})

test("the two branching steps follow the adapters a deployment runs", () => {
  const lean = new Map(coreWorkflowSteps(LEAN).map((s) => [s.n, s.href]))
  const full = new Map(coreWorkflowSteps(FULL).map((s) => [s.n, s.href]))
  assert.equal(lean.get("01"), "/knowledge")
  assert.equal(full.get("01"), "/connectors")
  assert.equal(lean.get("02"), "/knowledge")
  assert.equal(full.get("02"), "/catalog")
})
