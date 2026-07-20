"use client"

import { useState } from "react"
import { ShieldAlert } from "lucide-react"
import { AiBackends } from "@/components/settings/ai-backends"
import { getUser } from "@/lib/auth"

// AI Gateway — first-class home for LiteLLM model routing, virtual keys,
// usage, and budgets. Promoted out of Settings so the model-provider boundary
// that powers the whole foundation is discoverable, not buried.
export default function AiGatewayPage() {
  // Every backend this page calls (/settings/ai/{backends,keys,usage,spend}) is
  // admin-only. Gate the page so a non-admin sees an explicit notice instead of
  // editable forms that 403 on save.
  const [isAdmin] = useState(() => getUser()?.role === "admin")
  return (
    <div className="flex-1 space-y-5 p-8 pt-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">AI</p>
        <h1 className="mt-0.5 text-[23px] font-semibold tracking-tight">AI Gateway</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Route embeddings, RAG, and AI SQL through logical LiteLLM models; manage configured cloud or local providers, virtual keys, usage, and budgets.
        </p>
      </div>
      {isAdmin ? (
        <AiBackends />
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
