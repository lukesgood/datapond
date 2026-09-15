import assert from "node:assert/strict"
import { test } from "node:test"

import { buildToolCallSection, windowParams } from "./compliance-report.ts"

test("windowParams turns date inputs into tz-aware ISO bounds", () => {
  const p = windowParams("2026-09-01", "2026-09-07")
  assert.equal(p.get("since"), new Date("2026-09-01T00:00:00").toISOString())
  assert.equal(p.get("until"), new Date("2026-09-07T23:59:59").toISOString())
  assert.equal(windowParams("", "").has("since"), false)
})

test("buildToolCallSection carries totals, capped flag and per-actor rows", () => {
  const s = buildToolCallSection(
    { rows: [{ tool: "ai.rag", outcome: "ok" }], total: 300, capped: true },
    { by_actor: [{ actor_username: "svc-bot", actor_kind: "service", calls: 3, refused: 1,
                   ok: 3, degraded: 0, error: 0, collections: ["faq"], tables: [],
                   hits: 9, pii_masked: 2 }] },
  )
  assert.equal(s.total_available, 300)
  assert.equal(s.returned, 1)
  assert.equal(s.capped, true)
  assert.equal(s.by_actor[0].actor_username, "svc-bot")
  assert.equal(s.by_actor[0].collections[0], "faq")
})

test("a refusal count rides along when the deployment sends one", () => {
  const withRefusals = buildToolCallSection(
    { rows: [], total: 0, capped: false },
    { by_actor: [{ actor_username: "svc-bot", actor_kind: "service", calls: 2, ok: 1, degraded: 0, error: 0, refused: 1, collections: [], tables: [] }] },
  )
  assert.equal(withRefusals.by_actor[0].refused, 1)

  const withoutRefusals = buildToolCallSection(
    { rows: [], total: 0, capped: false },
    { by_actor: [{ actor_username: "old", actor_kind: "service", calls: 1, ok: 1, degraded: 0, error: 0, collections: [], tables: [] }] },
  )
  assert.equal(withoutRefusals.by_actor[0].refused, undefined)
})
