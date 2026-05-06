"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Activity, Database, Cpu, HardDrive, TrendingUp, TrendingDown, Minus } from "lucide-react"
import { LineChart, Line, ResponsiveContainer } from "recharts"
import { subDays } from "date-fns"

interface StatsCardsProps {
  totalServices: number
  healthyServices: number
  cpuUsage?: number
  memoryUsage?: number
}

// Generate realistic 7-day trend data
const generateTrendData = (baseValue: number, variance: number) => {
  return Array.from({ length: 7 }, (_, i) => ({
    day: i,
    value: baseValue + Math.sin(i / 2) * variance + (Math.random() - 0.5) * variance * 0.5
  }))
}

export function StatsCards({
  totalServices,
  healthyServices,
  cpuUsage,
  memoryUsage
}: StatsCardsProps) {
  const uptimePercent = totalServices > 0
    ? ((healthyServices / totalServices) * 100).toFixed(1)
    : "0"

  // Generate mock trend data for sparklines
  const serviceTrend = generateTrendData(totalServices, 2)
  const uptimeTrend = generateTrendData(Number(uptimePercent), 3)
  const cpuTrend = generateTrendData(cpuUsage || 35, 8)
  const memoryTrend = generateTrendData(memoryUsage || 55, 10)

  // Calculate trend direction
  const getTrend = (data: { value: number }[]) => {
    if (data.length < 2) return "flat"
    const first = data[0].value
    const last = data[data.length - 1].value
    const change = ((last - first) / first) * 100
    if (Math.abs(change) < 2) return "flat"
    return change > 0 ? "up" : "down"
  }

  const getTrendPercentage = (data: { value: number }[]) => {
    if (data.length < 2) return 0
    const first = data[0].value
    const last = data[data.length - 1].value
    return ((last - first) / first) * 100
  }

  const serviceTrendDir = getTrend(serviceTrend)
  const uptimeTrendDir = getTrend(uptimeTrend)
  const cpuTrendDir = getTrend(cpuTrend)
  const memoryTrendDir = getTrend(memoryTrend)

  const stats = [
    {
      title: "Total Services",
      value: totalServices,
      icon: Activity,
      description: `${healthyServices} healthy, ${totalServices - healthyServices} issues`,
      trend: serviceTrendDir,
      trendValue: getTrendPercentage(serviceTrend),
      data: serviceTrend
    },
    {
      title: "Platform Uptime",
      value: `${uptimePercent}%`,
      icon: Database,
      description: "Service availability",
      trend: uptimeTrendDir,
      trendValue: getTrendPercentage(uptimeTrend),
      data: uptimeTrend
    },
    {
      title: "CPU Usage",
      value: cpuUsage ? `${cpuUsage.toFixed(1)}%` : "–",
      icon: Cpu,
      description: "Cluster average",
      trend: cpuTrendDir,
      trendValue: getTrendPercentage(cpuTrend),
      data: cpuTrend
    },
    {
      title: "Memory Usage",
      value: memoryUsage ? `${memoryUsage.toFixed(1)}%` : "–",
      icon: HardDrive,
      description: "Cluster average",
      trend: memoryTrendDir,
      trendValue: getTrendPercentage(memoryTrend),
      data: memoryTrend
    }
  ]

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => {
        const Icon = stat.icon
        const TrendIcon = stat.trend === "up" ? TrendingUp : stat.trend === "down" ? TrendingDown : Minus

        return (
          <Card key={stat.title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                {stat.title}
              </CardTitle>
              <Icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>

            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <p className="text-xs text-muted-foreground mt-1">
                {stat.description}
              </p>
              <div className="flex items-center gap-2 mt-3">
                <div className={`flex items-center gap-0.5 text-xs font-medium ${
                  stat.trend === "up"
                    ? "text-emerald-600"
                    : stat.trend === "down"
                    ? "text-red-600"
                    : "text-slate-600"
                }`}>
                  <TrendIcon className="h-3 w-3" />
                  <span>{stat.trend !== "flat" && (stat.trend === "up" ? "+" : "")}{Math.abs(stat.trendValue).toFixed(1)}%</span>
                </div>
                <span className="text-xs text-muted-foreground">from last week</span>
              </div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
