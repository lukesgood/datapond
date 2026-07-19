"use client"

import Link from "next/link"
import { Card, CardContent } from "@/components/ui/card"
import { ArrowDownToLine, Database, Sparkles, Bot, ShieldCheck } from "lucide-react"
import { useCapabilities } from "@/lib/capabilities"

type Step = {
  n: string
  title: string
  sub: string
  href: string
  icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>
  color: string
}

export function JourneyStrip() {
  const caps = useCapabilities()
  const sourcesEnabled = caps.connectors === true
  const catalogEnabled = caps.catalog === true
  const catalog = typeof caps.catalog_backend === "string" && caps.catalog_backend !== "none"
    ? caps.catalog_backend
    : "collections"

  const steps: Step[] = [
    {
      n: "01",
      title: "Connect",
      sub: sourcesEnabled ? "Sources & sync" : "Files, text & S3",
      href: sourcesEnabled ? "/connectors" : "/knowledge",
      icon: ArrowDownToLine,
      color: "var(--chart-1)",
    },
    {
      n: "02",
      title: "Organize",
      sub: catalogEnabled ? `${catalog} catalog` : "Knowledge collections",
      href: catalogEnabled ? "/catalog" : "/knowledge",
      icon: Database,
      color: "var(--chart-3)",
    },
    {
      n: "03",
      title: "Ground",
      sub: "Embed · retrieve · rerank",
      href: "/knowledge",
      icon: Sparkles,
      color: "var(--chart-4)",
    },
    {
      n: "04",
      title: "Serve",
      sub: "LiteLLM model gateway",
      href: "/ai",
      icon: Bot,
      color: "var(--chart-2)",
    },
    {
      n: "05",
      title: "Govern",
      sub: "Access · PII · spend",
      href: "/governance",
      icon: ShieldCheck,
      color: "var(--chart-5)",
    },
  ]

  return (
    <Card>
      <CardContent className="px-5 py-4">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">
          Portable core workflow
        </p>
        <div className="flex flex-wrap items-center gap-y-3">
          {steps.map((step, index) => (
            <div key={step.n} className="flex flex-1 items-center gap-3" style={{ minWidth: 150 }}>
              <Link href={step.href} className="group flex items-center gap-3">
                <span
                  className="dp-num grid h-8 w-8 shrink-0 place-items-center rounded-lg text-xs font-bold text-white transition-transform group-hover:scale-105"
                  style={{ background: step.color }}
                >
                  {step.n}
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-[13px] font-semibold group-hover:text-primary">
                    <step.icon className="h-3.5 w-3.5" style={{ color: step.color }} />
                    {step.title}
                  </span>
                  <span className="block truncate text-[10.5px] capitalize text-muted-foreground">{step.sub}</span>
                </span>
              </Link>
              {index < steps.length - 1 && (
                <span className="mx-1 hidden h-px flex-1 bg-gradient-to-r from-border to-transparent md:block" />
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
