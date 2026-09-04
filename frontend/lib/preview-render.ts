/** Turning an action preview into something legible, without a special case per key.
 *
 *  Every `preview_*` executor on the backend returns whatever shape its own action
 *  needs — a collection name here, a typed key/value there, roles and an expression
 *  for a policy. `PreviewBody` and `DestructiveCard` used to hard-code a fixed list
 *  of keys (`reads`, `validated`, `already_exists`, `cost_estimate_available`,
 *  `name`, `sql`) and render nothing at all for anything outside it — which was
 *  every key the six newer actions in this branch actually emit. A reversible
 *  action's card showed its label and nothing else; a destructive action's card
 *  never showed the value being written, only the key the person had to type.
 *
 *  `genericPreviewEntries` is the fallback for exactly that case: it turns every
 *  preview field a caller has not special-cased into a readable label/value pair,
 *  so the next action added needs no matching frontend change to be shown honestly.
 */

/** Keys that already have dedicated rendering elsewhere and so must not also appear
 *  in the generic fallback list — either because a caller renders them specially
 *  (`reads`, `validated`/`error`, `already_exists`, `cost_estimate_available`,
 *  `name`, `sql`, `summary`), or because they describe the destructive gate itself
 *  rather than the change (`target`, `dependents`, `named_by_user`), and are
 *  rendered by the typed-confirmation UI and the dependents list, not this table. */
const KNOWN_KEYS = new Set([
  "reads", "validated", "error", "already_exists", "cost_estimate_available",
  "name", "sql", "summary",
  "target", "dependents", "named_by_user",
])

export type PreviewEntry = { key: string; label: string; value: string }

/** "new_interval_minutes" -> "New interval minutes". Applied to every key this
 *  module renders, including nested object keys, so a preview shape nobody wrote
 *  copy for still reads as words rather than a snake_case field name. */
export function humanizeKey(key: string): string {
  const spaced = key.replace(/_/g, " ").trim()
  if (!spaced) return key
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** A value of any shape a preview might hold, as one legible string — including a
 *  nested object or array, so a value that is itself structured (a source
 *  descriptor, a list of roles) stays legible rather than printing as
 *  `[object Object]`. */
export function formatPreviewValue(value: unknown): string {
  if (value === null || value === undefined) return "—"
  if (typeof value === "boolean") return value ? "yes" : "no"
  if (typeof value === "number") return String(value)
  if (typeof value === "string") return value.length > 0 ? value : "—"
  if (Array.isArray(value)) {
    return value.length > 0 ? value.map(formatPreviewValue).join(", ") : "—"
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
    return entries.length > 0
      ? entries.map(([k, v]) => `${humanizeKey(k)}: ${formatPreviewValue(v)}`).join("; ")
      : "—"
  }
  return String(value)
}

/** Every preview field with no dedicated rendering elsewhere, as label/value pairs,
 *  in the order the server sent them. `extraExcluded` lets a caller fold in the keys
 *  it *does* handle specially (e.g. `PreviewBody`'s own fixed-key rendering) without
 *  duplicating them here. */
export function genericPreviewEntries(
  preview: Record<string, unknown> | null | undefined,
  extraExcluded: readonly string[] = [],
): PreviewEntry[] {
  if (!preview) return []
  const excluded = new Set(extraExcluded)
  return Object.entries(preview)
    .filter(([key, value]) => !KNOWN_KEYS.has(key) && !excluded.has(key) && value !== undefined)
    .map(([key, value]) => ({ key, label: humanizeKey(key), value: formatPreviewValue(value) }))
}
