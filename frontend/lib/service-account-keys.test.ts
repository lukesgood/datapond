import assert from "node:assert/strict"
import { test } from "node:test"
import {
  DEFAULT_EXPIRY_DAYS, EXPIRY_OPTIONS, choosableScopes, defaultScopes, describeKey,
  keyRequestBody,
} from "./service-account-keys.ts"

test("choosable scopes are the intersection, sorted", () => {
  assert.deepEqual(
    choosableScopes(["ai:generate", "knowledge:read", "query:run", "audit:read"],
                    ["knowledge:read", "query:run", "ai:generate", "catalog:read"]),
    ["ai:generate", "knowledge:read", "query:run"],
  )
})

test("default scopes are knowledge:read + ai:generate when available", () => {
  assert.deepEqual(defaultScopes(["ai:generate", "knowledge:read", "query:run"]),
                   ["knowledge:read", "ai:generate"])
  assert.deepEqual(defaultScopes(["query:run"]), ["query:run"])
})

test("expiry defaults to 90 days and the body omits it for no-expiry", () => {
  assert.equal(DEFAULT_EXPIRY_DAYS, 90)
  assert.ok(EXPIRY_OPTIONS.some(o => o.days === 90))
  assert.deepEqual(keyRequestBody("bot key", ["ai:generate"], 90),
                   { name: "bot key", scopes: ["ai:generate"], expires_in_days: 90 })
  assert.deepEqual(keyRequestBody("bot key", [], null), { name: "bot key", scopes: [] })
})

test("describeKey names scopes and expiry, or says so when absent", () => {
  assert.equal(describeKey({ scopes: ["knowledge:read", "ai:generate"], expires_at: "2026-12-06T00:00:00Z" }),
               "knowledge:read, ai:generate · expires 2026-12-06")
  assert.equal(describeKey({ scopes: [], expires_at: null }), "all role permissions · no expiry")
})
