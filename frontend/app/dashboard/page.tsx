"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { RefreshCw } from "lucide-react"
import { AttentionCard } from "@/components/dashboard/attention-card"
import { PlatformRail, type LakeFacts } from "@/components/dashboard/platform-rail"
import { TodayCard, type GlobalBudget, type TodayActor } from "@/components/dashboard/today-card"
import { Button } from "@/components/ui/button"
import { ErrorBox } from "@/components/ui/error-box"
import { PageHeader } from "@/components/ui/page-header"
import { Skeleton } from "@/components/ui/skeleton"
import { useCapabilities } from "@/lib/capabilities"
import {
  activityTotals, actorsFrom, platformStatus, spendFromBudgetAlerts, startOfLocalDay, type ServiceState,
} from "@/lib/dashboard-activity"
import { lakeCatalogCount, lastSyncAt, queriesSince } from "@/lib/lakehouse-summary"
import { parseOpsStatus, type OpsStatus } from "@/lib/ops-status"
import { agentProblems, attentionItems, catalogFact, getStartedSteps } from "@/lib/overview"
import type { Agent } from "@/lib/agents"
import { useHasPermission, usePermissions } from "@/lib/permissions"

const SKIPPED = Symbol("skipped")
const REFRESH_MS = 30_000

async function fetchJson(url: string): Promise<unknown> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

const arr = (d: unknown, key?: string): unknown[] | null => {
  const v = key ? (d && typeof d === "object" ? (d as Record<string, unknown>)[key] : undefined) : d
  return Array.isArray(v) ? v : null
}

const clock = (d: Date) => d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })

type Data = {
  actors: TodayActor[] | null
  spend: unknown
  budget: GlobalBudget
  services: ServiceState[] | null
  collections: number | null
  chunks: number | null
  storage: string | null
  ops: OpsStatus | null
  agents: Agent[] | null
  lakeCatalogs: number | null
  tables: { namespace: string; catalog?: string }[] | null
  sources: { last_sync_at: string | null }[] | null
  history: { created_at?: string }[] | null
  failed: string[]
  at: Date
}

export default function DashboardPage() {
  const caps = useCapabilities()
  const canAudit = useHasPermission("audit:read")
  const canSpend = useHasPermission("spend:read")
  const canKnowledge = useHasPermission("knowledge:read")
  const canManage = useHasPermission("service:manage")
  const canAgents = useHasPermission("user:manage")
  const canSync = useHasPermission("connector:write")
  const { permissions, loaded: permissionsLoaded, error: permissionsError } = usePermissions()
  const hasCatalog = caps.catalog === true
  const hasSources = caps.connectors === true
  const hasQuery = caps.query === true
  // Only the latest fetch may write: one started before the permissions arrived (every
  // permission false) could finish after the real one and blank the activity.
  const latest = useRef(0)
  const [data, setData] = useState<Data | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const fetchData = useCallback(async () => {
    const mine = ++latest.current
    setRefreshing(true)
    const since = encodeURIComponent(startOfLocalDay(new Date()).toISOString())
    const when = (allowed: boolean, url: string) => (allowed ? fetchJson(url) : Promise.resolve(SKIPPED))
    const results = await Promise.allSettled([
      when(canAudit, `/api/audit/tool-calls/summary?since=${since}`),
      when(canSpend, "/api/settings/ai/budget-alerts"),
      fetchJson("/api/services"),
      when(canKnowledge, "/api/ai/collections"),
      fetchJson("/api/storage/overview"),
      fetchJson("/api/ops/status"),
      when(canAgents, "/api/service-accounts"),
      when(hasCatalog, "/api/catalogs"),
      when(hasCatalog, "/api/catalog/tables"),
      when(hasSources, "/api/connectors/connections"),
      when(hasQuery, "/api/queries/history?limit=200"),
    ])
    if (mine !== latest.current) return
    const [calls, budgetRes, svc, cols, store, ops, accounts, catalogs, tables, conns, history] =
      results.map(r => (r.status === "fulfilled" ? r.value : undefined))
    const failed: string[] = []
    const pick = <T,>(v: unknown, label: string, read: (v: unknown) => T | null): T | null => {
      if (v === SKIPPED) return null
      const out = v === undefined ? null : read(v)
      if (out === null) failed.push(label)
      return out
    }

    const colList = pick(cols, "collection statistics", v => arr(v) ?? arr(v, "collections")) as { chunks?: number }[] | null
    const storeValue = pick(store, "storage statistics", v =>
      v && typeof v === "object" ? (v as { total_size_human?: string; bucket_count?: number }) : null)
    setData({
      actors: pick(calls, "tool call activity", actorsFrom) as TodayActor[] | null,
      spend: budgetRes === SKIPPED ? null : spendFromBudgetAlerts(budgetRes),
      budget: budgetRes && budgetRes !== SKIPPED && typeof budgetRes === "object"
        ? ((budgetRes as { global?: GlobalBudget }).global ?? null) : null,
      services: pick(svc, "service status", v => arr(v)) as ServiceState[] | null,
      collections: colList ? colList.length : null,
      chunks: colList ? colList.reduce((n, c) => n + (c.chunks ?? 0), 0) : null,
      storage: storeValue?.total_size_human
        ? `${storeValue.total_size_human} in ${storeValue.bucket_count ?? 0} bucket${storeValue.bucket_count === 1 ? "" : "s"}` : null,
      ops: ops === undefined ? null : parseOpsStatus(ops),
      agents: pick(accounts, "agents", v => arr(v, "accounts")) as Agent[] | null,
      lakeCatalogs: (() => { const c = pick(catalogs, "catalogs", v => arr(v, "catalogs")); return c ? lakeCatalogCount(c as { kind: string; enabled: boolean }[]) : null })(),
      tables: pick(tables, "tables", v => arr(v, "tables")) as { namespace: string; catalog?: string }[] | null,
      sources: pick(conns, "sources", v => arr(v)) as { last_sync_at: string | null }[] | null,
      history: pick(history, "query history", v => arr(v, "items")) as { created_at?: string }[] | null,
      failed: ops === undefined ? [...failed, "operations status"] : failed,
      at: new Date(),
    })
    setRefreshing(false)
  }, [canAudit, canSpend, canKnowledge, canAgents, hasCatalog, hasSources, hasQuery])

  useEffect(() => {
    // Wait for the permissions (or their failure): until then every permission reads false.
    if (!permissionsLoaded && !permissionsError) return
    const initial = window.setTimeout(() => void fetchData(), 0)
    const interval = window.setInterval(() => void fetchData(), REFRESH_MS)
    return () => { window.clearTimeout(initial); window.clearInterval(interval) }
  }, [fetchData, permissionsLoaded, permissionsError])

  const refresh = (
    <div className="flex items-center gap-2.5">
      {data && <span className="text-xs text-muted-foreground">Updated {clock(data.at)} · every 30 s</span>}
      <Button variant="outline" size="sm" onClick={() => void fetchData()} disabled={refreshing}>
        <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
        Refresh
      </Button>
    </div>
  )

  if (!data) {
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1180px] space-y-5 px-6 py-6" aria-busy="true" aria-label="Loading overview">
          <PageHeader title="Overview" description="What needs you today, and what agents and people did with the data." actions={refresh} />
          <div className="flex flex-wrap gap-6">
            <div className="min-w-0 flex-[3_1_560px] space-y-4"><Skeleton className="h-16" /><Skeleton className="h-[260px]" /></div>
            <Skeleton className="h-[360px] min-w-0 flex-[2_1_300px]" />
          </div>
        </div>
      </div>
    )
  }

  const now = new Date()
  const totals = data.actors ? activityTotals(data.actors) : null
  const platform = data.services ? platformStatus(data.services) : null
  const adapters = (data.services ?? []).filter(s => s.status === "managed").map(s => s.name)
  const unreachable = data.ops?.issues.filter(i => i.kind === "catalog_unreachable").length ?? 0
  const items = data.ops
    ? attentionItems(data.ops.issues, data.agents ? agentProblems(data.agents, now) : [], permissions, now.getTime())
    : null
  const lake: LakeFacts | null = hasCatalog || hasSources || hasQuery ? {
    tables: data.tables ? data.tables.length : null,
    namespaces: data.tables ? new Set(data.tables.map(t => `${t.catalog ?? ""}.${t.namespace}`)).size : null,
    sources: data.sources ? data.sources.length : null,
    lastSync: data.sources ? lastSyncAt(data.sources) : null,
    queriesToday: data.history ? queriesSince(data.history, startOfLocalDay(now)) : null,
  } : null
  const steps = getStartedSteps({
    sources: hasSources && data.sources ? data.sources.length : null,
    queriedEver: hasQuery && data.history ? data.history.length > 0 : null,
    chunks: data.chunks,
    agentsWithKey: data.agents ? data.agents.filter(a => a.is_active && a.keys.some(k => k.status === "active")).length : null,
  })
  const checked = data.ops?.checked_at
    ? clock(new Date(data.ops.checked_at.endsWith("Z") || data.ops.checked_at.includes("+") ? data.ops.checked_at : `${data.ops.checked_at}Z`))
    : null

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[1180px] space-y-5 px-6 py-6">
        <PageHeader title="Overview" description="What needs you today, and what agents and people did with the data." actions={refresh} />

        {data.failed.length > 0 && (
          <div role="alert" aria-live="polite">
            <ErrorBox
              msg={`Some overview data is unavailable: ${data.failed.join(", ")}. Values that could not be read show as —, not zero.`}
              action={<Button variant="outline" size="sm" onClick={() => void fetchData()} disabled={refreshing}>Retry</Button>}
            />
          </div>
        )}

        <div className="flex flex-wrap items-start gap-6">
          <div className="min-w-0 flex-[3_1_560px] space-y-4">
            <AttentionCard items={items} canSync={canSync} checkedAt={checked} onChanged={() => void fetchData()} />
            <TodayCard canAudit={canAudit} canSpend={canSpend} actors={data.actors} totals={totals}
                       spend={data.spend} budget={data.budget} />
          </div>
          <PlatformRail
            platform={platform}
            adapters={adapters}
            catalogs={hasCatalog && data.lakeCatalogs !== null ? catalogFact(data.lakeCatalogs, unreachable) : null}
            storage={data.storage}
            lake={lake}
            collections={data.collections}
            chunks={data.chunks}
            steps={steps}
            canManage={canManage}
          />
        </div>
      </div>
    </div>
  )
}
