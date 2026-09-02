/** The assistant panel's open state, which two components now read.
 *
 *  It used to live inside the panel component, where only that component could see it.
 *  The open control moved to the top bar, so the trigger and the panel are separate
 *  components reading the same fact — and a second copy of "is it open" is a panel that
 *  disagrees with its own button.
 */
import assert from "node:assert/strict"
import { afterEach, beforeEach, test } from "node:test"

import {
  readPanelOpen, serverPanelOpen, subscribeToPanelState, togglePanel,
} from "./assistant-panel-state.ts"

const KEY = "datapond_assistant_open"

function fakeStorage(initial: Record<string, string> = {}, throwOnAccess = false) {
  const store = { ...initial }
  return {
    getItem(key: string) {
      if (throwOnAccess) throw new Error("site data blocked")
      return key in store ? store[key] : null
    },
    setItem(key: string, value: string) {
      if (throwOnAccess) throw new Error("site data blocked")
      store[key] = value
    },
    _store: store,
  }
}

let saved: unknown

beforeEach(() => { saved = (globalThis as Record<string, unknown>).localStorage })
afterEach(() => { (globalThis as Record<string, unknown>).localStorage = saved })

function install(storage: unknown) {
  ;(globalThis as Record<string, unknown>).localStorage = storage
}

test("a first visit is closed — nothing stored means no panel", () => {
  install(fakeStorage())
  assert.equal(readPanelOpen(), false)
})

test("only an explicit open counts as open", () => {
  install(fakeStorage({ [KEY]: "1" }))
  assert.equal(readPanelOpen(), true)

  for (const stored of ["0", "", "true", "yes"]) {
    install(fakeStorage({ [KEY]: stored }))
    assert.equal(readPanelOpen(), false, `"${stored}" should not read as open`)
  }
})

test("toggling flips what the next read returns", () => {
  const storage = fakeStorage()
  install(storage)

  togglePanel()
  assert.equal(readPanelOpen(), true)
  togglePanel()
  assert.equal(readPanelOpen(), false)
})

test("a toggle tells every subscriber, so the bar and the panel move together", () => {
  install(fakeStorage())
  const seen: string[] = []
  const stopA = subscribeToPanelState(() => seen.push("trigger"))
  const stopB = subscribeToPanelState(() => seen.push("panel"))

  togglePanel()
  assert.deepEqual(seen, ["trigger", "panel"])

  stopA()
  togglePanel()
  assert.deepEqual(seen, ["trigger", "panel", "panel"], "unsubscribe did not take effect")
  stopB()
})

test("a browser with site data blocked reads closed instead of throwing", () => {
  // The panel is a convenience. Failing to read where it was last must not take the
  // page down with it.
  install(fakeStorage({}, true))
  assert.equal(readPanelOpen(), false)
  assert.doesNotThrow(() => togglePanel())
})

test("the server always renders closed, because it cannot know", () => {
  assert.equal(serverPanelOpen(), false)
})
