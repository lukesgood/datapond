"use client"

import { useCallback, useEffect, useState } from "react"
import { AlertCircle, Clock, Database, Loader2, RefreshCw } from "lucide-react"

type Source = { source: string; chunks: number; last_ingested: string | null; scheduled: boolean }
type Composition = {
  collection: string
  sources: Source[]
  total_chunks: number
  scheduled_source_has_no_chunks: boolean
}

/** What this collection is made of.
 *
 *  The list card could say "3 sources" and nothing in the product could say which
 *  three, how much each contributed, or when it last arrived — the first question
 *  anyone asks about a collection they did not build themselves.
 *
 *  A bar per source rather than a diagram: a collection and its sources are a flat
 *  one-to-many, and a star drawn around a centre node says nothing a sorted list with
 *  proportions does not. The relationships worth drawing are upstream of here, in
 *  Lineage.
 */
export function CompositionPanel({ name }: { name: string }) {
  const [c, setC] = useState<Composition | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    setErr(null)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}/composition`)
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      setC(await r.json())
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load")
    } finally {
      setLoading(false)
    }
  }, [name])

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
  if (!c || c.sources.length === 0) {
    return <p className="py-6 text-center text-xs text-muted-foreground">
      Nothing ingested yet.</p>
  }

  const top = Math.max(...c.sources.map(s => s.chunks), 1)

  return (
    <div className="space-y-3 pt-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {c.total_chunks} vector{c.total_chunks === 1 ? "" : "s"} from{" "}
          {c.sources.length} source{c.sources.length === 1 ? "" : "s"}
        </p>
        <button onClick={() => void load()}
                className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
          <RefreshCw className="h-3 w-3" />Refresh
        </button>
      </div>

      {c.scheduled_source_has_no_chunks && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            A refresh is scheduled, but none of the chunks here came from it. The
            Schedule tab shows it enabled either way — this is the only place that
            would tell you it has produced nothing.
          </span>
        </div>
      )}

      <div className="divide-y rounded-lg border">
        {c.sources.map(s => (
          <div key={s.source} className="relative px-3 py-2">
            <div className="absolute inset-y-0 left-0 bg-primary/5"
                 style={{ width: `${(s.chunks / top) * 100}%` }} />
            <div className="relative flex items-center justify-between gap-3">
              <span className="flex min-w-0 items-center gap-1.5">
                <Database className="h-3 w-3 shrink-0 text-muted-foreground" />
                <span className="truncate font-mono text-[11px]">{s.source}</span>
                {s.scheduled && (
                  <span className="shrink-0 rounded bg-primary/15 px-1 py-0.5 text-[10px] text-primary">
                    scheduled
                  </span>
                )}
              </span>
              <span className="flex shrink-0 items-center gap-3 text-[11px] tabular-nums text-muted-foreground">
                {s.last_ingested && (
                  <span className="flex items-center gap-0.5">
                    <Clock className="h-2.5 w-2.5" />{new Date(s.last_ingested).toLocaleDateString()}
                  </span>
                )}
                <span className="w-14 text-right font-medium text-foreground">{s.chunks}</span>
              </span>
            </div>
          </div>
        ))}
      </div>

      <p className="text-[10px] text-muted-foreground">
        A scheduled source is replaced whole on each refresh; the rest stay until
        someone removes them. That is why an old date means different things on
        different rows.
      </p>
    </div>
  )
}
