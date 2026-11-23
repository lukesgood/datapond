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
const LEAN = { sourcesEnabled: false, catalogEnabled: false, queryEnabled: false, catalogBackend: "collections" }
const FULL = { sourcesEnabled: true, catalogEnabled: true, queryEnabled: true, catalogBackend: "glue" }
const navUrls = new Map([...NAV_SECTIONS.flatMap((s) => s.items), ...BOTTOM_ITEMS].map((i) => [i.url, i.title]))
// The menu item a page sits under: its own entry, or the entry whose path it extends
// (a guide at /help/integrate is under Help).
const menuOf = (href: string) =>
  navUrls.get(href) ?? [...navUrls].find(([url]) => href.startsWith(`${url}/`))?.[1]

test("the strip has five steps in both shapes", () => {
  assert.equal(coreWorkflowSteps(LEAN).length, 5)
  assert.equal(coreWorkflowSteps(FULL).length, 5)
})

test("every step leads somewhere the menu has", () => {
  for (const inputs of [LEAN, FULL]) {
    const missing = coreWorkflowSteps(inputs).filter((s) => !menuOf(s.href))
    assert.deepEqual(missing, [], "a step links to a page with no menu item")
  }
})

test("no menu item takes a name a workflow step already uses", () => {
  const stepTitles = new Set(coreWorkflowSteps(FULL).map((s) => s.title.toLowerCase()))
  const clashes = [...navUrls.values()].filter((t) => stepTitles.has(t.toLowerCase()))
  assert.deepEqual(clashes, [], "menu items reuse a workflow step's name")
})

test("the steps that do not branch point at the expected page", () => {
  const byTitle = new Map(coreWorkflowSteps(LEAN).map((s) => [s.title, s.href]))
  assert.equal(menuOf(byTitle.get("Ground")!), "Knowledge")
  // The integration guide, not a menu page of its own: what this step needs is how to
  // connect (MCP, the gateway document, the REST surface), which is documentation,
  // and the one action in it — issuing a key — lives on the Agents page.
  assert.equal(byTitle.get("Connect your agent"), "/help/integrate")
  assert.equal(menuOf(byTitle.get("Connect your agent")!), "Help")
  assert.equal(menuOf(byTitle.get("Govern")!), "Governance")
})

test("the two branching steps follow the adapters a deployment runs", () => {
  const lean = new Map(coreWorkflowSteps(LEAN).map((s) => [s.n, s.href]))
  const full = new Map(coreWorkflowSteps(FULL).map((s) => [s.n, s.href]))
  assert.equal(lean.get("01"), "/knowledge")
  assert.equal(full.get("01"), "/connectors")
  assert.equal(lean.get("02"), "/knowledge")
  assert.equal(full.get("02"), "/catalog")
})


test("with a query engine the strip is the lakehouse path, AI last", () => {
  // The product is a lightweight lakehouse first (docs/PRODUCT_CONCEPT.md v7): land
  // data, catalog it, query it, govern it — then put AI on it.
  const steps = coreWorkflowSteps(FULL)
  assert.deepEqual(steps.map((s) => s.title), ["Connect", "Organize", "Query", "Govern", "Add AI"])
  assert.deepEqual(steps.map((s) => s.href), ["/connectors", "/catalog", "/query", "/governance", "/knowledge"])
})

test("without a query engine the strip stays the knowledge path", () => {
  assert.deepEqual(coreWorkflowSteps(LEAN).map((s) => s.title),
    ["Connect", "Organize", "Ground", "Connect your agent", "Govern"])
})

test("every step names its icon kind", () => {
  for (const inputs of [LEAN, FULL]) {
    for (const s of coreWorkflowSteps(inputs)) assert.ok(s.kind, `${s.title} has no kind`)
  }
})

test("the menu follows the data's path: Data, Semantic, Use, Operate", () => {
  assert.deepEqual(NAV_SECTIONS.map((s) => s.label), ["Data", "Semantic", "Use", "Operate"])
  const titles = (label: string) => NAV_SECTIONS.find((s) => s.label === label)!.items.map((i) => i.title)
  assert.deepEqual(titles("Data"), ["Sources", "Transforms", "Streaming", "Catalog"])
  assert.deepEqual(titles("Semantic"), ["Semantic model"])
  assert.deepEqual(titles("Use"), ["Analytics", "Knowledge", "Notebooks", "Experiments", "Agents"])
  assert.deepEqual(titles("Operate"), ["Governance", "AI Gateway", "Storage", "Infrastructure", "Settings"])
})

test("each role sees its own stretch of the path", () => {
  // Permission sets as in backend app/permissions.py; capabilities all on.
  const visible = (perms: string[]) => NAV_SECTIONS.flatMap((s) => s.items)
    .filter((i) => !i.permission || perms.includes(i.permission)).map((i) => i.title)
  const read = ["catalog:read", "knowledge:read"]
  assert.deepEqual(visible([...read, "query:run"]), ["Catalog", "Semantic model", "Analytics", "Knowledge"])
  assert.deepEqual(visible([...read, "governance:read", "spend:read"]),
    ["Catalog", "Semantic model", "Knowledge", "Governance", "AI Gateway"])
})

test("the Organize sub-label counts catalogs when there are several", () => {
  const sub = (n?: number) => coreWorkflowSteps({ ...FULL, lakeCatalogCount: n }).find((s) => s.n === "02")!.sub
  assert.equal(sub(), "glue catalog")
  assert.equal(sub(1), "glue catalog")
  assert.equal(sub(2), "2 catalogs")
})
