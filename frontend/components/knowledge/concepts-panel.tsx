"use client"

import { useCallback, useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useHasPermission } from "@/lib/permissions"
import { AlertCircle, Loader2, Plus, ShieldAlert, Trash2 } from "lucide-react"

type Concept = {
  name: string
  description: string | null
  parent: string | null
  pii: boolean
  terms: string[]
}

/** The vocabulary that widens a query before retrieval.
 *
 *  This shipped with an API and no screen. The answer panel already reports which
 *  concepts fired on a question, so the effect was visible while the cause was not —
 *  and nobody could correct a synonym that was pulling in the wrong documents.
 *
 *  Curation needs knowledge:write, the same permission as putting documents into a
 *  collection: deciding that two words mean the same thing is part of making that
 *  collection searchable, not an administrative act.
 */
export function ConceptsPanel() {
  const canEdit = useHasPermission("knowledge:write")
  const [rows, setRows] = useState<Concept[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [name, setName] = useState("")
  const [terms, setTerms] = useState("")
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/ai/concepts")
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      setRows((await r.json()).concepts || [])
      setErr(null)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load concepts")
    } finally {
      setLoading(false)
    }
  }, [])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  const add = async () => {
    const n = name.trim()
    if (!n || busy) return
    setBusy(true)
    try {
      const r = await fetch("/api/ai/concepts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: n,
          terms: terms.split(",").map(t => t.trim()).filter(Boolean),
        }),
      })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      setName(""); setTerms(""); await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save")
    } finally {
      setBusy(false)
    }
  }

  const remove = async (n: string) => {
    setBusy(true)
    try {
      await fetch(`/api/ai/concepts/${encodeURIComponent(n)}`, { method: "DELETE" })
      await load()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3 pt-3">
      <p className="text-xs text-muted-foreground">
        Terms listed against a concept are added to a query before retrieval, when
        Concepts is switched on in Search. A search for one term then also finds
        documents that use any of the others.
      </p>

      {err && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />{err}
        </div>
      )}

      {canEdit && (
        <div className="flex gap-2">
          <Input value={name} onChange={e => setName(e.target.value)}
                 placeholder="Concept, e.g. refund" className="h-9 max-w-[220px] text-xs" />
          <Input value={terms} onChange={e => setTerms(e.target.value)}
                 onKeyDown={e => { if (e.key === "Enter") void add() }}
                 placeholder="Terms that mean the same thing, comma separated"
                 className="h-9 flex-1 text-xs" />
          <Button size="sm" className="h-9 gap-1.5" disabled={!name.trim() || busy} onClick={() => void add()}>
            <Plus className="h-3.5 w-3.5" />Add
          </Button>
        </div>
      )}
      {!canEdit && (
        <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <ShieldAlert className="h-3 w-3" />
          Read-only. Curating concepts needs the same permission as ingesting into a
          collection.
        </p>
      )}

      {loading ? (
        <div className="flex items-center gap-1.5 py-6 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />Loading…
        </div>
      ) : rows.length === 0 ? (
        <p className="py-6 text-center text-xs text-muted-foreground">
          No concepts yet. Until one exists, switching Concepts on in Search changes nothing.
        </p>
      ) : (
        <div className="divide-y rounded-lg border">
          {rows.map(c => (
            <div key={c.name} className="flex items-start justify-between gap-3 px-3 py-2">
              <div className="min-w-0">
                <span className="text-xs font-medium">{c.name}</span>
                {c.pii && (
                  <span className="ml-1.5 rounded bg-amber-500/10 px-1 py-0.5 text-[10px] text-amber-600 dark:text-amber-400">PII</span>
                )}
                <div className="mt-0.5 flex flex-wrap gap-1">
                  {c.terms.length === 0 ? (
                    <span className="text-[11px] text-muted-foreground">
                      no terms — this concept expands nothing
                    </span>
                  ) : c.terms.map(t => (
                    <span key={t} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{t}</span>
                  ))}
                </div>
              </div>
              {canEdit && (
                <button onClick={() => void remove(c.name)} disabled={busy}
                        aria-label={`Delete ${c.name}`}
                        className="text-muted-foreground hover:text-destructive">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
