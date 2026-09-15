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

test("status colour comes from the tokens, not the raw palette", () => {
  // Success was green in 21 files, emerald in 14, and --dp-good in 21; warning was
  // yellow, amber, and --dp-warn. One meaning, one token: --dp-good, --dp-warn, destructive.
  const offenders = ROOTS.flatMap(sources).flatMap((file) =>
    [...readFileSync(file, "utf8").matchAll(/(?<![\w-])(?:[a-z0-9-]+:)*(?:text|bg|from|to|via|border|ring|divide|outline|fill|stroke)-(?:green|emerald|yellow|amber|orange|red|rose)-\d{2,3}\b/g)]
      .map((m) => `${file}: ${m[0]}`),
  )
  assert.deepEqual(offenders, [], "use text-[var(--dp-good)], text-[var(--dp-warn)], or text-destructive")
})

test("status colour as text uses the text tones", () => {
  // --dp-good and --dp-warn are fill tones: as text they measured 3.1:1 and 2.4:1.
  const offenders = ROOTS.flatMap(sources).flatMap((file) =>
    [...readFileSync(file, "utf8").matchAll(/(?<![\w-])(?:[a-z0-9-]+:)*text-\[var\(--dp-(?:good|warn)\)\]/g)].map((m) => `${file}: ${m[0]}`),
  )
  assert.deepEqual(offenders, [], "use text-[var(--dp-good-text)] or text-[var(--dp-warn-text)]")
})
