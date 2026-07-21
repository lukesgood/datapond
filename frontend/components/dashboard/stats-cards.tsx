"use client"

import { Card, CardContent } from "@/components/ui/card"
import { Sparkles, Boxes, HardDrive, ShieldCheck } from "lucide-react"

interface StatsCardsProps {
  collections: number | null
  vectors: number | null
  storageHuman: string | null
  storageObjects: number | null
  totalServices: number
  healthyServices: number
}

// Compact SI-ish formatting for counts: 1_200_000 → "1.2M".
function fmt(n: number | null): string {
  if (n == null) return "—"
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}K`
  return String(n)
}

export function StatsCards({
  collections, vectors, storageHuman, storageObjects, totalServices, healthyServices,
}: StatsCardsProps) {
  const uptimePct = totalServices > 0 ? Math.round((healthyServices / totalServices) * 100) : 0

  const stats = [
    {
      label: "Collections",
      dot: "var(--chart-1)",
      icon: Sparkles,
      value: fmt(collections),
      sub: "vector collections",
    },
    {
      label: "Vectors",
      dot: "var(--chart-3)",
      icon: Boxes,
      value: fmt(vectors),
      sub: "embedded chunks",
    },
    {
      label: "Storage",
      dot: "var(--chart-5)",
      icon: HardDrive,
      value: storageHuman ?? "—",
      sub: storageObjects != null ? `${storageObjects.toLocaleString()} objects · object storage` : "Object storage · Iceberg",
    },
    {
      label: "Workload health",
      dot: "var(--dp-good)",
      icon: ShieldCheck,
      value: totalServices > 0 ? `${uptimePct}%` : "—",
      sub: `${healthyServices} / ${totalServices} observed`,
    },
  ]

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((s) => {
        const Icon = s.icon
        return (
          <Card key={s.label}>
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-[11.5px] font-medium text-muted-foreground">
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: s.dot }} />
                <span>{s.label}</span>
                <Icon className="ml-auto h-3.5 w-3.5 opacity-60" />
              </div>
              <div className="dp-num mt-2 text-[27px] font-semibold leading-none tracking-tight">{s.value}</div>
              <p className="mt-1.5 text-[11.5px] text-muted-foreground">{s.sub}</p>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
