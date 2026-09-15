"use client"

import { useCallback, useEffect, useState } from "react"
import { RefreshCw } from "lucide-react"
import { ActivityPanel, type GlobalBudget } from "@/components/dashboard/activity-panel"
import { JourneyStrip } from "@/components/dashboard/journey-strip"
import { PlatformStatusLine } from "@/components/dashboard/platform-status-line"
import { Button } from "@/components/ui/button"
import { ErrorBox } from "@/components/ui/error-box"
import { Skeleton } from "@/components/ui/skeleton"
import {
  activitySentence, activityTotals, actorsFrom, platformStatus, spendFromBudgetAlerts, startOfLocalDay,
  type ActorSummary, type ServiceState,
} from "@/lib/dashboard-activity"
import { useHasPermission } from "@/lib/permissions"

interface CollectionSummary { chunks?: number }
interface CollectionsResponse { collections?: CollectionSummary[] }
interface StorageSummary { total_size_human?: string }

const SKIPPED = Symbol("skipped")

async function fetchJson(url: string): Promise<unknown> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

export default function DashboardPage() {
  const canAudit = useHasPermission("audit:read")
  const canSpend = useHasPermission("spend:read")
  const canKnowledge = useHasPermission("knowledge:read")
  const canManage = useHasPermission("service:manage")

  const [actors, setActors] = useState<ActorSummary[] | null>(null)
  const [spend, setSpend] = useState<unknown>(null)
  const [budget, setBudget] = useState<GlobalBudget>(null)
  const [services, setServices] = useState<ServiceState[] | null>(null)
  const [collections, setCollections] = useState<number | null>(null)
  const [chunks, setChunks] = useState<number | null>(null)
  const [storedHuman, setStoredHuman] = useState<string | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchData = useCallback(async () => {
    setRefreshing(true)
    const since = encodeURIComponent(startOfLocalDay(new Date()).toISOString())
    const when = (allowed: boolean, url: string) => (allowed ? fetchJson(url) : Promise.resolve(SKIPPED))
    const [calls, budgetRes, svc, cols, store] = await Promise.allSettled([
      when(canAudit, `/api/audit/tool-calls/summary?since=${since}`),
      // Carries the gateway-wide spend (spendFromBudgetAlerts) as well as the budget.
      when(canSpend, "/api/settings/ai/budget-alerts"),
      fetchJson("/api/services"),
      when(canKnowledge, "/api/ai/collections"),
      fetchJson("/api/storage/overview"),
    ])
    const failed: string[] = []
    const value = (r: PromiseSettledResult<unknown>) => (r.status === "fulfilled" ? r.value : undefined)

    const actorList = value(calls) === SKIPPED ? null : actorsFrom(value(calls))
    setActors(actorList)
    if (canAudit && actorList === null) failed.push("tool call activity")

    const budgetValue = value(budgetRes)
    setSpend(budgetValue === SKIPPED ? null : spendFromBudgetAlerts(budgetValue))
    setBudget(budgetValue && budgetValue !== SKIPPED && typeof budgetValue === "object"
      ? ((budgetValue as { global?: GlobalBudget }).global ?? null) : null)
    if (canSpend && budgetRes.status === "rejected") failed.push("budget")

    const svcValue = value(svc)
    if (Array.isArray(svcValue)) setServices(svcValue as ServiceState[])
    else { setServices(null); failed.push("service status") }

    const colsValue = value(cols)
    const list = colsValue === SKIPPED ? null
      : Array.isArray(colsValue) ? (colsValue as CollectionSummary[])
      : (colsValue as CollectionsResponse | undefined)?.collections ?? undefined
    if (Array.isArray(list)) {
      setCollections(list.length)
      setChunks(list.reduce((acc, c) => acc + (c.chunks ?? 0), 0))
    } else {
      setCollections(null); setChunks(null)
      if (list === undefined) failed.push("collection statistics")
    }

    const storeValue = value(store)
    setStoredHuman(storeValue && typeof storeValue === "object" ? ((storeValue as StorageSummary).total_size_human ?? null) : null)
    if (!storeValue) failed.push("storage statistics")

    setErrors(failed)
    setLoading(false)
    setRefreshing(false)
  }, [canAudit, canSpend, canKnowledge])

  useEffect(() => {
    const initial = window.setTimeout(() => void fetchData(), 0)
    const interval = window.setInterval(() => void fetchData(), 30000)
    return () => { window.clearTimeout(initial); window.clearInterval(interval) }
  }, [fetchData])

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6" aria-busy="true" aria-label="Loading overview">
        <Skeleton className="h-4 w-[80px]" />
        <Skeleton className="h-8 w-[320px]" />
        <Skeleton className="h-[220px]" />
        <Skeleton className="h-5 w-[480px]" />
      </div>
    )
  }

  const totals = actors ? activityTotals(actors) : null
  const platform = services ? platformStatus(services) : null
  const summary = totals
    ? activitySentence(totals)
    : platform
      ? `${platform.healthy} of ${platform.observed} workloads healthy.`
      : "Status is unavailable."

  return (
    <div className="flex-1 space-y-6 p-8 pt-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">Overview</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{canAudit ? "Today" : "Platform"}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{summary}</p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchData} disabled={refreshing}>
          <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          {refreshing ? "Refreshing" : "Refresh"}
        </Button>
      </div>

      {errors.length > 0 && (
        <div role="alert" aria-live="polite">
          <ErrorBox
            msg={`Some overview data is unavailable: ${errors.join(", ")}. Values from failed requests are shown as unavailable, not zero.`}
            action={<Button variant="outline" size="sm" onClick={fetchData} disabled={refreshing}>Retry</Button>}
          />
        </div>
      )}

      <ActivityPanel canAudit={canAudit} canSpend={canSpend} actors={actors} totals={totals} spend={spend} budget={budget} />

      <PlatformStatusLine platform={platform} collections={collections} chunks={chunks} storedHuman={storedHuman} canManage={canManage} />

      <JourneyStrip />
    </div>
  )
}
