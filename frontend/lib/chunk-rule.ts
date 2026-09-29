/** Client-side twin of backend/app/chunk_access.py's `validate`, so the form can say
 *  what is wrong before a round trip. The server stays the authority. */

export interface ChunkRule { metadata_key: string; user_attribute: string }

/** What GET /ai/collections returns for `chunk_access`: a rule, null, or a stored rule
 *  that no longer parses (retrieval denies everything for it). */
export type StoredChunkRule = ChunkRule | { invalid: true } | null | undefined

const IDENT = /^[A-Za-z0-9_]{1,64}$/

export function validIdentifier(value: string): boolean {
  return IDENT.test(value)
}

/** An error sentence for the form, or null when both fields are acceptable. */
export function ruleError(rule: ChunkRule): string | null {
  if (!validIdentifier(rule.metadata_key) || !validIdentifier(rule.user_attribute)) {
    return "Both fields must be 1-64 letters, digits or underscores."
  }
  return null
}

export function isRule(stored: StoredChunkRule): stored is ChunkRule {
  return !!stored && "metadata_key" in stored
}

export function isInvalidRule(stored: StoredChunkRule): boolean {
  return !!stored && "invalid" in stored
}
