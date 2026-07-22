"use client"

import Link from "next/link"
import { Card, CardContent } from "@/components/ui/card"
import { Sparkles, Boxes, HardDrive, ShieldCheck, ArrowUpRight } from "lucide-react"

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
      href: "/knowledge",
    },
    {
      label: "Vectors",
      dot: "var(--chart-3)",
      icon: Boxes,
      value: fmt(vectors),
      sub: "embedded chunks",
      href: "/knowledge",
    },
    {
      label: "Storage",
      dot: "var(--chart-5)",
      icon: HardDrive,
      value: storageHuman ?? "—",
      sub: storageObjects != null ? `${storageObjects.toLocaleString()} objects · object storage` : "Object storage · Iceberg",
      href: "/storage",
    },
    {
      label: "Workload health",
      dot: "var(--dp-good)",
      icon: ShieldCheck,
      value: totalServices > 0 ? `${uptimePct}%` : "—",
      sub: `${healthyServices} / ${totalServices} observed`,
      href: "/services",
    },
  ]

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((s) => {
        const Icon = s.icon
        return (
          <Link
            key={s.label}
            href={s.href}
            aria-label={`${s.label}: view details`}
            className="group rounded-xl focus-visible:outline-none"
          >
            <Card className="h-full transition-colors group-hover:border-primary/40 group-hover:bg-muted/30 group-focus-visible:ring-2 group-focus-visible:ring-ring group-focus-visible:ring-offset-2">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-[11.5px] font-medium text-muted-foreground">
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: s.dot }} />
                  <span>{s.label}</span>
                  {/* Corner icon morphs to an arrow on hover to signal the card is navigable. */}
                  <span className="ml-auto relative h-3.5 w-3.5 shrink-0">
                    <Icon className="absolute inset-0 h-3.5 w-3.5 opacity-60 transition-opacity group-hover:opacity-0" />
                    <ArrowUpRight className="absolute inset-0 h-3.5 w-3.5 text-primary opacity-0 transition-opacity group-hover:opacity-100" />
                  </span>
                </div>
                <div className="dp-num mt-2 text-[27px] font-semibold leading-none tracking-tight">{s.value}</div>
                <p className="mt-1.5 text-[11.5px] text-muted-foreground">{s.sub}</p>
              </CardContent>
            </Card>
          </Link>
        )
      })}
    </div>
  )
}
