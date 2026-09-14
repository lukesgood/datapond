/** The signed-in user, as read by components that render it (./auth.ts).
 *
 *  The sidebar used to read it with a lazy useState initialiser. The server has no
 *  localStorage, so it rendered no user block and the browser hydrated one in — React
 *  reports that as error #418, on every page the sidebar appears on. These tests pin the
 *  three things useSyncExternalStore needs from a store: an answer for the server, a
 *  client snapshot that stays the same object while nothing changed, and a notification
 *  when the answer does change.
 */
import assert from "node:assert/strict"
import { afterEach, beforeEach, test } from "node:test"

import { clearAuth, readUser, saveAuth, serverUser, subscribeToUser, type AuthUser } from "./auth.ts"

const USER_KEY = "datapond_user"

const ALICE: AuthUser = {
  id: "u1", username: "alice", display_name: "Alice", email: "alice@example.com", role: "admin",
}

function fakeStorage(initial: Record<string, string> = {}, throwOnAccess = false) {
  const store: Record<string, string> = { ...initial }
  const guard = () => { if (throwOnAccess) throw new Error("site data blocked") }
  return {
    getItem(key: string) { guard(); return key in store ? store[key] : null },
    setItem(key: string, value: string) { guard(); store[key] = value },
    removeItem(key: string) { guard(); delete store[key] },
    _store: store,
  }
}

const g = globalThis as Record<string, unknown>
let savedStorage: unknown
let savedDocument: unknown

beforeEach(() => {
  savedStorage = g.localStorage
  savedDocument = g.document
  // saveAuth/clearAuth also write the cookie the Next middleware checks.
  g.document = { cookie: "" }
})
afterEach(() => {
  g.localStorage = savedStorage
  g.document = savedDocument
})

function install(storage: unknown) {
  g.localStorage = storage
}

test("the server renders signed out, because it cannot know who is signed in", () => {
  assert.equal(serverUser(), null)
})

test("nothing stored reads as signed out", () => {
  install(fakeStorage())
  assert.equal(readUser(), null)
})

test("a stored user reads back", () => {
  install(fakeStorage({ [USER_KEY]: JSON.stringify(ALICE) }))
  assert.deepEqual(readUser(), ALICE)
})

test("an unchanged stored value returns the same object — useSyncExternalStore compares by identity", () => {
  // A fresh JSON.parse per call would hand React a new snapshot on every render, which
  // it reads as a change and re-renders without end.
  install(fakeStorage({ [USER_KEY]: JSON.stringify(ALICE) }))
  const first = readUser()
  assert.ok(first)
  assert.equal(readUser(), first)
})

test("a changed stored value returns a new answer", () => {
  const storage = fakeStorage({ [USER_KEY]: JSON.stringify(ALICE) })
  install(storage)
  const before = readUser()
  storage._store[USER_KEY] = JSON.stringify({ ...ALICE, display_name: "Alice B" })
  const after = readUser()
  assert.notEqual(after, before)
  assert.equal(after?.display_name, "Alice B")
})

test("a malformed stored value reads as signed out instead of throwing", () => {
  install(fakeStorage({ [USER_KEY]: "{not json" }))
  assert.equal(readUser(), null)
})

test("a browser with site data blocked reads as signed out instead of throwing", () => {
  install(fakeStorage({}, true))
  assert.equal(readUser(), null)
})

test("signing in and out tells subscribers in this tab", () => {
  // A `storage` event never fires in the tab that made the change, so without a direct
  // notification the sidebar would keep showing the previous user in that tab.
  install(fakeStorage())
  let calls = 0
  const stop = subscribeToUser(() => { calls++ })

  saveAuth("tok", ALICE)
  assert.equal(calls, 1)
  assert.deepEqual(readUser(), ALICE)

  clearAuth()
  assert.equal(calls, 2)
  assert.equal(readUser(), null)

  stop()
  saveAuth("tok", ALICE)
  assert.equal(calls, 2, "unsubscribe did not take effect")
})
