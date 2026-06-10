"use client"

import { useEffect, useState } from "react"
import { PageHeader } from "@/components/dashboard/page-header"
import { JourneyStrip } from "@/components/dashboard/journey-strip"
import { StatsCards } from "@/components/dashboard/stats-cards"
import { ServiceCard } from "@/components/dashboard/service-card"
import { ServiceHealthChart } from "@/components/dashboard/service-health-chart"
import { ResourceCharts } from "@/components/dashboard/resource-charts"
import { ActivityTimeline } from "@/components/dashboard/activity-timeline"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { AlertCircle, Info } from "lucide-react"

interface Service {
  name: string
  status: "healthy" | "unhealthy" | "unknown"
  url?: string
  version?: string
}

interface DashboardStats {
  total_services: number
  healthy_services: number
  unhealthy_services: number
  cpu_usage?: number
  memory_usage?: number
}

export default function DashboardPage() {
  const [services, setServices] = useState<Service[]>([])
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchData = async () => {
    try {
      // Fetch services status
      const servicesRes = await fetch("/api/services")
      const servicesData = await servicesRes.json()
      setServices(servicesData)

      // Fetch dashboard stats
      const statsRes = await fetch("/api/dashboard/stats")
      const statsData = await statsRes.json()
      setStats(statsData)
    } catch (error) {
      console.error("Failed to fetch dashboard data:", error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()

    // Refresh every 30 seconds
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

  const unhealthyCount = stats?.unhealthy_services || 0

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        {/* Header skeleton */}
        <div className="space-y-2">
          <Skeleton className="h-4 w-[200px]" />
          <Skeleton className="h-8 w-[300px]" />
        </div>

        {/* Stats cards skeleton */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-[140px]" />
          ))}
        </div>

        {/* Two-column layout skeleton */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Skeleton className="lg:col-span-2 h-[400px]" />
          <Skeleton className="h-[400px]" />
        </div>

        {/* Resource chart skeleton */}
        <Skeleton className="h-[380px]" />

        {/* Services grid skeleton */}
        <div className="space-y-4">
          <Skeleton className="h-8 w-[200px]" />
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {[...Array(8)].map((_, i) => (
              <Skeleton key={i} className="h-[140px]" />
            ))}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      {/* Page Header */}
      <PageHeader onRefresh={fetchData} />

      {/* Data journey entry points */}
      <JourneyStrip />

      {/* Development mode notice */}
      {unhealthyCount > 0 && (
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            Running in local development mode. Services may show as unhealthy when accessed outside the cluster.
          </AlertDescription>
        </Alert>
      )}

      {/* Stats Cards */}
      {stats && (
        <StatsCards
          totalServices={stats.total_services}
          healthyServices={stats.healthy_services}
          cpuUsage={stats.cpu_usage}
          memoryUsage={stats.memory_usage}
        />
      )}

      {/* Two-column layout: Service Health Chart + Activity Timeline */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <ServiceHealthChart />
        </div>
        <div>
          <ActivityTimeline />
        </div>
      </div>

      {/* Resource Usage Chart */}
      <ResourceCharts />

      {/* Services Section with Tabs */}
      <Tabs defaultValue="all" className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold tracking-tight">Platform Services</h2>
          <TabsList>
            <TabsTrigger value="all">
              All ({services.length})
            </TabsTrigger>
            <TabsTrigger value="healthy">
              Healthy ({stats?.healthy_services || 0})
            </TabsTrigger>
            <TabsTrigger value="unhealthy">
              Issues ({unhealthyCount})
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="all" className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {services.map((service) => (
              <ServiceCard
                key={service.name}
                name={service.name}
                status={service.status}
                description={serviceDescriptions[service.name]}
                url={service.url}
                version={service.version}
              />
            ))}
          </div>
        </TabsContent>

        <TabsContent value="healthy" className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {services
              .filter((s) => s.status === "healthy")
              .map((service) => (
                <ServiceCard
                  key={service.name}
                  name={service.name}
                  status={service.status}
                  description={serviceDescriptions[service.name]}
                  url={service.url}
                  version={service.version}
                />
              ))}
          </div>
        </TabsContent>

        <TabsContent value="unhealthy" className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {services
              .filter((s) => s.status === "unhealthy" || s.status === "unknown")
              .map((service) => (
                <ServiceCard
                  key={service.name}
                  name={service.name}
                  status={service.status}
                  description={serviceDescriptions[service.name]}
                  url={service.url}
                  version={service.version}
                />
              ))}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
