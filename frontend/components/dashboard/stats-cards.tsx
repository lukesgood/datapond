"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Activity, Database, Cpu, HardDrive } from "lucide-react"

interface StatsCardsProps {
  totalServices: number
  healthyServices: number
  cpuUsage?: number
  memoryUsage?: number
}

export function StatsCards({
  totalServices,
  healthyServices,
  cpuUsage,
  memoryUsage
}: StatsCardsProps) {
  const stats = [
    {
      title: "Total Services",
      value: totalServices,
      icon: Activity,
      description: `${healthyServices} healthy`,
      color: "text-blue-500"
    },
    {
      title: "Healthy Services",
      value: healthyServices,
      icon: Database,
      description: `${((healthyServices / totalServices) * 100).toFixed(0)}% uptime`,
      color: "text-green-500"
    },
    {
      title: "CPU Usage",
      value: cpuUsage ? `${cpuUsage.toFixed(1)}%` : "N/A",
      icon: Cpu,
      description: "Average across nodes",
      color: "text-orange-500"
    },
    {
      title: "Memory Usage",
      value: memoryUsage ? `${memoryUsage.toFixed(1)}%` : "N/A",
      icon: HardDrive,
      description: "Average across nodes",
      color: "text-purple-500"
    }
  ]

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => {
        const Icon = stat.icon
        return (
          <Card key={stat.title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">{stat.title}</CardTitle>
              <Icon className={`h-4 w-4 ${stat.color}`} />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <p className="text-xs text-muted-foreground">{stat.description}</p>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
