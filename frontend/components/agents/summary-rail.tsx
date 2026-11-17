"use client"

import { AlertTriangle, Check, X } from "lucide-react"
import { useCapability } from "@/lib/capabilities"
import { formatUsd } from "@/lib/format-usd"
import {
  agentAttention, agentStatus, describeAccess, effectivePiiMode, keyPermissions,
  type AgentDetail, type ByActor,
} from "@/lib/agents"
import { useJson } from "./use-json"

const TONE = { ok: "text-[var(--dp-good-text)]", warn: "text-[var(--dp-warn-text)]", bad: "text-destructive" } as const
const DOT = { ok: "bg-[var(--dp-good)]", warn: "bg-[var(--dp-warn)]", bad: "bg-destructive" } as const

/** What the agent can do right now, beside the settings that decide it: status, the
 *  gaps between what was set up and what will work, what its live keys allow, and the
 *  numbers an operator checks first. Each source loads on its own; one that fails or is
 *  still loading shows "—" and adds no warning. */
export function SummaryRail({ agent, since, rev }: { agent: AgentDetail; since: string; rev: number }) {
  const catalogsOn = useCapability("catalog")
  const collections = useJson<{ collections: { name: string; access: string }[] }>(`/api/service-accounts/${agent.id}/collections`, rev)
  const catalogs = useJson<{ catalogs: { catalog: string; via: string | null }[] }>(
    catalogsOn ? `/api/service-accounts/${agent.id}/catalogs` : null, rev)
  const spend = useJson<{ max_budget: number | null; spend: number }>(`/api/settings/ai/budgets/${encodeURIComponent(agent.id)}`, rev)
  const calls = useJson<{ by_actor: ByActor[] }>(`/api/audit/tool-calls/summary?since=${encodeURIComponent(since)}`)

  const now = new Date()
  const status = agentStatus(agent, now)
  const perms = keyPermissions(agent, now)
  const access = describeAccess(perms)
  const attention = agentAttention(agent, now, collections.data?.collections ?? null,
    catalogsOn ? (catalogs.data?.catalogs ?? null) : [])
  const live = agent.keys.filter(k => k.status === "active" && (!k.expires_at || new Date(k.expires_at) > now))
  const nextExpiry = live.map(k => k.expires_at).filter((x): x is string => !!x).sort()[0]
  const mine = calls.data?.by_actor.find(r => r.actor_id === agent.id)
  const deployment = agent.pii_default ?? "mask"

  return (
    <aside aria-label="What this agent can do now"
           className="min-w-0 flex-[2_1_300px] space-y-4 rounded-xl border bg-muted/40 p-5 lg:sticky lg:top-6">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Right now</h3>
        <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${TONE[status.tone]}`}>
          <span aria-hidden className={`h-2 w-2 rounded-full ${DOT[status.tone]}`} />{status.label}
        </span>
      </div>

      {attention.length > 0 && (
        <div className="space-y-1.5 rounded-lg border border-[var(--dp-warn)]/40 bg-[var(--dp-warn)]/5 p-3">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-[var(--dp-warn-text)]">
            <AlertTriangle aria-hidden className="h-3.5 w-3.5" />Needs attention
          </p>
          <ul className="space-y-1 text-xs">
            {attention.map(a => <li key={a.text} className={a.tone === "bad" ? "text-destructive" : ""}>{a.text}</li>)}
          </ul>
        </div>
      )}

      {perms.length > 0 && (
        <>
          <List title="Its keys can" items={access.can} ok />
          <List title="They cannot" items={access.cannot} />
        </>
      )}

      <dl className="grid grid-cols-[84px_minmax(0,1fr)] gap-x-3 gap-y-2 border-t pt-3 text-sm">
        <dt className="text-muted-foreground">Role</dt><dd className="font-mono text-xs leading-5">{agent.role}</dd>
        <dt className="text-muted-foreground">Keys</dt>
        <dd>{live.length} active{nextExpiry ? `, next expiry ${nextExpiry.slice(0, 10)}` : live.length ? ", none expire" : ""}</dd>
        <dt className="text-muted-foreground">PII</dt><dd>applies: {effectivePiiMode(agent.pii_mode ?? null, deployment)}</dd>
        <dt className="text-muted-foreground">Spend</dt>
        <dd>{spend.data ? `${formatUsd(spend.data.spend)} · ${spend.data.max_budget === null ? "no cap" : `cap ${formatUsd(spend.data.max_budget)}`}` : "—"}</dd>
        <dt className="text-muted-foreground">Calls 24h</dt>
        <dd>{calls.data ? `${mine?.calls ?? 0} · ${mine?.refused ?? 0} refused` : "—"}</dd>
      </dl>
    </aside>
  )
}

function List({ title, items, ok }: { title: string; items: string[]; ok?: boolean }) {
  return (
    <div className="space-y-1.5">
      <h4 className="text-xs font-semibold">{title}</h4>
      <ul className="space-y-1">
        {items.map(t => (
          <li key={t} className="flex gap-2 text-xs">
            {ok ? <Check aria-hidden className="mt-px h-3.5 w-3.5 shrink-0 text-[var(--dp-good-text)]" />
                : <X aria-hidden className="mt-px h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
            <span className={ok ? "" : "text-muted-foreground"}>{t}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
