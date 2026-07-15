"use client"

// The data-foundation signature: the path data takes through the platform,
// Collect → Catalog → Query → Retrieve, each step naming the AWS service behind
// it and linking to where you work on it. A real sequence, so it's numbered.
import Link from "next/link"
import { Card, CardContent } from "@/components/ui/card"
import { ArrowDownToLine, Database, Code2, Sparkles } from "lucide-react"

type Step = {
  n: string
  title: string
  sub: string
  href: string
  icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>
  color: string
}

const STEPS: Step[] = [
  { n: "01", title: "Collect",  sub: "Connectors → S3",    href: "/connectors", icon: ArrowDownToLine, color: "var(--chart-1)" },
  { n: "02", title: "Catalog",  sub: "AWS Glue",           href: "/catalog",    icon: Database,        color: "var(--chart-3)" },
  { n: "03", title: "Query",    sub: "Amazon Athena",      href: "/query",      icon: Code2,           color: "var(--chart-2)" },
  { n: "04", title: "Retrieve", sub: "pgvector · Bedrock", href: "/knowledge",  icon: Sparkles,        color: "var(--chart-4)" },
]

export function JourneyStrip() {
  return (
    <Card>
      <CardContent className="px-5 py-4">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">
          The path your data takes
        </p>
        <div className="flex flex-wrap items-center gap-y-3">
          {STEPS.map((s, i) => (
            <div key={s.n} className="flex flex-1 items-center gap-3" style={{ minWidth: 160 }}>
              <Link href={s.href} className="group flex items-center gap-3">
                <span
                  className="dp-num grid h-8 w-8 shrink-0 place-items-center rounded-lg text-xs font-bold text-white transition-transform group-hover:scale-105"
                  style={{ background: s.color }}
                >
                  {s.n}
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-[13px] font-semibold group-hover:text-primary">
                    <s.icon className="h-3.5 w-3.5" style={{ color: s.color }} />
                    {s.title}
                  </span>
                  <span className="block truncate text-[10.5px] text-muted-foreground">{s.sub}</span>
                </span>
              </Link>
              {i < STEPS.length - 1 && (
                <span className="mx-1 hidden h-px flex-1 bg-gradient-to-r from-border to-transparent md:block" />
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
