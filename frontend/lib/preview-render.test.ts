import assert from "node:assert/strict"
import { test } from "node:test"

import { genericPreviewEntries, humanizeKey, formatPreviewValue } from "./preview-render.ts"

test("a key with no dedicated rendering becomes a label", () => {
  assert.equal(humanizeKey("new_sync_mode"), "New sync mode")
  assert.equal(humanizeKey("policy_id"), "Policy id")
  assert.equal(humanizeKey("table"), "Table")
})

test("primitive values format plainly", () => {
  assert.equal(formatPreviewValue("titan-v2"), "titan-v2")
  assert.equal(formatPreviewValue(42), "42")
  assert.equal(formatPreviewValue(true), "yes")
  assert.equal(formatPreviewValue(false), "no")
})

test("null, undefined and empty string all render as an explicit placeholder, not blank", () => {
  assert.equal(formatPreviewValue(null), "—")
  assert.equal(formatPreviewValue(undefined), "—")
  assert.equal(formatPreviewValue(""), "—")
})

test("an array joins its formatted values", () => {
  assert.equal(formatPreviewValue(["analyst", "viewer"]), "analyst, viewer")
  assert.equal(formatPreviewValue([]), "—")
})

test("a nested object stays legible instead of printing as [object Object]", () => {
  assert.equal(
    formatPreviewValue({ interval_minutes: 30, source_table: "crm.customers" }),
    "Interval minutes: 30; Source table: crm.customers",
  )
})

test("keys with dedicated rendering elsewhere are excluded from the generic list", () => {
  const preview = {
    reads: ["crm.customers"], validated: true, name: "handbook", sql: "select 1",
    summary: "Delete the row filter.", target: "rls-7", dependents: { items: [] },
    named_by_user: true,
    // the fields no caller has a special case for:
    key: "ai.litellm_url", value: "https://new-gateway",
  }
  const entries = genericPreviewEntries(preview)
  const keys = entries.map(e => e.key)
  assert.deepEqual(keys, ["key", "value"])
})

test("every one of the six new previews' own fields survives as a readable entry", () => {
  // settings.set_model_config — Critical 3's other half: the approver types the key
  // and must still be shown the value.
  const settingsPreview = { key: "ai.litellm_url", value: "https://new-gateway",
                            summary: "Set ai.litellm_url to 'https://new-gateway'." }
  assert.deepEqual(genericPreviewEntries(settingsPreview),
    [{ key: "key", label: "Key", value: "ai.litellm_url" },
     { key: "value", label: "Value", value: "https://new-gateway" }])

  // knowledge.set_refresh_schedule
  const schedulePreview = { collection: "handbook", currently_enabled: false,
                            current_interval_minutes: null, new_interval_minutes: 30,
                            schedule_preset: "hourly", will_be_enabled: true }
  const scheduleEntries = genericPreviewEntries(schedulePreview)
  assert.equal(scheduleEntries.length, 6)
  assert.deepEqual(scheduleEntries.find(e => e.key === "current_interval_minutes"),
    { key: "current_interval_minutes", label: "Current interval minutes", value: "—" })
  assert.deepEqual(scheduleEntries.find(e => e.key === "will_be_enabled"),
    { key: "will_be_enabled", label: "Will be enabled", value: "yes" })

  // knowledge.add_member / remove_member
  const memberPreview = { collection: "handbook", username: "ada", new_role: "editor",
                          current_role: "reader" }
  assert.equal(genericPreviewEntries(memberPreview).length, 4)

  // connectors.set_schedule
  const connSchedulePreview = { connection_id: "c1", connection_name: "CRM export",
                                current_schedule: "0 1 * * *", new_schedule: null,
                                disabling: true }
  assert.equal(genericPreviewEntries(connSchedulePreview).length, 5)

  // connectors.set_sync_mode
  const syncModePreview = { connection_id: "c1", connection_name: "CRM export",
                            table: "all tables", new_sync_mode: "full" }
  assert.equal(genericPreviewEntries(syncModePreview).length, 4)

  // governance.delete_rls_policy / delete_masking_policy preview content, the other
  // half of Critical 3's destructive-card gap
  const deletePolicyPreview = { policy_id: "rls-7", table: "crm.customers",
                                roles: ["analyst"], enabled: true,
                                summary: "Delete the row filter on crm.customers." }
  const deleteEntries = genericPreviewEntries(deletePolicyPreview)
  assert.deepEqual(deleteEntries.map(e => e.key), ["policy_id", "table", "roles", "enabled"])
  assert.deepEqual(deleteEntries.find(e => e.key === "roles"),
    { key: "roles", label: "Roles", value: "analyst" })
})

test("a caller's own extra-excluded keys are left out too", () => {
  const preview = { collection: "handbook", username: "ada" }
  assert.deepEqual(genericPreviewEntries(preview, ["collection"]),
    [{ key: "username", label: "Username", value: "ada" }])
})

test("an empty or missing preview yields no entries", () => {
  assert.deepEqual(genericPreviewEntries(null), [])
  assert.deepEqual(genericPreviewEntries(undefined), [])
  assert.deepEqual(genericPreviewEntries({}), [])
})
