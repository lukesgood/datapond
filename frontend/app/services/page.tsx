"use client"

import { useCallback, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import {
  Activity,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Search,
  RefreshCw,
  ExternalLink,
} from "lucide-react"

interface Service {
  name: string
  status: "healthy" | "unhealthy" | "unknown" | "managed"
  url?: string
  version?: string
  description?: string
}

// Internal K8s DNS → browser-accessible ingress path
const EXTERNAL_URLS: Record<string, string> = {
  jupyterlab:    "/jupyter",
  mlflow:        "/mlflow",
  trino:         "/api/trino",
  openmetadata:  "/openmetadata",
  minio:         "/storage",
  airflow:       "/airflow",
}

function getExternalUrl(name: string): string | null {
  return EXTERNAL_URLS[name] ?? null
}

export default function ServicesPage() {
  const router = useRouter()
  const [services, setServices] = useState<Service[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  // Status filter runs alongside the name search so a busy grid can be scoped
  // to just the things that need attention (issues) without scrolling.
  const [statusFilter, setStatusFilter] = useState<"all" | "healthy" | "issues" | "managed">("all")

  const fetchServices = useCallback(async () => {
    try {
      setLoading(true)
      const response = await fetch("/api/services")
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      setServices(Array.isArray(data) ? data : [])
      setError(null)
    } catch (error) {
      console.error("Failed to fetch services:", error)
      // Don't render a stale/empty grid as if everything is fine — surface it.
      setError(error instanceof Error ? error.message : "Failed to load services")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => void fetchServices(), 0)
    const interval = window.setInterval(() => void fetchServices(), 30000)
    return () => { window.clearTimeout(initial); window.clearInterval(interval) }
  }, [fetchServices])

  // Fallback descriptions only — the backend now supplies `description`.
  const serviceDescriptions: Record<string, string> = {
    backend: "DataPond API (FastAPI)",
    frontend: "Management UI (Next.js)",
    litellm: "Portable AI model gateway",
    valkey: "Redis-compatible cache / sessions",
    "Amazon S3": "Object storage (Iceberg data)",
    "Amazon Aurora": "PostgreSQL + pgvector (managed)",
    "Amazon Bedrock": "LLM / embeddings (managed)",
    "AWS Glue": "Iceberg Data Catalog (serverless)",
    "Amazon Athena": "Serverless SQL query engine",
    // Full-profile (self-hosted) services
    postgres: "PostgreSQL database - metadata storage",
    minio: "S3-compatible object storage",
    trino: "Distributed SQL query engine",
    polaris: "Apache Iceberg REST catalog",
    spark: "Distributed batch compute add-on",
    ollama: "Local model and embedding runtime",
  }

  const matchesStatus = (s: Service) => {
    if (statusFilter === "all") return true
    if (statusFilter === "issues") return s.status === "unhealthy" || s.status === "unknown"
    return s.status === statusFilter
  }

  const filteredServices = services.filter(
    (service) =>
      service.name.toLowerCase().includes(searchQuery.toLowerCase()) && matchesStatus(service)
  )

  const healthyCount = services.filter((s) => s.status === "healthy").length
  const unhealthyCount = services.filter((s) => s.status === "unhealthy" || s.status === "unknown").length
  const configuredCount = services.filter((s) => s.status === "managed").length

  // Left-edge color accent encodes status as form+color so the grid is scannable
  // at a glance, before reading the badge text.
  const statusAccent = (status: string) => {
    switch (status) {
      case "healthy":
        return "border-l-2 border-l-[var(--dp-good)]"
      case "unhealthy":
        return "border-l-2 border-l-destructive"
      case "unknown":
        return "border-l-2 border-l-[var(--dp-warn)]"
      default:
        return "border-l-2 border-l-muted-foreground/30"
    }
  }

  const statusFilters: { key: typeof statusFilter; label: string; count: number }[] = [
    { key: "all", label: "All", count: services.length },
    { key: "healthy", label: "Healthy", count: healthyCount },
    { key: "issues", label: "Issues", count: unhealthyCount },
    { key: "managed", label: "Adapters", count: configuredCount },
  ]

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "healthy":
        return (
          <Badge variant="default" className="bg-[var(--dp-good)] text-white">
            <CheckCircle2 className="mr-1 h-3 w-3" />
            Healthy
          </Badge>
        )
      case "unhealthy":
        return (
          <Badge variant="destructive">
            <XCircle className="mr-1 h-3 w-3" />
            Unhealthy
          </Badge>
        )
      case "managed":
        return (
          <Badge variant="outline">
            <ExternalLink className="mr-1 h-3 w-3" />
            Configured adapter
          </Badge>
        )
      default:
        return (
          <Badge variant="secondary">
            <AlertCircle className="mr-1 h-3 w-3" />
            Unknown
          </Badge>
        )
    }
  }

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Skeleton className="h-5 w-[200px]" />
        <div className="space-y-2">
          <Skeleton className="h-8 w-[150px]" />
          <Skeleton className="h-4 w-[300px]" />
        </div>
        <div className="grid gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-[120px]" />
          ))}
        </div>
        <Skeleton className="h-[400px]" />
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="/dashboard">Home</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Services</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Platform Services</h2>
          <p className="text-muted-foreground">
            Monitor configured DataPond workloads and external adapters
          </p>
        </div>

        <Button variant="outline" size="sm" onClick={fetchServices}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      {/* Search + status filter */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full max-w-md">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            aria-label="Search services by name"
            placeholder="Search services..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
          />
        </div>

        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter services by status">
          {statusFilters.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setStatusFilter(f.key)}
              aria-pressed={statusFilter === f.key}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                statusFilter === f.key
                  ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                  : "text-muted-foreground hover:bg-muted"
              }`}
            >
              {f.label}
              <span className="dp-num tabular-nums font-semibold">{f.count}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Health summary — healthy share across all reporting services */}
      {services.length > 0 && (
        <div className="flex items-center gap-3 rounded-md border dp-surface px-3 py-2">
          <span className="whitespace-nowrap text-xs text-muted-foreground">
            <span className="dp-num tabular-nums font-semibold text-foreground">{healthyCount}</span>
            {" / "}
            <span className="dp-num tabular-nums">{services.length}</span> healthy
          </span>
          <div
            className="flex h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
            role="img"
            aria-label={`${healthyCount} healthy, ${unhealthyCount} with issues, ${configuredCount} configured adapters, of ${services.length} total`}
          >
            {healthyCount > 0 && (
              <div className="bg-[var(--dp-good)]" style={{ width: `${(healthyCount / services.length) * 100}%` }} />
            )}
            {unhealthyCount > 0 && (
              <div className="bg-destructive" style={{ width: `${(unhealthyCount / services.length) * 100}%` }} />
            )}
            {configuredCount > 0 && (
              <div className="bg-muted-foreground/40" style={{ width: `${(configuredCount / services.length) * 100}%` }} />
            )}
          </div>
        </div>
      )}

      {/* Statistics Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Total Services</CardTitle>
              <Activity className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold dp-num">{services.length}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Healthy</CardTitle>
              <CheckCircle2 className="h-4 w-4 text-[var(--dp-good)]" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-[var(--dp-good)] dp-num">{healthyCount}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Issues</CardTitle>
              <XCircle className="h-4 w-4 text-destructive" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-destructive dp-num">{unhealthyCount}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Configured adapters</CardTitle>
              <ExternalLink className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold dp-num">{configuredCount}</div>
          </CardContent>
        </Card>
      </div>

      {/* A refresh failed but we still have a prior snapshot — say so rather than
          silently showing state that may be stale. */}
      {error && services.length > 0 && (
        <div className="flex items-center gap-2 rounded-md border border-[var(--dp-warn)]/40 bg-[var(--dp-warn)]/10 px-3 py-2 text-xs">
          <AlertCircle className="h-4 w-4 shrink-0 text-[var(--dp-warn)]" />
          <span>Showing last known state — refresh failed ({error}).</span>
        </div>
      )}

      {/* Services Grid */}
      {error && services.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-lg border bg-muted/30 p-12 text-center">
          <XCircle className="h-6 w-6 text-[var(--dp-bad)]" />
          <p className="text-sm font-medium">Could not load services</p>
          <p className="text-xs text-muted-foreground">{error}</p>
        </div>
      ) : !loading && filteredServices.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-lg border bg-muted/30 p-12 text-center">
          <p className="text-sm font-medium">
            {searchQuery || statusFilter !== "all" ? "No services match your filters" : "No services found"}
          </p>
          <p className="text-xs text-muted-foreground">
            {searchQuery || statusFilter !== "all"
              ? "Adjust the search or status filter to see more."
              : "No platform services are reporting yet."}
          </p>
        </div>
      ) : (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filteredServices.map((service) => (
          <Card
            key={service.name}
            className={`${statusAccent(service.status)} ${service.status === "managed" ? "transition-shadow" : "hover:shadow-md transition-shadow cursor-pointer"}`}
            onClick={() => { if (service.status !== "managed") router.push(`/services/${service.name}`) }}
          >
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base capitalize">{service.name}</CardTitle>
                {getStatusBadge(service.status)}
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground line-clamp-2">
                {service.description ?? serviceDescriptions[service.name] ?? "DataPond platform service"}
              </p>

              {service.version && (
                <div className="text-xs text-muted-foreground">
                  Version: {service.version}
                </div>
              )}

              <div className="flex gap-2 pt-2">
                {service.status !== "managed" && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={(e) => {
                      e.stopPropagation()
                      router.push(`/services/${service.name}`)
                    }}
                  >
                    Details
                  </Button>
                )}
                {getExternalUrl(service.name) && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation()
                      window.open(getExternalUrl(service.name)!, "_blank")
                    }}
                  >
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      )}
    </div>
  )
}
