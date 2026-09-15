import { test } from "node:test"
import assert from "node:assert/strict"
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"

/** The UI once used 21 font sizes, a dozen of them one-off `text-[Npx]` values down to
 *  8px. The scale now lives in globals.css (text-2xs … text-4xl). This keeps it there. */
const ROOTS = ["app", "components"]

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sources(path)
    return path.endsWith(".tsx") || path.endsWith(".ts") ? [path] : []
  })
}

test("no arbitrary font sizes outside the type scale", () => {
  const offenders = ROOTS.flatMap(sources).flatMap((file) =>
    // px and rem only: an em size (inline code at 0.9em) follows its paragraph rather than
    // adding a step to the scale.
    [...readFileSync(file, "utf8").matchAll(/\btext-\[\d[\d.]*(px|rem)\]/g)].map((m) => `${file}: ${m[0]}`),
  )
  assert.deepEqual(offenders, [], "use a scale size (text-2xs, text-xs, text-sm, …) instead")
})
