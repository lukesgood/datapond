"use client"

import { useCallback, useEffect, useState } from "react"
import { AlertCircle, ArrowRight, Database, Loader2, PlugZap, Sparkles } from "lucide-react"

type Node = { id: string; kind: "connector" | "table" | "collection"; label: string; type?: string; status?: string }
type Edge = { source: string; target: string; active: boolean }
type Graph = { nodes: Node[]; edges: Edge[] }

const ICON = { connector: PlugZap, table: Database, collection: Sparkles }

/** What feeds each collection.
 *
 *  This dependency already runs: when a connector sync finishes,
 *  _invalidate_sink_collections marks any collection whose scheduled source names
 *  that table stale, and the re-embedding scheduler picks it up. It fires in
 *  production and appeared nowhere, so "this table changed — which collections are
 *  now wrong?" had no answer for the person who needed one.
 *
 *  Drawn as chains rather than a force-directed graph. The shape is genuinely a set
 *  of short paths (connector → table → collection), and a layout that pushes nodes
 *  around to avoid overlap makes three-hop paths harder to read, not easier.
 */
export function LineagePanel() {
  const [g, setG] = useState<Graph | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/ai/lineage")
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      setG(await r.json())
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load lineage")
    } finally {
      setLoading(false)
    }
  }, [])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  if (loading) {
    return <div className="flex items-center gap-1.5 py-6 text-xs text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />Loading…</div>
  }
  if (err) {
    return <div className="mt-3 flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
      <AlertCircle className="h-3.5 w-3.5 shrink-0" />{err}</div>
  }
  if (!g || g.nodes.length === 0) {
    return <p className="py-6 text-center text-xs text-muted-foreground">No collections yet.</p>
  }

  const byId = new Map(g.nodes.map(n => [n.id, n]))
  const collections = g.nodes.filter(n => n.kind === "collection")

  // One row per collection, walking backwards to what feeds it. Backwards because
  // the question is asked from the collection's end: "where did this come from?"
  const chains = collections.map(c => {
    const up = g.edges.filter(e => e.target === c.id)
    return { collection: c, feeds: up.map(e => {
      const table = byId.get(e.source)
      const conns = g.edges.filter(x => x.target === e.source).map(x => byId.get(x.source))
      return { table, conns: conns.filter(Boolean) as Node[], active: e.active }
    }) }
  })

  return (
    <div className="space-y-3 pt-3">
      <p className="text-xs text-muted-foreground">
        A collection with an upstream is re-embedded automatically when that table is
        synced. One with none was ingested by hand and nothing will change it.
      </p>
      <div className="divide-y rounded-lg border">
        {chains.map(({ collection, feeds }) => (
          <div key={collection.id} className="px-3 py-2.5">
            {feeds.length === 0 ? (
              <div className="flex items-center gap-2 text-xs">
                <Chip node={collection} />
                <span className="text-[11px] text-muted-foreground">
                  no upstream — ingested directly
                </span>
              </div>
            ) : feeds.map((f, i) => (
              <div key={i} className="flex flex-wrap items-center gap-1.5 py-0.5 text-xs">
                {f.conns.map(c => (
                  <span key={c.id} className="flex items-center gap-1.5">
                    <Chip node={c} />
                    <ArrowRight className="h-3 w-3 text-muted-foreground" />
                  </span>
                ))}
                {f.table && <><Chip node={f.table} /><ArrowRight className="h-3 w-3 text-muted-foreground" /></>}
                <Chip node={collection} />
                {!f.active && (
                  <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-700 dark:text-amber-400">
                    refresh paused
                  </span>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

function Chip({ node }: { node: Node }) {
  const Icon = ICON[node.kind]
  const failed = node.status === "failed"
  return (
    <span className={`flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] ${
      failed ? "border-destructive/50 bg-destructive/5 text-destructive" : "bg-background"}`}>
      <Icon className="h-3 w-3 text-muted-foreground" />
      <span className="font-mono">{node.label}</span>
      {failed && <span className="text-[10px]">last sync failed</span>}
    </span>
  )
}
