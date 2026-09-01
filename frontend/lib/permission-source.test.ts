/** Every page under app/ must read what the caller may do from GET /api/me/permissions
 *  (usePermissions()/useHasPermission(), lib/permissions.tsx), never from the role
 *  baked into the JWT sitting in localStorage (getUser().role, lib/auth.ts). That
 *  token is a value the browser owns, it carries a role and no permissions, and it
 *  cannot express a service account key's narrowed scopes — the API already enforces
 *  from /api/me/permissions, so a console that decides differently just disagrees
 *  with itself.
 *
 *  This is the frontend analogue of backend/tests/test_route_authorization_inventory.py:
 *  it walks app/ itself rather than naming the eight pages that had this bug, so a
 *  ninth page that reaches for the token fails here instead of quietly joining them.
 *
 *  What counts as the defect is narrower than "uses getUser() at all" — getUser()
 *  legitimately stays the identity source (id, username) — and narrower than "shows
 *  `.role` at all" — app/account/page.tsx displays the caller's own role as plain
 *  text, which is not a decision about what to allow. The defect is specifically a
 *  *branch* on it: a `.role` read off getUser() (directly, or one hop through a
 *  variable assigned straight from it) compared with `===`/`!==` to decide what
 *  renders.
 */
import assert from "node:assert/strict"
import { readFileSync, readdirSync, statSync } from "node:fs"
import { test } from "node:test"
import path from "node:path"
import { fileURLToPath } from "node:url"

const APP_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "app")

function walk(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry)
    const info = statSync(full)
    if (info.isDirectory()) out.push(...walk(full))
    else if (entry.endsWith(".tsx") || entry.endsWith(".ts")) out.push(full)
  }
  return out
}

/** Strip line and block comments before matching — the house style in this repo is
 *  to explain a fix in prose right above the line it fixes ("this used to gate on
 *  getUser()'s admin role"), and that prose routinely names the exact pattern this
 *  test exists to catch. Scanning comments as if they were code would make the
 *  detector flag the sentence that explains the fix, not just an unfixed page —
 *  a false positive this file's own comments hit while it was under construction.
 *  Good enough for this codebase's actual syntax; it does not need to be a full
 *  tokenizer.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "")
}

/** True if `source` decides something by comparing a getUser()-derived `.role` with
 *  `===`/`!==` — either the direct chain (`getUser()?.role === "admin"`) or one hop
 *  through a variable bound straight from `getUser()` (`const me = getUser()` ...
 *  `me?.role === "admin"`). A bare read with no comparison — `{user?.role}` in JSX
 *  text, or passing it straight to a `<Badge>` — is display, not a branch, and is
 *  left alone; see the "own role, displayed rather than decided" test below for why
 *  that distinction has to exist for this test to be usable at all.
 */
export function branchesOnGetUserRole(source: string): boolean {
  const code = stripComments(source)
  if (!/getUser\s*\(\s*\)/.test(code)) return false

  const boundVars = new Set<string>()
  const bindRe = /\b(?:const|let|var)\s+(\w+)\s*=\s*getUser\(\)/g
  for (let m = bindRe.exec(code); m; m = bindRe.exec(code)) boundVars.add(m[1])

  const bases = ["getUser\\(\\)", ...boundVars].join("|")
  const branchRe = new RegExp(`(?:${bases})\\??\\.role\\s*(?:===|!==)`)
  return branchRe.test(code)
}

test("no page under app/ branches on getUser().role for what the caller may do", () => {
  const offenders = walk(APP_DIR)
    .filter(f => branchesOnGetUserRole(readFileSync(f, "utf8")))
    .map(f => path.relative(APP_DIR, f))
    .sort()
  assert.deepEqual(
    offenders,
    [],
    `these page(s) decide access from the role in the localStorage token instead of ` +
    `GET /api/me/permissions (usePermissions()/useHasPermission()):\n  ${offenders.join("\n  ")}`,
  )
})

test("the detector actually catches a branch — a broken regex finding nothing would pass silently", () => {
  assert.equal(branchesOnGetUserRole('const [isAdmin] = useState(() => getUser()?.role === "admin")'), true)
  assert.equal(
    branchesOnGetUserRole('const me = getUser()\nif (me?.role === "admin") { doAdminThing() }'),
    true,
  )
  assert.equal(branchesOnGetUserRole('const currentUser = getUser()\nconst isAdmin = currentUser?.role === "admin"'), true)
})

test("someone else's role — a row in a user-management table, not the caller's own — is not a match", () => {
  // Settings' user list compares u.role, where u is a row from GET /api/auth/users,
  // never getUser(). That comparison is legitimate (an admin deciding what to show
  // for someone else) and must not trip this detector.
  assert.equal(
    branchesOnGetUserRole('const isAdmin = users.some(u => u.role === "admin")'),
    false,
  )
})

test("the caller's own role, displayed rather than decided, is not a branch", () => {
  assert.equal(
    branchesOnGetUserRole('const [user] = useState(() => getUser())\nreturn <span>{user?.role}</span>'),
    false,
  )
})

test("a comment describing the fix, in the exact words the fix removed, is not a branch", () => {
  // The actual shape this hit during development: a docstring above the corrected
  // line explaining what it used to do. If comments counted, fixing a page would
  // require never mentioning the bug it fixed — worse than not writing the test.
  assert.equal(
    branchesOnGetUserRole(
      '// This used to check getUser()?.role === "admin" instead of usePermissions().\n' +
      'const isAdmin = role === "admin"',
    ),
    false,
  )
})
