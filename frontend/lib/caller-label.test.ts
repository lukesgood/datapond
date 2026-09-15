import { test } from "node:test"
import assert from "node:assert/strict"
import { callerLabel } from "./caller-label.ts"

const ID = "c67dae27-cc01-4932-a669-d552c7783ced"

test("a known account shows its name, with the id on hover", () => {
  assert.deepEqual(callerLabel("svc-bot", ID), { text: "svc-bot", title: ID })
})

test("an unknown UUID is shortened but kept whole in the title", () => {
  assert.deepEqual(callerLabel(null, ID), { text: "c67dae27…", title: ID })
})

test("a non-UUID id and a missing id are shown as they are", () => {
  assert.deepEqual(callerLabel(undefined, "ops@example.com"), { text: "ops@example.com" })
  assert.deepEqual(callerLabel(null, null), { text: "—" })
})
