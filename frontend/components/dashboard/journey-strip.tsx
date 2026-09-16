"use client"

import Link from "next/link"
import { ArrowDownToLine, Database, Sparkles, Plug, ShieldCheck } from "lucide-react"
import { useCapabilities } from "@/lib/capabilities"
import { coreWorkflowSteps } from "@/lib/core-workflow"

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  "01": ArrowDownToLine, "02": Database, "03": Sparkles, "04": Plug, "05": ShieldCheck,
}

export function JourneyStrip() {
  const caps = useCapabilities()
  const steps = coreWorkflowSteps({
    sourcesEnabled: caps.connectors === true,
    catalogEnabled: caps.catalog === true,
    catalogBackend: typeof caps.catalog_backend === "string" && caps.catalog_backend !== "none"
      ? caps.catalog_backend
      : "collections",
  })

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
                    {(() => { const Icon = ICONS[step.n]; return <Icon className="h-3.5 w-3.5 text-muted-foreground" /> })()}
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
