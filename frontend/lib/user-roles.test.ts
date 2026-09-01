/** Presentation logic for Settings → Users → role picker, run by `npm test` (node:test).
 *
 *  See lib/user-roles.ts for what this covers and why it holds no role descriptions
 *  of its own.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import * as UserRoles from "./user-roles.ts"
import { roleOptions } from "./user-roles.ts"

const SERVER_ROLES = [
  {
    name: "viewer",
    label: "Read-only access: browse the catalog and knowledge, and run read-only queries.",
    permissions: ["catalog:read", "knowledge:read", "query:run"],
  },
  {
    name: "data_scientist",
    label: "Queries, builds collections, spends on models, and can check when a source last synced.",
    permissions: [
      "catalog:read", "knowledge:read", "query:run", "knowledge:write",
      "ai:generate", "dashboard:write", "connector:read", "workbench:read", "workbench:write",
    ],
  },
  {
    name: "admin",
    label: "Full access to every module, every collection, and account management.",
    permissions: ["catalog:read", "user:manage"],
  },
]

test("one option per assignable role, in the order the server sent them", () => {
  const options = roleOptions(SERVER_ROLES)
  assert.deepStrictEqual(options.map(o => o.value), ["viewer", "data_scientist", "admin"])
})

test("each option carries a one-line description an admin can act on without guessing", () => {
  const options = roleOptions(SERVER_ROLES)
  for (const option of options) {
    assert.ok(option.description.length > 0, `${option.value} has no description`)
    assert.ok(!option.description.includes("\n"), `${option.value} description is not one line`)
  }
  // The two roles the brief calls out by name as easy to confuse must not read the same.
  const dataScientist = options.find(o => o.value === "data_scientist")!
  const admin = options.find(o => o.value === "admin")!
  assert.notStrictEqual(dataScientist.description, admin.description)
})

test("a role the server sent with no label still renders, under its bare name", () => {
  const options = roleOptions([{ name: "contractor", permissions: [] }])
  assert.strictEqual(options.length, 1)
  assert.strictEqual(options[0].value, "contractor")
  assert.strictEqual(options[0].label, "contractor")
  assert.ok(options[0].description.includes("contractor"))
})

test("roleOptions preserves the server's order even when it doesn't sort alphabetically", () => {
  const reordered = [SERVER_ROLES[2], SERVER_ROLES[0], SERVER_ROLES[1]]
  const options = roleOptions(reordered)
  assert.deepStrictEqual(options.map(o => o.value), ["admin", "viewer", "data_scientist"])
})

test("nextRoleAfterToggle does not exist — a seven-role product has no meaningful toggle", () => {
  assert.strictEqual(
    "nextRoleAfterToggle" in UserRoles,
    false,
    "an admin/viewer toggle makes no sense once a person can hold any of seven roles",
  )
})
