"use client"

import { ShieldAlert } from "lucide-react"
import { AiBackends, UsagePanel } from "@/components/settings/ai-backends"
import { useHasPermission, usePermissions } from "@/lib/permissions"
import { permissionState } from "@/lib/permission-state"
import { PermissionUnknown } from "@/components/ui/permission-state"

// AI Gateway — first-class home for LiteLLM model routing, virtual keys,
// usage, and budgets. Promoted out of Settings so the model-provider boundary
// that powers the whole foundation is discoverable, not buried.
export default function AiGatewayPage() {
  // Two audiences. Configuring the model boundary — which backends exist, who
  // holds a key — is admin (backend/app/api/ai_backends.py's backend/active/keys
  // routes are all `require_admin`, not a permission — there is no finer-grained
  // name to check, so this reads the role itself, sourced from /api/me/permissions
  // rather than the token in localStorage). Reading what was spent is `spend:read`,
  // held by ai_engineer and auditor: the roles most accountable for model cost, who
  // until now could not open the only screen that shows it. Showing them a menu
  // item that leads to "permission required" would have been worse than hiding it,
  // so they get the usage panel itself.
  const { role, loaded, error, refetch } = usePermissions()
  const isAdmin = role === "admin"
  const canSeeSpend = useHasPermission("spend:read")
  // "unknown" here means /api/me/permissions itself failed to answer, so neither
  // isAdmin nor canSeeSpend can be trusted — showing the ordinary denial copy would
  // have told an ai_engineer whose network hiccuped that their role was the problem.
  const access = permissionState({ loaded, error, allowed: isAdmin || canSeeSpend })
  return (
    <div className="flex-1 space-y-5 p-8 pt-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">AI</p>
        <h1 className="mt-0.5 text-[23px] font-semibold tracking-tight">AI Gateway</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Route embeddings, RAG, and AI SQL through logical LiteLLM models; manage configured cloud or local providers, virtual keys, usage, and budgets.
        </p>
      </div>
      {access === "unknown" ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border bg-muted/30 p-16 text-center">
          <PermissionUnknown onRetry={refetch} />
        </div>
      ) : isAdmin ? (
        <AiBackends />
      ) : canSeeSpend ? (
        <>
          <UsagePanel />
          <p className="text-xs text-muted-foreground">
            Model backends and virtual keys are managed by an administrator.
          </p>
        </>
      ) : (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border bg-muted/30 p-16 text-center">
          <ShieldAlert className="h-6 w-6 text-muted-foreground" />
          <h2 className="text-lg font-semibold">Admin permission required</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            The AI Gateway manages model providers, virtual keys, and spend. Ask an administrator for access.
          </p>
        </div>
      )}
    </div>
  )
}
