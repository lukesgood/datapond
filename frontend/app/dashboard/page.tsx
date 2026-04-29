"use client"

import { useEffect, useState } from "react"
import { StatsCards } from "@/components/dashboard/stats-cards"
import { ServiceCard } from "@/components/dashboard/service-card"
import { Skeleton } from "@/components/ui/skeleton"

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

  useEffect(() => {
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

  if (loading) {
    return (
      <div className="flex flex-col space-y-6 p-8">
        <div className="space-y-2">
          <Skeleton className="h-8 w-[250px]" />
          <Skeleton className="h-4 w-[350px]" />
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-[120px]" />
          ))}
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[...Array(9)].map((_, i) => (
            <Skeleton key={i} className="h-[180px]" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col space-y-6 p-8">
      <div className="space-y-1">
        <h1 className="text-3xl font-bold tracking-tight">DataPond Dashboard</h1>
        <p className="text-muted-foreground">
          Monitor all services and infrastructure in real-time
        </p>
      </div>

      {stats && (
        <StatsCards
          totalServices={stats.total_services}
          healthyServices={stats.healthy_services}
          cpuUsage={stats.cpu_usage}
          memoryUsage={stats.memory_usage}
        />
      )}

      <div>
        <h2 className="text-2xl font-semibold mb-4">Services Status</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
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
      </div>
    </div>
  )
}
