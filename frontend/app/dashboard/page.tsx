"use client"

import { useEffect, useState } from "react"
import { JourneyStrip } from "@/components/dashboard/journey-strip"
import { StatsCards } from "@/components/dashboard/stats-cards"
import { ServiceCard } from "@/components/dashboard/service-card"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { RefreshCw } from "lucide-react"

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

export default function DashboardPage() {
  const [services, setServices] = useState<Service[]>([])
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [collections, setCollections] = useState<number | null>(null)
  const [vectors, setVectors] = useState<number | null>(null)
  const [storageHuman, setStorageHuman] = useState<string | null>(null)
  const [storageObjects, setStorageObjects] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchData = async () => {
    // Each source is best-effort — one failing shouldn't blank the whole dashboard.
    const [svc, st, cols, store] = await Promise.allSettled([
      fetch("/api/services").then((r) => r.json()),
      fetch("/api/dashboard/stats").then((r) => r.json()),
      fetch("/api/ai/collections").then((r) => r.json()),
      fetch("/api/storage/overview").then((r) => r.json()),
    ])
    if (svc.status === "fulfilled" && Array.isArray(svc.value)) setServices(svc.value)
    if (st.status === "fulfilled") setStats(st.value)
    if (cols.status === "fulfilled") {
      const list = Array.isArray(cols.value) ? cols.value : cols.value?.collections ?? []
      setCollections(list.length)
      setVectors(list.reduce((acc: number, c: any) => acc + (c.chunks ?? 0), 0))
    }
    if (store.status === "fulfilled") {
      setStorageHuman(store.value?.total_size_human ?? null)
      setStorageObjects(store.value?.total_object_count ?? null)
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [])

  const serviceDescriptions: Record<string, string> = {
    postgres: "PostgreSQL database - metadata storage",
    mlflow: "ML experiment tracking and model registry",
    jupyterlab: "Interactive data science notebooks",
    trino: "Distributed SQL query engine",
    risingwave: "Streaming SQL database",
    openmetadata: "Data catalog and lineage tracking",
    seaweedfs: "S3-compatible object storage",
    polaris: "Apache Iceberg REST catalog",
    valkey: "Redis-compatible cache",
  }

  const managed = services.filter((s) => s.status === "managed").length
  const running = services.filter((s) => s.status === "healthy").length
  const allGreen = stats != null && stats.unhealthy_services === 0
  const summary = stats
    ? `${running} workload${running === 1 ? "" : "s"} on your cluster, ${managed} managed by AWS.${allGreen ? " All green." : ""}`
    : "Your AI Data Foundation at a glance."

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <div className="space-y-2">
          <Skeleton className="h-3 w-[80px]" />
          <Skeleton className="h-7 w-[240px]" />
        </div>
        <Skeleton className="h-[76px]" />
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-[110px]" />
          ))}
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {[...Array(6)].map((_, i) => (
            <Skeleton key={i} className="h-[92px]" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-5 p-8 pt-6">
      {/* Editorial header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">Overview</p>
          <h1 className="mt-0.5 text-[23px] font-semibold tracking-tight">Foundation health</h1>
          <p className="mt-1 text-sm text-muted-foreground">{summary}</p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchData}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      {/* The path your data takes */}
      <JourneyStrip />

      {/* Product stats */}
      <StatsCards
        collections={collections}
        vectors={vectors}
        storageHuman={storageHuman}
        storageObjects={storageObjects}
        totalServices={stats?.total_services ?? services.length}
        healthyServices={stats?.healthy_services ?? 0}
      />

      {/* Platform Services */}
      <div className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold tracking-tight">Platform Services</h2>
          <span className="text-xs text-muted-foreground tabular-nums">
            {running} running · {managed} managed
          </span>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {services.map((service) => (
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
      </div>
    </div>
  )
}
