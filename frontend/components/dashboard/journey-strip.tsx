"use client"

import Link from "next/link"
import { ArrowDownToLine, Database, Sparkles, Plug, ShieldCheck } from "lucide-react"
import { useCapabilities } from "@/lib/capabilities"

type Step = {
  n: string
  title: string
  sub: string
  href: string
  icon: React.ComponentType<{ className?: string }>
  cta?: boolean
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
      sub: sourcesEnabled ? "Sources" : "Files, text & S3",
      href: sourcesEnabled ? "/connectors" : "/knowledge",
      icon: ArrowDownToLine,
    },
    {
      n: "02",
      title: "Organize",
      sub: catalogEnabled ? `${catalog} catalog` : "Knowledge collections",
      href: catalogEnabled ? "/catalog" : "/knowledge",
      icon: Database,
    },
    {
      n: "03",
      title: "Ground",
      sub: "Embed · retrieve · rerank",
      href: "/knowledge",
      icon: Sparkles,
    },
    {
      n: "04",
      title: "Connect your agent",
      sub: "Issue a key, call this deployment",
      href: "/connect",
      icon: Plug,
      cta: true,
    },
    {
      n: "05",
      title: "Govern",
      sub: "Access · PII · spend",
      href: "/governance",
      icon: ShieldCheck,
    },
  ]

  return (
    // Secondary to the activity above: no card, a muted ground, one accent colour.
    <section className="rounded-lg border border-dashed px-5 py-4">
        <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Core workflow
        </p>
        <div className="flex flex-wrap items-center gap-y-3">
          {steps.map((step, index) => (
            <div key={step.n} className="flex flex-1 items-center gap-3" style={{ minWidth: 150 }}>
              <Link
                href={step.href}
                className={
                  step.cta
                    ? "group flex items-center gap-3 rounded-lg border border-primary/40 bg-primary/5 px-2 py-1"
                    : "group flex items-center gap-3"
                }
              >
                <span
                  className="dp-num grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary/10 text-xs font-semibold text-primary transition-transform group-hover:scale-105"
                >
                  {step.n}
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-sm font-semibold group-hover:text-primary">
                    <step.icon className="h-3.5 w-3.5 text-muted-foreground" />
                    {step.title}
                  </span>
                  <span className={`block truncate text-xs text-muted-foreground${step.cta ? "" : " capitalize"}`}>{step.sub}</span>
                </span>
              </Link>
              {index < steps.length - 1 && (
                <span className="mx-1 hidden h-px flex-1 bg-gradient-to-r from-border to-transparent md:block" />
              )}
            </div>
          ))}
        </div>
    </section>
  )
}
