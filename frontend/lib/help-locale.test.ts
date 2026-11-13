import test from "node:test"
import assert from "node:assert/strict"
import { pick, initialLocale, parseLocale, type L } from "./help-locale.ts"

const text: L = { en: "Sources", ko: "소스" }

test("pick returns the text for the locale, English when Korean is missing", () => {
  assert.equal(pick(text, "ko"), "소스")
  assert.equal(pick(text, "en"), "Sources")
  assert.equal(pick({ en: "Only English" } as L, "ko"), "Only English")
  assert.equal(pick("plain", "ko"), "plain", "a plain string is the same in both")
})

test("the first visit follows the browser; a saved choice wins", () => {
  assert.equal(initialLocale(null, ["ko-KR", "en"]), "ko")
  assert.equal(initialLocale(null, ["en-US"]), "en")
  assert.equal(initialLocale(null, []), "en")
  assert.equal(initialLocale("en", ["ko-KR"]), "en")
  assert.equal(initialLocale("ko", ["en-US"]), "ko")
})

test("anything but en/ko is not a saved choice", () => {
  assert.equal(parseLocale("ko"), "ko")
  assert.equal(parseLocale("fr"), null)
  assert.equal(parseLocale(null), null)
})
