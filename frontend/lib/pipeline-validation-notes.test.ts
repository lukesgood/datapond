/** pipelineValidationNotice (./pipeline-validation-notes.ts), run by `npm test` (node:test).
 *
 *  `POST /api/pipelines/validate` returns `warnings` alongside `success`. The compiler
 *  no longer executes the submitted pipeline source — it reads it — so those warnings
 *  are where it says what it could not use: a decorator the DSL does not define (the
 *  `@quality(table=...)` the builder itself emits), a module-level statement that was
 *  never run, an argument it would have had to execute the file to learn. The console
 *  used to declare the field and render none of it, which is the failure this guards:
 *  a pipeline that looks validated while part of it was ignored.
 *
 *  The rule these tests pin is that the count on the pill is the count in the list.
 *  A pill saying "3 notes" over a panel listing two is a worse lie than showing nothing.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { pipelineValidationNotice } from "./pipeline-validation-notes.ts"

test("no warnings field at all is a clean validation", () => {
  const notice = pipelineValidationNotice(undefined)
  assert.equal(notice.hasNotes, false)
  assert.equal(notice.label, "Validated")
  assert.deepEqual(notice.notes, [])
})

test("an empty warnings array is a clean validation, not an empty panel", () => {
  assert.equal(pipelineValidationNotice([]).hasNotes, false)
})

test("one warning reads as one note, singular", () => {
  const notice = pipelineValidationNotice(["'@quality' is not a DataPond pipeline decorator"])
  assert.equal(notice.hasNotes, true)
  assert.equal(notice.label, "Validated · 1 note")
  assert.deepEqual(notice.notes, ["'@quality' is not a DataPond pipeline decorator"])
})

test("more than one warning is plural", () => {
  assert.equal(pipelineValidationNotice(["a", "b"]).label, "Validated · 2 notes")
  assert.equal(pipelineValidationNotice(["a", "b", "c"]).label, "Validated · 3 notes")
})

test("the heading counts the same notes the label does", () => {
  const notice = pipelineValidationNotice(["a", "b"])
  assert.equal(notice.heading, "Validation notes (2)")
  assert.equal(notice.notes.length, 2)
})

test("a blank warning is dropped rather than rendered as an empty bullet", () => {
  const notice = pipelineValidationNotice(["a", "   ", ""])
  assert.deepEqual(notice.notes, ["a"])
  assert.equal(notice.label, "Validated · 1 note")
})

test("warnings that are all blank leave a clean validation", () => {
  assert.equal(pipelineValidationNotice(["", "  "]).hasNotes, false)
})

test("the count on the pill is always the number of notes listed", () => {
  for (const warnings of [[], ["a"], ["a", ""], ["a", "b", "c"], undefined]) {
    const notice = pipelineValidationNotice(warnings)
    assert.equal(notice.hasNotes, notice.notes.length > 0)
    if (notice.hasNotes) {
      assert.ok(notice.label.includes(String(notice.notes.length)))
      assert.ok(notice.heading.includes(String(notice.notes.length)))
    }
  }
})

test("each note keeps the API's own words, untruncated and unreworded", () => {
  const fromApi =
    "2 module-level statement(s) were read but not executed. A pipeline definition " +
    "is parsed, never run, so anything those statements would have computed is not " +
    "part of this pipeline."
  assert.deepEqual(pipelineValidationNotice([fromApi]).notes, [fromApi])
})

test("surrounding whitespace is trimmed so the list lines up", () => {
  assert.deepEqual(pipelineValidationNotice(["  padded  "]).notes, ["padded"])
})
