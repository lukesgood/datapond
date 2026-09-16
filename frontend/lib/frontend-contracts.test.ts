/** Properties of the frontend that used to be pinned from backend tests.
 *
 *  backend/tests/test_ml_integrations.py and test_operational_flows.py read these
 *  files with read_text() and grepped them. Every assertion below is about frontend
 *  source only, so a frontend refactor could turn backend CI red for a reason that had
 *  nothing to do with the backend — which happened on 2026-09-15. They live here now,
 *  next to the code they describe, in the directory-walking style of
 *  lib/permission-source.test.ts.
 */
import assert from "node:assert/strict"
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs"
import { test } from "node:test"
import path from "node:path"
import { fileURLToPath } from "node:url"

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..")

function walk(dir: string, exts = [".tsx", ".ts"]): string[] {
  if (!existsSync(dir)) return []
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...walk(full, exts))
    else if (exts.some((e) => entry.endsWith(e))) out.push(full)
  }
  return out
}

/** Prose above a line routinely names the very pattern a test forbids, so comments are
 *  stripped before matching — the same reason lib/permission-source.test.ts does it. */
function source(...targets: string[]): string {
  const files = targets.flatMap((t) => {
    const full = path.join(ROOT, t)
    return statSync(full).isDirectory() ? walk(full) : [full]
  })
  assert.ok(files.length > 0, `no files found for ${targets.join(", ")}`)
  return files
    .map((f) => readFileSync(f, "utf8"))
    .join("\n")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "")
}

// ── MLflow route handlers ─────────────────────────────────────────────────────

test("every MLflow route handler goes through the shared authenticated proxy", () => {
  const routes = walk(path.join(ROOT, "app/api/mlflow"), [".ts"]).filter((f) => f.endsWith("route.ts"))
  assert.ok(routes.length > 0, "no MLflow route handlers found")
  for (const file of routes) {
    const text = readFileSync(file, "utf8")
    assert.match(text, /proxyMlflow/, file)
    // A handler that re-wraps the upstream body loses its status and headers.
    assert.doesNotMatch(text, /NextResponse\.json\(data\)/, file)
  }
  const helper = readFileSync(path.join(ROOT, "app/api/mlflow/_proxy.ts"), "utf8")
  for (const needle of [
    'request.headers.get("authorization")',
    'headers.set("authorization", authorization)',
    "status: upstream.status",
    '"content-type"',
    "new Response(upstream.body",
  ]) {
    assert.ok(helper.includes(needle), `_proxy.ts is missing ${needle}`)
  }
})

test("notebook screens never call Jupyter directly or carry a token", () => {
  const text = source("app/notebooks", "components/notebooks", "components/query/open-in-notebook-modal.tsx")
  for (const forbidden of ["/jupyter/api", "/api/contents", "token=jupyter", "?token="]) {
    assert.ok(!text.includes(forbidden), `a notebook screen reaches Jupyter directly: ${forbidden}`)
  }
})

test("experiment screens read the proxy's payload, not a nested envelope", () => {
  const text = source("app/experiments", "components/mlflow", "components/query/log-to-mlflow-modal.tsx")
  for (const nested of [
    ".registered_models", "data.experiments", "data.runs",
    "expData.experiment", "runData.run", "runsData.runs",
  ]) {
    assert.ok(!text.includes(nested), `an experiment screen unwraps a nested envelope: ${nested}`)
  }
})

// ── Service detail gating and the sidebar's sign-out ──────────────────────────

test("service detail decides admin-only controls from the permissions API", () => {
  const page = readFileSync(path.join(ROOT, "app/services/[id]/page.tsx"), "utf8")
  const viewer = readFileSync(path.join(ROOT, "components/services/logs-viewer.tsx"), "utf8")
  for (const needle of [
    'from "@/lib/permissions"',
    "const { role } = usePermissions()",
    'const isAdmin = role === "admin"',
    "{isAdmin && !isManaged && (",
    "onDeletePod={isAdmin ? handleDeletePod : undefined}",
    "canStream={isAdmin}",
    "if (!isAdmin) return",
  ]) {
    assert.ok(page.includes(needle), `services detail page is missing ${needle}`)
  }
  // The role in the JWT cannot express a service account key's narrowed scopes.
  assert.ok(!page.includes("getUser()?.role"), "services detail page branches on the token's role")
  for (const needle of ["canStream?: boolean", "{canStream && (", "onToggleStream(!isStreaming)", "downloadLogs"]) {
    assert.ok(viewer.includes(needle), `logs viewer is missing ${needle}`)
  }
})

test("sign out is reachable and visible by keyboard", () => {
  const sidebar = readFileSync(path.join(ROOT, "components/app-sidebar.tsx"), "utf8")
  for (const needle of [
    "group-focus-within:opacity-100",
    "focus-visible:opacity-100",
    "focus-visible:ring-2",
    "focus-visible:ring-ring",
    'aria-label="Sign out"',
  ]) {
    assert.ok(sidebar.includes(needle), `sidebar sign-out is missing ${needle}`)
  }
})
