"use client"

import { Card, CardContent } from "@/components/ui/card"
import { Activity, ShieldCheck, Cpu, HardDrive } from "lucide-react"

interface StatsCardsProps {
  totalServices: number
  healthyServices: number
  cpuUsage?: number
  memoryUsage?: number
}

// A thin honest usage bar (0–100%) — real current value, not a fabricated trend.
function UsageBar({ pct }: { pct: number }) {
  const clamped = Math.max(0, Math.min(100, pct))
  return (
    <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-muted">
      <div className="dp-gradient h-full rounded-full transition-[width]" style={{ width: `${clamped}%` }} />
    </div>
  )
}

export function StatsCards({ totalServices, healthyServices, cpuUsage, memoryUsage }: StatsCardsProps) {
  const uptimePercent = totalServices > 0 ? (healthyServices / totalServices) * 100 : 0
  const issues = totalServices - healthyServices

  const stats = [
    {
      title: "Services",
      value: String(totalServices),
      icon: Activity,
      description: issues > 0 ? `${healthyServices} healthy · ${issues} need attention` : "All healthy",
      bar: undefined as number | undefined,
    },
    {
      title: "Availability",
      value: `${uptimePercent.toFixed(0)}%`,
      icon: ShieldCheck,
      description: `${healthyServices} of ${totalServices} operational`,
      bar: undefined,
    },
    {
      title: "CPU",
      value: cpuUsage != null ? `${cpuUsage.toFixed(0)}%` : "—",
      icon: Cpu,
      description: "Cluster average",
      bar: cpuUsage,
    },
    {
      title: "Memory",
      value: memoryUsage != null ? `${memoryUsage.toFixed(0)}%` : "—",
      icon: HardDrive,
      description: "Cluster average",
      bar: memoryUsage,
    },
  ]

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => {
        const Icon = stat.icon
        return (
          <Card key={stat.title}>
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <Icon className="h-3.5 w-3.5" />
                <span className="uppercase tracking-wide">{stat.title}</span>
              </div>
              <div className="dp-num mt-2 text-3xl font-semibold tracking-tight tabular-nums">{stat.value}</div>
              <p className="mt-0.5 text-xs text-muted-foreground">{stat.description}</p>
              {stat.bar != null && <UsageBar pct={stat.bar} />}
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
