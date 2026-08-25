/** Parser assertions, run by `npm test` (node:test — no test framework added).
 *
 *  The frontend has no test runner, which is how a renderer that dropped every
 *  construct except **bold** stayed that way: `tsc` and `eslint` both pass on a
 *  parser that is simply wrong. Splitting parsing out of rendering is what makes
 *  this checkable at all.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { parseBlocks, parseInline } from "./markdown.ts"

test("bold becomes emphasis rather than asterisks", () => {
  assert.deepEqual(parseInline("a **b** c"),
    [{ t: "text", v: "a " }, { t: "bold", v: "b" }, { t: "text", v: " c" }])
})

test("asterisks inside code stay literal", () => {
  assert.deepEqual(parseInline("`a **b**`"), [{ t: "code", v: "a **b**" }])
})

test("a lone asterisk in an identifier is not emphasis", () => {
  // Models write field*name and snake_case constantly. Italicising on either would
  // mangle far more text than it formats.
  assert.deepEqual(parseInline("field*name and a_b"),
    [{ t: "text", v: "field*name and a_b" }])
})

test("citations are chips only where an answer asked for them", () => {
  assert.deepEqual(parseInline("see [1]"),
    [{ t: "text", v: "see " }, { t: "text", v: "[1]" }])
  assert.deepEqual(parseInline("see [1]", true),
    [{ t: "text", v: "see " }, { t: "cite", v: "1" }])
})

test("bullets and numbers become lists", () => {
  assert.equal(parseBlocks("- one\n- two")[0].t, "ul")
  assert.equal(parseBlocks("1. one\n2. two")[0].t, "ol")
})

test("switching marker starts a new list rather than mixing two meanings", () => {
  assert.deepEqual(parseBlocks("- a\n1. b").map(b => b.t), ["ul", "ol"])
})

test("headings and fenced code are their own blocks", () => {
  assert.deepEqual(parseBlocks("## Title")[0], { t: "h", level: 2, spans: [{ t: "text", v: "Title" }] })
  assert.deepEqual(parseBlocks("```\nx=1\n```"), [{ t: "pre", v: "x=1" }])
})

test("a blank line separates paragraphs and a newline does not", () => {
  assert.deepEqual(parseBlocks("a\n\nb").map(b => b.t), ["p", "p"])
  assert.deepEqual(parseBlocks("a\nb"), [{ t: "p", spans: [{ t: "text", v: "a b" }] }])
})

test("a list ends where prose resumes", () => {
  assert.deepEqual(parseBlocks("- a\nprose").map(b => b.t), ["ul", "p"])
})

test("empty and plain input survive", () => {
  assert.deepEqual(parseBlocks(""), [])
  assert.deepEqual(parseBlocks("hello"), [{ t: "p", spans: [{ t: "text", v: "hello" }] }])
})
