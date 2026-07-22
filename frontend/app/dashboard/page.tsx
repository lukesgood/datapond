"use client"

import { useCallback, useEffect, useState } from "react"
import { JourneyStrip } from "@/components/dashboard/journey-strip"
import { StatsCards } from "@/components/dashboard/stats-cards"
import { ServiceCard } from "@/components/dashboard/service-card"
import { ErrorBox } from "@/components/ui/error-box"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { RefreshCw } from "lucide-react"
import { useCapabilities } from "@/lib/capabilities"
import { getProductProfile } from "@/lib/product-profile"

interface Service {
  name: string
  status: "healthy" | "unhealthy" | "unknown" | "managed"
  url?: string
  version?: string
  description?: string
}

interface DashboardStats {
  total_services: number
  healthy_services: number
  unhealthy_services: number
}

interface CollectionSummary { chunks?: number }
interface CollectionsResponse { collections?: CollectionSummary[] }
interface StorageSummary { total_size_human?: string; total_object_count?: number }

async function fetchJson(url: string): Promise<unknown> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

export default function DashboardPage() {
  const caps = useCapabilities()
  const profile = getProductProfile(caps)
  const [services, setServices] = useState<Service[] | null>(null)
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [collections, setCollections] = useState<number | null>(null)
  const [vectors, setVectors] = useState<number | null>(null)
  const [storageHuman, setStorageHuman] = useState<string | null>(null)
  const [storageObjects, setStorageObjects] = useState<number | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchData = useCallback(async () => {
    setRefreshing(true)
    const [svc, st, cols, store] = await Promise.allSettled([
      fetchJson("/api/services"),
      fetchJson("/api/dashboard/stats"),
      fetchJson("/api/ai/collections"),
      fetchJson("/api/storage/overview"),
    ])
    const failed: string[] = []

    if (svc.status === "fulfilled" && Array.isArray(svc.value)) {
      setServices(svc.value as Service[])
    } else {
      setServices(null)
      failed.push("service status")
    }

    if (st.status === "fulfilled" && st.value && typeof st.value === "object") {
      setStats(st.value as DashboardStats)
    } else {
      setStats(null)
      failed.push("dashboard health statistics")
    }

    if (cols.status === "fulfilled") {
      const payload = cols.value as CollectionsResponse | CollectionSummary[]
      const list = Array.isArray(payload) ? payload : payload?.collections
      if (Array.isArray(list)) {
        setCollections(list.length)
        setVectors(list.reduce((acc, collection) => acc + (collection.chunks ?? 0), 0))
      } else {
        setCollections(null)
        setVectors(null)
        failed.push("collection statistics")
      }
    } else {
      setCollections(null)
      setVectors(null)
      failed.push("collection statistics")
    }

    if (store.status === "fulfilled" && store.value && typeof store.value === "object") {
      const storage = store.value as StorageSummary
      setStorageHuman(storage.total_size_human ?? null)
      setStorageObjects(storage.total_object_count ?? null)
    } else {
      setStorageHuman(null)
      setStorageObjects(null)
      failed.push("storage statistics")
    }

    setErrors(failed)
    setLoading(false)
    setRefreshing(false)
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => void fetchData(), 0)
    const interval = window.setInterval(() => void fetchData(), 30000)
    return () => { window.clearTimeout(initial); window.clearInterval(interval) }
  }, [fetchData])

  const serviceDescriptions: Record<string, string> = {
    postgres: "PostgreSQL database - metadata storage",
    mlflow: "ML experiment tracking and model registry",
    jupyterlab: "Interactive data science notebooks",
    trino: "Distributed SQL query engine",
    risingwave: "Streaming SQL database",
    openmetadata: "Data catalog and lineage tracking",
    minio: "S3-compatible object storage",
    polaris: "Apache Iceberg REST catalog",
    valkey: "Redis-compatible cache",
  }

  const configured = services?.filter((service) => service.status === "managed").length ?? null
  const running = services?.filter((service) => service.status === "healthy").length ?? null
  const observed = services?.filter((service) => service.status !== "managed") ?? null
  const allObservedHealthy = !!observed?.length && observed.every((service) => service.status === "healthy")
  // Observed in-cluster workloads that are not confirmed healthy (unhealthy/unknown) — surfaced honestly.
  const attention = observed?.filter((service) => service.status !== "healthy").length ?? 0
  // Problem-first ordering so a degraded workload never hides at the bottom of the grid.
  const statusOrder: Record<Service["status"], number> = { unhealthy: 0, unknown: 1, healthy: 2, managed: 3 }
  const sortedServices = services
    ? [...services].sort((a, b) => statusOrder[a.status] - statusOrder[b.status])
    : null
  const healthAvailable = stats !== null || services !== null
  const totalServices = stats?.total_services ?? services?.length ?? 0
  const healthyServices = stats?.healthy_services ?? running ?? 0
  const summary = services
    ? `${profile.label}: ${running} healthy in-cluster workload${running === 1 ? "" : "s"}, ${configured} configured external adapter${configured === 1 ? "" : "s"}.${allObservedHealthy ? " All observed workloads are healthy." : ""}`
    : stats
      ? `${profile.label}: ${stats.healthy_services} of ${stats.total_services} observed workloads are healthy.`
      : profile.description

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6" aria-busy="true" aria-label="Loading dashboard">
        <div className="space-y-2">
          <Skeleton className="h-3 w-[80px]" />
          <Skeleton className="h-7 w-[240px]" />
        </div>
        <Skeleton className="h-[76px]" />
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-[110px]" />)}
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-[92px]" />)}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-5 p-8 pt-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">Overview</p>
          <h1 className="mt-0.5 text-[23px] font-semibold tracking-tight">Foundation health</h1>
          <p className="mt-1 text-sm text-muted-foreground">{summary}</p>
          {profile.adapters.length > 0 && (
            <p className="mt-1 text-[11px] capitalize text-muted-foreground">
              Active contracts: {profile.adapters.join(" · ")}
            </p>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={fetchData} disabled={refreshing}>
          <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          {refreshing ? "Refreshing" : "Refresh"}
        </Button>
      </div>

      {errors.length > 0 && (
        <div role="alert" aria-live="polite">
          <ErrorBox
            msg={`Some dashboard data is unavailable: ${errors.join(", ")}. Values from failed requests are shown as unavailable, not zero.`}
            action={<Button variant="outline" size="sm" onClick={fetchData} disabled={refreshing}>Retry</Button>}
          />
        </div>
      )}

      <JourneyStrip />

      {healthAvailable && (
        <StatsCards
          collections={collections}
          vectors={vectors}
          storageHuman={storageHuman}
          storageObjects={storageObjects}
          totalServices={totalServices}
          healthyServices={healthyServices}
        />
      )}

      <div className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold tracking-tight">Platform Services</h2>
          {services ? (
            <div className="flex items-center gap-1.5 text-xs">
              <span className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--dp-good)]" />
                <span className="font-semibold tabular-nums">{running}</span>
                <span className="text-muted-foreground">healthy</span>
              </span>
              {attention > 0 && (
                <span className="inline-flex items-center gap-1.5 rounded-md border border-[var(--dp-warn)]/30 px-2.5 py-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-[var(--dp-warn)]" />
                  <span className="font-semibold tabular-nums text-[var(--dp-warn)]">{attention}</span>
                  <span className="text-muted-foreground">need attention</span>
                </span>
              )}
              <span className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1">
                <span className="font-semibold tabular-nums">{configured}</span>
                <span className="text-muted-foreground">configured</span>
              </span>
            </div>
          ) : (
            <span className="text-xs text-muted-foreground">Status unavailable</span>
          )}
        </div>
        {services === null ? (
          <p className="rounded-md border px-4 py-8 text-center text-sm text-muted-foreground">
            Service details could not be loaded.
          </p>
        ) : services.length === 0 ? (
          <p className="rounded-md border px-4 py-8 text-center text-sm text-muted-foreground">
            No platform services were reported by the configured deployment.
          </p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {sortedServices!.map((service) => (
              <ServiceCard
                key={service.name}
                name={service.name}
                status={service.status}
                description={service.description ?? serviceDescriptions[service.name]}
                url={service.url}
                version={service.version}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
