import test from "node:test"
import assert from "node:assert/strict"
import { GOVERNANCE, INTEGRATE, INTEGRATE_AUDIT, INTEGRATE_CALL, INTEGRATE_SCOPES, KNOWLEDGE, METRICS, OPERATE_PAGE } from "./help-ai-ops.ts"
import { OPERATE_PROFILES, OPERATE_TOPICS } from "./help-operate.ts"

// Every { en, ko } in the content has both languages and the same inline code spans.
function walk(v: unknown, path: string, out: string[]) {
  if (Array.isArray(v)) return v.forEach((x, i) => walk(x, `${path}[${i}]`, out))
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>
    if (typeof o.en === "string" && typeof o.ko === "string") {
      if (!o.en.trim() || !o.ko.trim()) out.push(`${path}: empty`)
      const spans = (s: string) => (s.match(/`[^`]+`/g) ?? []).join("|")
      if (spans(o.en) !== spans(o.ko)) out.push(`${path}: code spans differ`)
      return
    }
    for (const [k, x] of Object.entries(o)) walk(x, `${path}.${k}`, out)
  }
}

test("AI and operations guides are fully bilingual", () => {
  const out: string[] = []
  walk({ KNOWLEDGE, GOVERNANCE, METRICS, INTEGRATE, INTEGRATE_AUDIT, INTEGRATE_CALL, INTEGRATE_SCOPES, OPERATE_PAGE, OPERATE_PROFILES, OPERATE_TOPICS }, "content", out)
  assert.deepEqual(out, [])
})
