"use client"

import { useCallback, useEffect, useState } from "react"
import { AlertCircle, Clock, Database, Loader2, RefreshCw, Trash2 } from "lucide-react"
import { useConfirm } from "@/lib/confirm"
import { useHasPermission } from "@/lib/permissions"

type Source = { source: string; chunks: number; last_ingested: string | null; scheduled: boolean }
type Composition = {
  collection: string
  description?: string | null
  chunk_preset?: string | null
  chunk_size?: number | null
  chunk_overlap?: number | null
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
export function CompositionPanel({ name, onChange }: { name: string; onChange?: () => void }) {
  const canEdit = useHasPermission("knowledge:write")
  const confirm = useConfirm()
  const [c, setC] = useState<Composition | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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

  const saveDescription = async (value: string) => {
    setBusy(true)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: value }),
      })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      await load(); onChange?.()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save")
    } finally {
      setBusy(false)
    }
  }

  const removeSource = async (source: string, chunks: number) => {
    const ok = await confirm({
      title: "Remove this source",
      message: `Deletes ${chunks} chunk${chunks === 1 ? "" : "s"} that came from "${source}". The rest of the collection is untouched. This cannot be undone.`,
      destructive: true, confirmText: "Remove",
    })
    if (!ok) return
    setBusy(true)
    try {
      const r = await fetch(
        `/api/ai/collections/${encodeURIComponent(name)}/sources?source=${encodeURIComponent(source)}`,
        { method: "DELETE" })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      await load(); onChange?.()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not remove")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3 pt-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {c.total_chunks} vector{c.total_chunks === 1 ? "" : "s"} from{" "}
          {c.sources.length} source{c.sources.length === 1 ? "" : "s"}
          {c.chunk_size ? (
            <> · split at <span className="dp-num">{c.chunk_size}</span>
              /<span className="dp-num">{c.chunk_overlap}</span>
              {c.chunk_preset ? ` (${c.chunk_preset})` : null}</>
          ) : null}
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
                {canEdit && (
                  <button onClick={() => void removeSource(s.source, s.chunks)} disabled={busy}
                          aria-label={`Remove ${s.source}`}
                          title={s.scheduled
                            ? "Removing a scheduled source only clears it until the next refresh puts it back"
                            : `Remove the ${s.chunks} chunk(s) from ${s.source}`}
                          className="text-muted-foreground hover:text-destructive disabled:opacity-40">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </span>
            </div>
          </div>
        ))}
      </div>

      {canEdit && <DescriptionField value={c.description ?? ""} busy={busy} onSave={saveDescription} />}

      <p className="text-[10px] text-muted-foreground">
        A scheduled source is replaced whole on each refresh; the rest stay until
        someone removes them. That is why an old date means different things on
        different rows.
      </p>
    </div>
  )
}


/** Describing what a collection holds is the thing most likely to be wrong later —
 *  it is written before anything is ingested. Editing it needed a delete-and-recreate
 *  before this, which loses every chunk to fix a sentence. */
function DescriptionField({ value, busy, onSave }: {
  value: string; busy: boolean; onSave: (v: string) => void
}) {
  const [draft, setDraft] = useState(value)
  const dirty = draft.trim() !== value.trim()
  return (
    <div className="flex items-center gap-2">
      <input value={draft} onChange={e => setDraft(e.target.value)}
             placeholder="What this collection holds…"
             className="h-8 flex-1 rounded-md border bg-background px-2 text-xs" />
      <button onClick={() => onSave(draft.trim())} disabled={!dirty || busy}
              className="shrink-0 rounded-md border px-2 py-1 text-[11px] disabled:opacity-40 hover:bg-muted/40">
        Save
      </button>
    </div>
  )
}
