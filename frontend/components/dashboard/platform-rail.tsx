"use client"

import Link from "next/link"
import { Check } from "lucide-react"
import { ExplainRail } from "@/components/ui/explain-rail"
import type { PlatformStatus } from "@/lib/dashboard-activity"
import type { GetStartedStep } from "@/lib/overview"

export type LakeFacts = {
  tables: number | null
  namespaces: number | null
  sources: number | null
  lastSync: string | null
  queriesToday: number | null
}

function Facts({ rows }: { rows: [string, React.ReactNode][] }) {
  if (rows.length === 0) return null
  return (
    <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="m-0 text-foreground">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

const plural = (n: number, w: string) => `${n.toLocaleString("en-US")} ${w}${n === 1 ? "" : "s"}`

/** Right of Overview: platform health, what is in the lakehouse, and the first steps
 *  (listed until each has been done once). */
export function PlatformRail({ platform, adapters, catalogs, storage, lake, collections, chunks, steps, canManage }: {
  platform: PlatformStatus | null
  adapters: string[]
  catalogs: string | null
  storage: string | null
  lake: LakeFacts | null
  collections: number | null
  chunks: number | null
  steps: GetStartedStep[]
  canManage: boolean
}) {
  const healthy = platform && platform.observed > 0 && platform.attention.length === 0
  const platformRows: [string, React.ReactNode][] = []
  if (platform) {
    platformRows.push(["Workloads", platform.observed === 0 ? "none observed"
      : platform.attention.length
        ? <span className="text-[var(--dp-warn-text)]">{platform.healthy} of {platform.observed} healthy · {platform.attention.join(", ")}</span>
        : `${platform.healthy} of ${platform.observed} healthy`])
    if (adapters.length) platformRows.push(["Adapters", `${adapters.length} configured (${adapters.join(", ")})`])
  }
  if (catalogs) platformRows.push(["Catalogs", catalogs])
  if (storage) platformRows.push(["Storage", storage])

  const lakeRows: [string, React.ReactNode][] = []
  if (lake?.tables != null) {
    lakeRows.push(["Tables", <Link key="t" href="/catalog" className="text-primary hover:underline">
      {lake.tables.toLocaleString("en-US")}{lake.namespaces != null ? ` in ${plural(lake.namespaces, "namespace")}` : ""}
    </Link>])
  }
  if (lake?.sources != null) {
    lakeRows.push(["Sources", <span key="s">
      <Link href="/connectors" className="text-primary hover:underline">{lake.sources}</Link>
      {lake.sources > 0 && (lake.lastSync
        ? ` · last sync ${new Date(lake.lastSync).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })}`
        : " · never synced")}
    </span>])
  }
  if (lake?.queriesToday != null) lakeRows.push(["Your queries", `${lake.queriesToday} today`])
  if (collections != null) lakeRows.push(["Collections", `${collections} · ${plural(chunks ?? 0, "chunk")}`])

  return (
    <ExplainRail label="Platform">
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold">Platform</h3>
          {platform && platform.observed > 0 && (
            <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${healthy ? "text-[var(--dp-good-text)]" : "text-[var(--dp-warn-text)]"}`}>
              <span className="h-2 w-2 rounded-full" style={{ background: healthy ? "var(--dp-good)" : "var(--dp-warn)" }} aria-hidden />
              {healthy ? "healthy" : "needs attention"}
            </span>
          )}
        </div>
        {platform === null && <p className="text-sm text-muted-foreground">Service status could not be read.</p>}
        <Facts rows={platformRows} />
        {canManage && <Link href="/services" className="inline-block text-sm text-primary hover:underline">Open Infrastructure</Link>}
      </section>

      {lakeRows.length > 0 && (
        <section className="space-y-2.5 border-t pt-3.5">
          <h3 className="text-base font-semibold">{lake ? "Lakehouse" : "Knowledge"}</h3>
          <Facts rows={lakeRows} />
        </section>
      )}

      {steps.length > 0 && (
        <section className="space-y-1.5 border-t pt-3.5">
          <h3 className="text-base font-semibold">Get started</h3>
          <p className="text-xs text-muted-foreground">Shown until each step has been done once.</p>
          <ul className="space-y-1 text-sm">
            {steps.map(s => (
              <li key={s.key} className="flex items-center gap-2">
                {s.done
                  ? <><Check className="h-3.5 w-3.5" style={{ color: "var(--dp-good)" }} aria-hidden /><span className="text-muted-foreground">{s.label}</span><span className="sr-only">(done)</span></>
                  : <><span className="h-3.5 w-3.5 rounded-full border" aria-hidden /><Link href={s.href} className="text-primary hover:underline">{s.label}</Link></>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </ExplainRail>
  )
}
