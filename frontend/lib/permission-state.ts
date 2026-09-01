/** The three answers to "may I do this", given what `usePermissions()` (lib/permissions.tsx)
 *  knows right now — as opposed to the one boolean `useHasPermission` gives, which cannot
 *  tell "your role does not include this" from "the fetch that would have told us failed".
 *
 *  Both read as nothing today: `loaded` stays false either way, and a gated control just
 *  stays hidden. That is fail-closed, which is correct — but it also means a viewer who
 *  is missing `ai:generate` and a viewer whose network dropped mid-fetch see the exact
 *  same blank space, and file the exact same "why can't I see this" ticket to two
 *  different teams. See components/ui/permission-state.tsx for the component that renders
 *  the difference; this file is the rule alone, so it can be asserted on directly.
 */

export type PermissionAccess = "allowed" | "denied" | "unknown"

export interface PermissionStateInput {
  /** `usePermissions().loaded` — true once GET /api/me/permissions has answered. */
  loaded: boolean
  /** `usePermissions().error` — true when that fetch itself failed (network, non-2xx).
   *  Distinct from `!loaded`: a request still in flight is also not yet loaded, but has
   *  not failed. Both read as "unknown" here — the difference is `loaded` will still
   *  arrive on its own for one and not the other, which is why the component offers a
   *  retry only when `error` is what is holding things up. */
  error: boolean
  /** Whether the caller holds the permission in question, once `loaded` says the answer
   *  is final. Meaningless — and not consulted — while `loaded` is false or `error` is
   *  true, which is the exact case a plain boolean cannot express: `allowed: false` here
   *  does not mean "denied" unless the fetch that produced it actually succeeded. */
  allowed: boolean
}

/** `"unknown"` whenever the answer isn't settled yet — still loading, or the fetch that
 *  would have settled it failed — and only "allowed"/"denied" once it genuinely is. */
export function permissionState({ loaded, error, allowed }: PermissionStateInput): PermissionAccess {
  if (error || !loaded) return "unknown"
  return allowed ? "allowed" : "denied"
}
