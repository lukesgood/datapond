import assert from "node:assert/strict"
import { test } from "node:test"
import { feedbackPayload, reportPage } from "./feedback.ts"

test("the page is sent without its query string", () => {
  assert.equal(reportPage("/query?sql=SELECT%201#x"), "/query")
  assert.equal(reportPage(""), "/")
})

test("a report needs a title within limits", () => {
  assert.equal(feedbackPayload("bug", "   ", "", "/", null, "ua"), null)
  assert.equal(feedbackPayload("bug", "x".repeat(201), "", "/", null, "ua"), null)
  const p = feedbackPayload("feature", " Dark mode ", " please ", "/catalog?q=1", "2.7.0", "Mozilla")
  assert.deepEqual(p, { kind: "feature", title: "Dark mode", body: "please", page: "/catalog",
                        app_version: "2.7.0", user_agent: "Mozilla" })
})
