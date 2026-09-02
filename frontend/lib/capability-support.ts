/** Presentation logic for the support tier a capability carries.
 *
 *  The fact itself lives in exactly two places: `SUPPORT.md` says it in prose for a
 *  person reading the repo, and `backend/app/capabilities.py`'s `support_tiers()`
 *  derives it from `CAPABILITY_BACKENDS`/`UNSUPPORTED_BACKENDS`/`PREVIEW_CAPABILITIES`
 *  and serves it as `support: Record<string, string>` on `GET /api/capabilities`. This
 *  module does not decide which capability carries which tier — that would be a second,
 *  driftable copy of a classification the backend already derives and tests against
 *  `SUPPORT.md` and the pipeline-deploy refusal. All this module owns is turning the
 *  string the backend sends into a lookup (`supportTier`) and into the two sentences of
 *  UI copy (`supportBadge`) — the only UI-owned text for this feature.
 *
 *  `supportTier` returns `null` for a tier this build does not recognize, not the raw
 *  string. A backend newer than this frontend build could one day send a third tier;
 *  rendering an unreviewed word in the console would be worse than rendering nothing.
 */

export type SupportTier = "experimental" | "preview"

const KNOWN_TIERS: readonly SupportTier[] = ["experimental", "preview"]

function isKnownTier(value: string): value is SupportTier {
  return (KNOWN_TIERS as readonly string[]).includes(value)
}

/** The tier `capability` carries per `support`, or `null` if it is absent (supported)
 *  or carries a tier this build does not know the words for. */
export function supportTier(capability: string, support: Record<string, string>): SupportTier | null {
  const tier = support[capability]
  if (tier === undefined) return null
  return isKnownTier(tier) ? tier : null
}

/** The label and title for a support tier — the only place this UI copy lives. */
export function supportBadge(tier: SupportTier): { label: string; title: string } {
  if (tier === "preview") {
    return {
      label: "Preview",
      title: "Not deployable in this release: pipelines compile to placeholder tasks and the deploy is refused.",
    }
  }
  return {
    label: "Experimental",
    title: "Configuration around an upstream project. The wiring is supported; the project itself is not.",
  }
}
