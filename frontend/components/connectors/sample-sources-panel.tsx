"use client"

import { useEffect, useState } from "react"
import { Checkbox } from "@/components/ui/checkbox"
import { CheckCircle2, AlertCircle, MinusCircle, Loader2, Sparkles } from "lucide-react"

// One sample per connector kind the deployment can serve to itself — see
// backend/app/sample_sources.py. The list comes from the API so the two cannot drift.
interface SampleSource {
  kind: string
  name: string
  connector_type: string
  description: string
  tables: string[]
  connection_id: string | null
}

interface JoinExample {
  question: string
  tables: string
}

interface SampleResult {
  kind: string
  name: string
  status: string
  action?: string
  detail?: string
  test?: { success: boolean; message: string }
}

const TYPE_ICON: Record<string, string> = {
  postgresql: "🐘",
  s3: "🪣",
  rest_api: "🌐",
  custom: "🐍",
  database_url: "🔗",
}

export function SampleSourcesPanel({ onAdded }: { onAdded?: () => void }) {
  const [sources, setSources] = useState<SampleSource[]>([])
  const [examples, setExamples] = useState<JoinExample[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [loadError, setLoadError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [results, setResults] = useState<SampleResult[] | null>(null)

  const load = async () => {
    try {
      const res = await fetch("/api/connectors/sample-sources")
      const d = await res.json()
      if (!res.ok) throw new Error(d.detail ?? `Failed (${res.status})`)
      const list: SampleSource[] = d.sources ?? []
      setSources(list)
      setExamples(d.join_examples ?? [])
      setSelected(prev => prev.size > 0 ? prev
        : new Set(list.filter(s => !s.connection_id).map(s => s.kind)))
      setLoadError(null)
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load sample sources")
    }
  }

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(initial)
  }, [])

  const toggle = (kind: string, on: boolean) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (on) next.add(kind)
      else next.delete(kind)
      return next
    })
  }

  const handleAdd = async () => {
    setAdding(true)
    setResults(null)
    try {
      const res = await fetch("/api/connectors/sample-sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kinds: Array.from(selected) }),
      })
      const d = await res.json()
      if (!res.ok) throw new Error(d.detail ?? `Failed (${res.status})`)
      setResults(d.results ?? [])
      setSelected(new Set())
      await load()
      onAdded?.()
    } catch (e) {
      setResults([{ kind: "request", name: "Request", status: "failed",
                    detail: e instanceof Error ? e.message : "Failed" }])
    } finally {
      setAdding(false)
    }
  }

  if (loadError) {
    return <p className="text-xs text-center text-destructive">{loadError}</p>
  }

  return (
    <div className="w-full max-w-2xl space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        {sources.map(s => {
          const checked = selected.has(s.kind)
          return (
            <label key={s.kind}
              className={`flex gap-3 rounded-lg border p-3 text-left cursor-pointer transition-colors ${
                checked ? "border-primary/50 bg-primary/5" : "hover:bg-muted/40"}`}>
              <Checkbox
                aria-label={`Add ${s.name}`}
                checked={checked}
                disabled={adding}
                onCheckedChange={(c) => toggle(s.kind, !!c)}
                className="mt-0.5"
              />
              <div className="min-w-0 space-y-1">
                <div className="flex items-center gap-1.5 text-sm font-medium">
                  <span aria-hidden>{TYPE_ICON[s.connector_type] ?? "🔌"}</span>
                  <span className="truncate">{s.name}</span>
                  {s.connection_id && (
                    <span className="shrink-0 rounded-full border px-1.5 text-2xs text-muted-foreground">
                      added
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{s.description}</p>
                <p className="text-2xs font-mono text-muted-foreground/80 truncate">
                  {s.tables.join(" · ")}
                </p>
              </div>
            </label>
          )
        })}
      </div>

      <div className="flex flex-col items-center gap-2">
        <button
          onClick={handleAdd}
          disabled={adding || selected.size === 0}
          className="flex items-center gap-2 px-6 py-3 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors shadow-sm disabled:opacity-60 min-w-56 justify-center"
        >
          {adding
            ? <><Loader2 className="h-4 w-4 animate-spin" />Setting up…</>
            : <><Sparkles className="h-4 w-4" />
                {selected.size === 0 ? "Select sample sources"
                  : `Add ${selected.size} sample source${selected.size > 1 ? "s" : ""}`}</>}
        </button>
        {!results && !adding && (
          <p className="text-xs text-muted-foreground text-center max-w-md">
            Already-added samples are refreshed in place. Adding does not sync — run Sync on
            each source to land its tables in the catalog.
          </p>
        )}
      </div>

      {results && (
        <ul className="space-y-1.5 rounded-lg border bg-muted/20 p-3 text-xs">
          {results.map(r => {
            const failed = r.status === "failed" || r.status === "error"
            const skipped = r.status === "skipped"
            const Icon = failed ? AlertCircle : skipped ? MinusCircle : CheckCircle2
            const tone = failed ? "text-destructive"
              : skipped ? "text-muted-foreground" : "text-[var(--dp-good-text)]"
            const note = r.detail ?? (r.test && !r.test.success ? r.test.message : null)
            return (
              <li key={r.kind} className="flex gap-2">
                <Icon className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${tone}`} />
                <span>
                  <span className="font-medium">{r.name}</span>{" "}
                  <span className="text-muted-foreground">— {r.action ?? r.status}</span>
                  {note && <span className="block text-muted-foreground break-words">{note}</span>}
                </span>
              </li>
            )
          })}
        </ul>
      )}

      {examples.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer text-center">What the samples join on</summary>
          <ul className="mt-2 space-y-1">
            {examples.map(e => (
              <li key={e.question}>
                <span className="text-foreground">{e.question}</span>
                <span className="block font-mono text-2xs">{e.tables}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
