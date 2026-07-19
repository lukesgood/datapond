"use client"

import { AiBackends } from "@/components/settings/ai-backends"

// AI Gateway — first-class home for LiteLLM model routing, virtual keys,
// usage, and budgets. Promoted out of Settings so the model-provider boundary
// that powers the whole foundation is discoverable, not buried.
export default function AiGatewayPage() {
  return (
    <div className="flex-1 space-y-5 p-8 pt-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">AI</p>
        <h1 className="mt-0.5 text-[23px] font-semibold tracking-tight">AI Gateway</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Route embeddings, RAG, and AI SQL through logical LiteLLM models; manage configured cloud or local providers, virtual keys, usage, and budgets.
        </p>
      </div>
      <AiBackends />
    </div>
  )
}
