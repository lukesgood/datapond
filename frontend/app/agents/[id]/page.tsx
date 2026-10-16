"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { ArrowLeft, Bot } from "lucide-react"
import { PermissionGate } from "@/components/ui/permission-state"
import { Loading, SectionError } from "@/components/agents/section"
import { useJson } from "@/components/agents/use-json"
import { IdentitySection } from "@/components/agents/identity-section"
import { KeysSection } from "@/components/agents/keys-section"
import { AccessSection } from "@/components/agents/access-section"
import { SpendSection } from "@/components/agents/spend-section"
import { ActivitySection } from "@/components/agents/activity-section"
import { DangerSection } from "@/components/agents/danger-section"
import type { AgentDetail } from "@/lib/agents"

export default function AgentPage() {
  return (
    <PermissionGate permission="user:manage" label="Agents">
      <AgentDetailPage />
    </PermissionGate>
  )
}

function AgentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const agent = useJson<AgentDetail>(`/api/service-accounts/${encodeURIComponent(id)}`)

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-5 px-6 py-6">
        <Link href="/agents" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-3.5 w-3.5" />All agents
        </Link>

        {agent.loading ? <Loading what="agent" /> : agent.status === 404 ? (
          // Deleted in another tab, or an id that was never a service account.
          <div className="space-y-2 py-10 text-center">
            <Bot className="mx-auto h-6 w-6 text-muted-foreground" />
            <p className="text-sm font-medium">This agent no longer exists</p>
            <Link href="/agents" className="text-xs text-primary hover:underline">Back to agents</Link>
          </div>
        ) : !agent.data ? (
          <SectionError message={`Could not load this agent: ${agent.error}`} onRetry={agent.reload} />
        ) : (
          <>
            <div>
              <h2 className="text-2xl font-bold tracking-tight">{agent.data.display_name || agent.data.username}</h2>
              <p className="font-mono text-xs text-muted-foreground">{agent.data.username}</p>
            </div>
            <IdentitySection agent={agent.data} onChange={agent.reload} />
            <KeysSection agent={agent.data} onChange={agent.reload} />
            <AccessSection agent={agent.data} onChange={agent.reload} />
            <SpendSection accountId={agent.data.id} />
            <ActivitySection accountId={agent.data.id} />
            <DangerSection agent={agent.data} onChange={agent.reload} />
          </>
        )}
      </div>
    </div>
  )
}
