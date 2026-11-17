// A collection's PII mode and sensitivity label, explained. Mirrors
// backend app/collection_protection.py and app/sensitivity.py; pure for node --test.

export type PiiMode = "off" | "mask" | "block"
export type Sensitivity = "public" | "internal" | "confidential" | "restricted"
export const SENSITIVITIES: Sensitivity[] = ["public", "internal", "confidential", "restricted"]

const PII_RANK: Record<string, number> = { off: 1, mask: 2, block: 3 }
const SENS_RANK: Record<string, number> = { public: 1, internal: 2, confidential: 3, restricted: 4 }
/** The PII mode a label requires at least (app/sensitivity.py _PII_FLOOR). */
const FLOOR: Record<Sensitivity, PiiMode | null> = { public: null, internal: null, confidential: "mask", restricted: "block" }

const rankPii = (m: PiiMode | null | undefined) => (m ? PII_RANK[m] ?? 0 : 0)
const rankSens = (s: Sensitivity | null | undefined) => (s ? SENS_RANK[s] ?? 0 : 0)

export const lowersPii = (from: PiiMode | null | undefined, to: PiiMode | null | undefined) => rankPii(to) < rankPii(from)
export const lowersSensitivity = (from: Sensitivity | null | undefined, to: Sensitivity | null | undefined) => rankSens(to) < rankSens(from)

/** What applies to answers from this collection: the strictest of the deployment
 *  default, the collection's own mode and its label's floor. */
export function effectivePii(deployment: PiiMode, own: PiiMode | null, label: Sensitivity | null): PiiMode {
  const cands: PiiMode[] = [deployment]
  if (own) cands.push(own)
  if (label && FLOOR[label]) cands.push(FLOOR[label] as PiiMode)
  return cands.reduce((a, b) => (rankPii(b) > rankPii(a) ? b : a))
}

export const PII_TEXT: Record<PiiMode, string> = {
  off: "Text reaches the model and answers unchanged.",
  mask: "Korean PII is masked at ingest, before the model, and in answers.",
  block: "A request or document carrying PII is refused.",
}

export const SENSITIVITY_TEXT: Record<Sensitivity, string> = {
  public: "Any model the gateway allows; no extra masking.",
  internal: "Any model the gateway allows; no extra masking.",
  confidential: "PII is at least masked, whatever the mode says.",
  restricted: "PII is blocked and only local models are used — ingest and answers fail on a deployment without one.",
}

/** Why the effective mode is stricter than the collection's own, if it is. */
export function piiReason(deployment: PiiMode, own: PiiMode | null, label: Sensitivity | null): string | null {
  const eff = effectivePii(deployment, own, label)
  if (own && eff === own) return null
  if (label && FLOOR[label] === eff && rankPii(FLOOR[label]) > rankPii(own)) return `raised to ${eff} by the ${label} label`
  if (eff === deployment && rankPii(deployment) > rankPii(own)) return own ? `the deployment default ${deployment} is stricter` : `inherited from the deployment`
  return null
}
