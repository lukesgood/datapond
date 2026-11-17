"use client"

import { useState } from "react"
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
import { SummaryRail } from "@/components/agents/summary-rail"
import type { AgentDetail } from "@/lib/agents"

const SECTIONS = [
  ["#identity", "Identity"], ["#keys", "Keys"], ["#access", "Data access"],
  ["#spend", "Spend"], ["#activity", "Activity"], ["#danger", "Danger zone"],
] as const

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
  // Fixed for the page's life: it is part of a fetched URL, and a new value each render
  // would refetch forever.
  const [since] = useState(() => new Date(Date.now() - 24 * 3_600_000).toISOString())
  // Any change in a section reloads the agent and the summary rail's own sources.
  const [rev, setRev] = useState(0)
  const changed = () => { agent.reload(); setRev(r => r + 1) }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
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
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-2xl font-bold tracking-tight">{agent.data.display_name || agent.data.username}</h2>
                <p className="font-mono text-xs text-muted-foreground">{agent.data.username}</p>
              </div>
              <nav aria-label="Sections" className="flex flex-wrap gap-1">
                {SECTIONS.map(([href, label]) => (
                  <a key={href} href={href} className="rounded-md border bg-card px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground">{label}</a>
                ))}
              </nav>
            </div>
            <div className="flex flex-wrap items-start gap-6">
              <div className="min-w-0 flex-[3_1_560px] space-y-5">
                <IdentitySection agent={agent.data} onChange={changed} />
                <KeysSection agent={agent.data} onChange={changed} />
                <AccessSection agent={agent.data} onChange={changed} />
                <SpendSection accountId={agent.data.id} onChange={changed} />
                <ActivitySection accountId={agent.data.id} />
                <DangerSection agent={agent.data} onChange={changed} />
              </div>
              <SummaryRail agent={agent.data} since={since} rev={rev} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
