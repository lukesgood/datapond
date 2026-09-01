/** The one place the pipeline builders write a quality check into generated Python.
 *
 *  Both builders used to emit this:
 *
 *      @quality(table="bronze_orders")
 *      def check_bronze_orders(): return "amount > 0"
 *
 *  There is no `quality(...)` call form in the DSL and never was.
 *  `backend/app/pipelines/decorators.py` defines `quality` as a namespace whose members
 *  are `quality.expect(name, condition)`, `quality.expect_or_drop(...)` and
 *  `quality.expect_or_fail(...)`, and they attach to the table by decorating **the same
 *  function** `@live_table` decorates, below it — decorators apply bottom-up, so the
 *  check is pending on the function by the time `live_table` reads it. A separate
 *  `check_*` function attaches to nothing even if the decorator existed.
 *
 *  So every quality check anyone configured in the console was dropped. It used to be
 *  loud — importing the module raised `TypeError: quality() takes no arguments` and
 *  validation failed — and since the compiler started parsing instead of importing, it
 *  is quiet: validation succeeds with a note that an unrecognized decorator was
 *  ignored, and the compiled pipeline has no checks.
 *
 *  `expect_or_fail`, not `expect`, because the field's own help text says "halts on
 *  failure": `QualityAction.FAIL`. The other two actions log or drop rows, which is a
 *  different promise from the one the console makes.
 *
 *  The exact string this produces is pinned on the backend side by
 *  `backend/tests/test_pipeline_quality_checks.py`, which runs it through the real
 *  compiler and asserts the check reaches the table definition. The two tests meet at
 *  that literal; change one and the other fails.
 */

/** Python double-quoted string body: backslashes first, then quotes. */
function pythonLiteral(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')
}

/** The name the check carries into validation output and the generated DAG. */
export function qualityCheckName(tableName: string): string {
  return `${tableName}_quality`
}

/** The decorator line for a table's quality condition, or null when there is none.
 *
 *  Returns one line, to be emitted directly under the table's `@live_table(...)` and
 *  directly above its `def`. Anything else — a blank line between, another function —
 *  breaks the attachment.
 */
export function qualityDecorator(tableName: string, condition: string): string | null {
  const trimmed = (condition ?? "").trim()
  if (!trimmed) return null
  return `@quality.expect_or_fail("${pythonLiteral(qualityCheckName(tableName))}", "${pythonLiteral(trimmed)}")`
}
