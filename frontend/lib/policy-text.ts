// Plain-language readings of row and column policies, for the Governance rail.
// Pure, so node --test reaches it.

export interface RowPolicyLike { filter_expression: string; roles: string[]; exempt_roles: string[]; enabled: boolean }
export interface MaskLike { masking_type: string; column_name: string; roles: string[]; enabled: boolean }

export const MASK_TEXT: Record<string, string> = {
  full: "replaced by ***",
  partial_email: "shown as its first letter and domain (k***@example.com)",
  partial_ssn: "shown as its last 4 characters (***-**-1234)",
  partial_phone: "shown as its last 4 digits (***-***-1234)",
  hash: "replaced by a hash (joins still work)",
  null: "returned as null",
  custom: "rewritten by a custom expression",
}

const list = (xs: string[]) =>
  xs.length <= 1 ? (xs[0] ?? "") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`

/** What a row policy does, in a sentence or three. A policy with no roles applies to
 *  nobody — the engine only applies a policy to the roles it names. */
export function describeRowPolicy(p: RowPolicyLike): string {
  if (!p.enabled) return "Off: nobody's rows are filtered by it."
  const parts: string[] = []
  if (p.roles.length === 0) parts.push("It names no roles, so it filters nobody.")
  else parts.push(`${list(p.roles)} see only rows where ${p.filter_expression.trim() || "…"}.`)
  if (p.exempt_roles.length) parts.push(`${list(p.exempt_roles)} see every row.`)
  if (p.roles.length) parts.push("Everyone else is not affected by this policy.")
  return parts.join(" ")
}

export function describeMask(m: MaskLike): string {
  if (!m.enabled) return `Off: ${m.column_name || "the column"} is returned as stored.`
  const what = MASK_TEXT[m.masking_type] ?? m.masking_type
  if (m.roles.length === 0) return "It names no roles, so it masks nothing."
  return `For ${list(m.roles)}, ${m.column_name || "the column"} is ${what}. Everyone else sees the stored value.`
}
