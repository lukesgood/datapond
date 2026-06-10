"use client"

// Data-journey entry strip for the dashboard — turns the first screen from a
// pure infra-health view into the starting point of the data workflow:
// Ingestion → Catalog → Knowledge → Dashboards, each with a live count + link.
import { useEffect, useState } from "react"
import Link from "next/link"
import { Card, CardContent } from "@/components/ui/card"
import { ArrowDownToLine, Database, Sparkles, BarChart3, ArrowRight } from "lucide-react"

type Step = {
  title: string
  href: string
  icon: React.ComponentType<{ className?: string }>
  count: number | null   // null = loading/unavailable
  unit: string
  hint: string
}

export function JourneyStrip() {
  const [counts, setCounts] = useState<(number | null)[]>([null, null, null, null])

  useEffect(() => {
    const load = async () => {
      const results = await Promise.allSettled([
        fetch("/api/connectors/connections").then(r => r.json()),
        fetch("/api/catalog/schemas?columns=false").then(r => r.json()),
        fetch("/api/ai/collections").then(r => r.json()),
        fetch("/api/dashboards").then(r => r.json()),
      ])
      const num = (i: number, fn: (d: any) => number) =>
        results[i].status === "fulfilled" ? fn((results[i] as PromiseFulfilledResult<any>).value) : null
      setCounts([
        num(0, d => (Array.isArray(d) ? d.length : d.connections?.length ?? 0)),
        num(1, d => (d.catalogs ?? []).flatMap((c: any) => c.schemas ?? [])
                      .reduce((acc: number, s: any) => acc + (s.tables?.length ?? 0), 0)),
        num(2, d => d.collections?.length ?? 0),
        num(3, d => (Array.isArray(d) ? d.length : d.total ?? d.items?.length ?? 0)),
      ])
    }
    load()
  }, [])

  const steps: Step[] = [
    { title: "Ingestion",  href: "/connectors", icon: ArrowDownToLine, count: counts[0], unit: "connectors",  hint: "데이터 소스 연결" },
    { title: "Catalog",    href: "/catalog",    icon: Database,        count: counts[1], unit: "tables",      hint: "Iceberg 테이블" },
    { title: "Knowledge",  href: "/knowledge",  icon: Sparkles,        count: counts[2], unit: "collections", hint: "RAG 벡터스토어" },
    { title: "Dashboards", href: "/dashboards", icon: BarChart3,       count: counts[3], unit: "dashboards",  hint: "쿼리 시각화" },
  ]

  return (
    <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
      {steps.map((s, i) => (
        <Link key={s.title} href={s.href} className="group">
          <Card className="transition hover:border-primary/40 hover:shadow-sm">
            <CardContent className="py-3 px-4 flex items-center gap-3">
              <s.icon className="h-5 w-5 text-muted-foreground shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium flex items-center gap-1">
                  {s.title}
                  {i < steps.length - 1 && <ArrowRight className="h-3 w-3 opacity-30 hidden lg:inline" />}
                </p>
                <p className="text-[11px] text-muted-foreground truncate">
                  {s.count === null ? "…" : `${s.count} ${s.unit}`} · {s.hint}
                </p>
              </div>
              <ArrowRight className="h-3.5 w-3.5 opacity-0 group-hover:opacity-60 transition shrink-0" />
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  )
}
