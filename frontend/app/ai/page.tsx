"use client"

import { Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { ShieldAlert } from "lucide-react"
import { AiBackends, UsagePanel } from "@/components/settings/ai-backends"
import { CallerBudgets } from "@/components/settings/caller-budgets"
import { VirtualKeys } from "@/components/ai/virtual-keys"
import { PageHeader } from "@/components/ui/page-header"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useHasPermission, usePermissions } from "@/lib/permissions"
import { permissionState } from "@/lib/permission-state"
import { PermissionUnknown } from "@/components/ui/permission-state"

// Two audiences. Configuring the model boundary — backends, the default model, gateway
// keys — is admin (backend/app/api/ai_backends.py's routes are `require_admin`; there
// is no finer permission, so this reads the role from /api/me/permissions). Reading
// spend is `spend:read`, held by ai_engineer and auditor, who get Spend and Budgets.
const ADMIN_TABS = ["models", "spend", "budgets", "keys"] as const
const SPEND_TABS = ["spend", "budgets"] as const

function AiGatewayInner() {
  const router = useRouter()
  const asked = useSearchParams().get("tab")
  const { role, loaded, error, refetch } = usePermissions()
  const isAdmin = role === "admin"
  const canSeeSpend = useHasPermission("spend:read")
  const access = permissionState({ loaded, error, allowed: isAdmin || canSeeSpend })
  const tabs: readonly string[] = isAdmin ? ADMIN_TABS : SPEND_TABS
  const tab = asked && tabs.includes(asked) ? asked : tabs[0]
  const setTab = (v: string) => router.replace(v === tabs[0] ? "/ai" : `/ai?tab=${v}`, { scroll: false })

  return (
    <div className="mx-auto max-w-[1400px] flex-1 space-y-5 p-8 pt-6">
      <PageHeader title="AI Gateway" description="The models every AI feature calls, what they cost, and who may spend how much." />
      {access === "unknown" ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border bg-muted/30 p-16 text-center">
          <PermissionUnknown onRetry={refetch} />
        </div>
      ) : access === "denied" ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border bg-muted/30 p-16 text-center">
          <ShieldAlert className="h-6 w-6 text-muted-foreground" />
          <h2 className="text-lg font-semibold">Needs an administrator or spend:read</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            The AI Gateway manages model providers, caller budgets and spend. Ask an administrator for access.
          </p>
        </div>
      ) : (
        <Tabs value={tab} onValueChange={v => setTab(String(v))}>
          <TabsList>
            {isAdmin && <TabsTrigger value="models">Models</TabsTrigger>}
            <TabsTrigger value="spend">Spend</TabsTrigger>
            <TabsTrigger value="budgets">Budgets</TabsTrigger>
            {isAdmin && <TabsTrigger value="keys">Keys</TabsTrigger>}
          </TabsList>
          {isAdmin && <TabsContent value="models" className="mt-5"><AiBackends /></TabsContent>}
          <TabsContent value="spend" className="mt-5"><UsagePanel /></TabsContent>
          <TabsContent value="budgets" className="mt-5 space-y-3">
            <CallerBudgets canEdit={isAdmin} />
            {!isAdmin && <p className="text-xs text-muted-foreground">Caps are set by an administrator.</p>}
          </TabsContent>
          {isAdmin && <TabsContent value="keys" className="mt-5"><VirtualKeys /></TabsContent>}
        </Tabs>
      )}
    </div>
  )
}

export default function AiGatewayPage() {
  return <Suspense><AiGatewayInner /></Suspense>
}
