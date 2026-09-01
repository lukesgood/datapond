/** What the pipeline builder should say about a validation that succeeded with notes.
 *
 *  `POST /api/pipelines/validate` no longer executes the pipeline source it is sent —
 *  it reads it with `ast` (backend/app/pipelines/ast_reader.py). Reading a definition
 *  rather than running it means there are things the validator can see but cannot use:
 *  a decorator the DSL does not define, a module-level statement it did not run, an
 *  argument whose value would only exist if the file had been executed. It reports
 *  each of those in `warnings`, and the page dropped them — declaring the field and
 *  rendering none of it. A pipeline then looked cleanly validated while part of what
 *  the author wrote had been ignored, which is exactly the silence this replaces.
 *
 *  The rule worth stating on its own, away from the JSX: the number on the pill is the
 *  number of notes in the list. Nothing is counted that is not shown.
 */

export interface PipelineValidationNotice {
  /** Whether there is anything to show at all. False means a plain "Validated". */
  hasNotes: boolean
  /** The pill's text, pluralized against the notes actually listed. */
  label: string
  /** The panel's heading, counting those same notes. */
  heading: string
  /** The notes, in the API's own words — trimmed, never truncated or reworded. */
  notes: string[]
}

/** Read a successful validation's `warnings` into what the builder should display. */
export function pipelineValidationNotice(
  warnings: readonly string[] | null | undefined,
): PipelineValidationNotice {
  // A blank warning would render as a bullet with nothing beside it and still be
  // counted, so it is dropped here rather than shown — the count has to mean the list.
  const notes = (warnings ?? []).map((w) => w.trim()).filter(Boolean)

  if (notes.length === 0) {
    return { hasNotes: false, label: "Validated", heading: "", notes: [] }
  }

  return {
    hasNotes: true,
    label: `Validated · ${notes.length} ${notes.length === 1 ? "note" : "notes"}`,
    heading: `Validation notes (${notes.length})`,
    notes,
  }
}
