"use client"

import { ReactNode } from "react"
import { RefreshCw, ShieldQuestion } from "lucide-react"
import { Button } from "@/components/ui/button"
import { usePermissions, useHasPermission } from "@/lib/permissions"
import { permissionState } from "@/lib/permission-state"

/** Gates `children` on a permission, and renders which of the three
 *  `lib/permission-state.ts::permissionState` answers is current instead of just
 *  hiding the control — "you may not" (your role does not include this) and "we
 *  could not ask" (the /api/me/permissions fetch itself failed) used to collapse
 *  into the same silent nothing, which meant a denied ai_engineer and a viewer whose
 *  network dropped mid-load saw the identical blank space.
 *
 *  `permission` feeds `useHasPermission` for the ordinary case — the same
 *  permission-set membership check the sidebar already uses. Pass `allowed`
 *  instead (or as well) when the real decision needs more than membership, e.g.
 *  `lib/knowledge-actions.ts`'s ownership-aware `mayIngest`; `permission` still
 *  supplies the default denial label in that case.
 *
 *  `denied` and `unknown` let a page keep a richer, page-specific explanation (an
 *  icon, a heading, a link to ask an administrator) instead of the plain one-liner
 *  this renders by default — this component only decides *which* of the three
 *  states applies, not that every denial must look identical.
 */
export function PermissionGate({
  permission,
  allowed,
  label,
  denied,
  unknown,
  children,
}: {
  permission?: string
  allowed?: boolean
  label?: string
  denied?: ReactNode
  unknown?: ReactNode
  children: ReactNode
}) {
  const { loaded, error, refetch } = usePermissions()
  const held = useHasPermission(permission)
  const state = permissionState({ loaded, error, allowed: allowed ?? held })

  if (state === "allowed") return <>{children}</>
  if (state === "denied") return <>{denied ?? <PermissionDenied label={label ?? permission ?? "this"} />}</>
  return <>{unknown ?? <PermissionUnknown onRetry={refetch} />}</>
}

/** Default "you may not" line — one sentence, names what is missing, says who can
 *  grant it. Exported so a page can drop the exact same line into a custom layout
 *  (next to an icon, inside a card) without re-deriving the wording. */
export function PermissionDenied({ label }: { label: string }) {
  return (
    <p className="text-xs text-muted-foreground">
      Your role does not include <code className="font-mono">{label}</code> — ask an administrator.
    </p>
  )
}

/** Default "we could not ask" line, with the one thing a denial can't offer: a retry,
 *  because unlike a denial this state might just clear on its own. */
export function PermissionUnknown({ onRetry }: { onRetry: () => void }) {
  return (
    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <ShieldQuestion className="h-3.5 w-3.5 shrink-0" />
      Could not check your permissions.
      <Button size="sm" variant="ghost" className="h-6 gap-1 px-1.5 text-xs" onClick={onRetry}>
        <RefreshCw className="h-3 w-3" />Retry
      </Button>
    </p>
  )
}
