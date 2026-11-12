"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { useCapabilities } from "@/lib/capabilities"
import { startOfLocalDay } from "@/lib/dashboard-activity"
import { lakeCatalogCount, lastSyncAt, queriesSince, staleSourceCount } from "@/lib/lakehouse-summary"

async function getJson(url: string): Promise<unknown> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

interface Summary {
  catalogs: number | null
  tables: number | null
  sources: number | null
  stale: number | null
  lastSync: string | null
  queries: number | null
}

/** A compact Lakehouse row above the AI activity: what is in the lake, how fresh its
 *  sources are, and today's queries. Each part shows only when its capability is true. */
export function LakehouseRow() {
  const caps = useCapabilities()
  const hasCatalog = caps.catalog === true
  const hasSources = caps.connectors === true
  const hasQuery = caps.query === true
  const [s, setS] = useState<Summary | null>(null)

  useEffect(() => {
    if (!hasCatalog && !hasSources && !hasQuery) return
    let live = true
    void (async () => {
      const ok = async <T,>(want: boolean, url: string, pick: (d: unknown) => T): Promise<T | null> => {
        if (!want) return null
        try { return pick(await getJson(url)) } catch { return null }
      }
      const arr = (d: unknown, key: string) => {
        const v = d && typeof d === "object" ? (d as Record<string, unknown>)[key] : undefined
        return Array.isArray(v) ? v : []
      }
      const [catalogs, tables, conns, history] = await Promise.all([
        ok(hasCatalog, "/api/catalogs", d => lakeCatalogCount(arr(d, "catalogs") as { kind: string; enabled: boolean }[])),
        ok(hasCatalog, "/api/catalog/tables", d => arr(d, "tables").length),
        ok(hasSources, "/api/connectors/connections", d => (Array.isArray(d) ? d : []) as { last_sync_at: string | null }[]),
        ok(hasQuery, "/api/queries/history?limit=200", d =>
          queriesSince(arr(d, "items") as { created_at?: string }[], startOfLocalDay(new Date()))),
      ])
      if (!live) return
      setS({
        catalogs, tables,
        sources: conns ? conns.length : null,
        stale: conns ? staleSourceCount(conns, Date.now()) : null,
        lastSync: conns ? lastSyncAt(conns) : null,
        queries: history,
      })
    })()
    return () => { live = false }
  }, [hasCatalog, hasSources, hasQuery])

  if (!hasCatalog && !hasSources && !hasQuery) return null
  if (!s) return null

  const facts: { key: string; node: React.ReactNode }[] = []
  if (hasCatalog) {
    facts.push({ key: "lake", node: (
      <Link href="/catalog" className="hover:underline">
        <span className="font-medium text-foreground tabular-nums">{s.catalogs ?? "—"}</span> lake catalog{s.catalogs === 1 ? "" : "s"}
        {" · "}<span className="font-medium text-foreground tabular-nums">{s.tables?.toLocaleString("en-US") ?? "—"}</span> table{s.tables === 1 ? "" : "s"}
      </Link>) })
  }
  if (hasSources) {
    facts.push({ key: "src", node: (
      <Link href="/connectors" className="hover:underline">
        <span className="font-medium text-foreground tabular-nums">{s.sources ?? "—"}</span> source{s.sources === 1 ? "" : "s"}
        {s.sources != null && s.sources > 0 && (
          <>
            {" · "}{s.lastSync ? `last sync ${new Date(s.lastSync).toLocaleString()}` : "never synced"}
            {s.stale ? <span className="font-medium text-[var(--dp-warn-text)]">{` · ${s.stale} stale`}</span> : null}
          </>
        )}
      </Link>) })
  }
  if (hasQuery) {
    facts.push({ key: "q", node: (
      <Link href="/query" className="hover:underline">
        <span className="font-medium text-foreground tabular-nums">{s.queries ?? "—"}</span> of your queries today
      </Link>) })
  }

  return (
    <section aria-label="Lakehouse" className="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-lg border px-4 py-3 text-sm text-muted-foreground">
      <span className="text-xs font-semibold uppercase tracking-widest text-primary">Lakehouse</span>
      {facts.map(f => <span key={f.key}>{f.node}</span>)}
    </section>
  )
}
