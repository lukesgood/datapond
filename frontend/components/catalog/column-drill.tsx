"use client"

import { useCallback, useEffect, useState } from "react"
import NextLink from "next/link"
import { Loader2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  bindingBody, conditionFor, joinPartners, meaningOf, newConceptProblem, parentSuggestion, share, valuesUrl,
  type ColumnValues,
} from "@/lib/column-drill"
import type { Binding, Concept, ConceptViewer } from "@/lib/concepts"
import { displayId, tableHref } from "@/lib/relationship-view"
import type { TableKeys } from "@/lib/table-profile"

type ConceptsDoc = { concepts: Concept[]; bindings: Binding[]; viewer?: ConceptViewer }

async function detail(r: Response): Promise<string> {
  const d = await r.json().catch(() => null)
  const msg = d?.detail
  return typeof msg === "string" ? msg : msg?.message ?? `HTTP ${r.status}`
}

/** One column drilled into: its top values by rows (read as you, through the governed
 *  query path), what it means (segments on it, its concepts), what it joins to, and two
 *  ways to give it meaning from here. */
export function ColumnDrill({ tableId, column, onClose, sole = null }: {
  tableId: string; column: string; onClose: () => void; sole?: string | null
}) {
  const [values, setValues] = useState<ColumnValues | null>(null)
  const [valuesError, setValuesError] = useState<string | null>(null)
  const [doc, setDoc] = useState<ConceptsDoc | null>(null)
  const [keys, setKeys] = useState<TableKeys | null>(null)
  const [making, setMaking] = useState<string | null>(null)       // value a segment form is open for
  const [binding, setBinding] = useState(false)
  const [done, setDone] = useState<string | null>(null)

  const loadConcepts = useCallback(() => {
    fetch("/api/semantic/concepts").then(r => (r.ok ? r.json() : null)).then(d => setDoc(d)).catch(() => setDoc(null))
  }, [])

  useEffect(() => {
    let cancelled = false
    const [catalog, namespace, ...rest] = tableId.split(".")
    const t = window.setTimeout(() => {
      setValues(null); setValuesError(null); setMaking(null); setBinding(false); setDone(null)
      fetch(valuesUrl(tableId, column))
        .then(async r => { if (!r.ok) throw new Error(await detail(r)); return r.json() })
        .then((v: ColumnValues) => { if (!cancelled) setValues(v) })
        .catch(e => { if (!cancelled) setValuesError(e instanceof Error ? e.message : "The values could not be read.") })
      fetch(`/api/catalog/tables/${encodeURIComponent(namespace)}/${encodeURIComponent(rest.join("."))}/keys?catalog=${encodeURIComponent(catalog)}`)
        .then(r => (r.ok ? r.json() : null)).then(k => { if (!cancelled) setKeys(k) }).catch(() => {})
      loadConcepts()
    }, 0)
    return () => { cancelled = true; window.clearTimeout(t) }
  }, [tableId, column, loadConcepts])

  const bindings = doc?.bindings ?? []
  const concepts = doc?.concepts ?? []
  const canBind = !!(doc?.viewer?.can_approve || doc?.viewer?.can_propose)
  const meaning = meaningOf(bindings, tableId, column)
  const partners = joinPartners(keys, column)
  const max = Math.max(1, ...(values?.values ?? []).map(v => v.rows))
  const short = displayId(tableId, sole)

  return (
    <section aria-label={`Column ${short}.${column}`} className="space-y-3 rounded-md border bg-card p-4 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono font-semibold">{short}.{column}</p>
          {values && (
            <p className="text-xs text-muted-foreground">
              {values.type} · {share(values.nulls, values.rows)} empty
              {values.distinct != null && ` · ${values.distinct.toLocaleString("en-US")} value${values.distinct === 1 ? "" : "s"}`}
              {` · ${values.rows.toLocaleString("en-US")} rows`}
              {values.restricted && " you may see"}
            </p>
          )}
        </div>
        <button type="button" onClick={onClose} aria-label="Close column" className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>

      {valuesError ? <p role="alert" className="text-xs text-destructive">{valuesError}</p>
        : !values ? <p className="flex items-center text-xs text-muted-foreground"><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />Reading values…</p>
        : values.hidden ? <p className="text-xs text-muted-foreground">{values.reason}</p>
        : values.values.length === 0 ? <p className="text-xs text-muted-foreground">No rows.</p>
        : (
          <div>
            <p className="mb-1 text-2xs text-muted-foreground">Top {values.values.length} values by rows, read as you (grants, row policies and masks apply).</p>
            <ul className="space-y-1">
              {values.values.map(v => {
                const label = v.value ?? "(empty)"
                return (
                  <li key={label}>
                    <div className="flex items-center gap-2">
                      <span className="w-36 shrink-0 truncate font-mono text-xs" title={label}>{label}</span>
                      <span className="relative h-3 min-w-0 flex-1 rounded-sm bg-muted" aria-hidden>
                        <span className="absolute inset-y-0 left-0 rounded-sm bg-primary/70" style={{ width: `${(v.rows / max) * 100}%` }} />
                      </span>
                      <span className="w-24 shrink-0 text-right text-xs tabular-nums">{v.rows.toLocaleString("en-US")} <span className="text-muted-foreground">{share(v.rows, values.rows)}</span></span>
                      {canBind && v.value != null && (
                        <button type="button" onClick={() => { setMaking(making === v.value ? null : v.value); setDone(null) }}
                                className="w-20 shrink-0 text-right text-2xs text-primary hover:underline">Segment…</button>
                      )}
                    </div>
                    {making === v.value && v.value != null && (
                      <SegmentForm tableId={tableId} column={column} value={v.value} type={values.type} rows={v.rows}
                                   concepts={concepts} parent={parentSuggestion(bindings, tableId)}
                                   onDone={msg => { setMaking(null); setDone(msg); loadConcepts() }} />
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )}

      {done && <p role="status" className="rounded bg-muted px-2 py-1 text-xs">{done}</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="text-xs font-medium">Means</p>
          {meaning.segments.length === 0 && meaning.concepts.length === 0
            ? <p className="text-xs text-muted-foreground">No concept or segment uses this column yet.</p>
            : (
              <ul className="space-y-0.5 text-xs">
                {meaning.concepts.map((c, i) => <li key={`${c.concept}|${c.role}|${i}`}><span className="font-medium">{c.concept}</span> <span className="text-muted-foreground">({c.role})</span></li>)}
                {meaning.segments.map((s, i) => <li key={`${s.concept}|${s.filter_sql}|${i}`}><span className="font-medium">{s.concept}</span> <span className="text-muted-foreground">=</span> <code className="text-2xs">{s.filter_sql}</code></li>)}
              </ul>
            )}
          {canBind && !binding && (
            <button type="button" onClick={() => { setBinding(true); setDone(null) }} className="mt-1 text-2xs text-primary hover:underline">Bind column to a concept…</button>
          )}
          {binding && (
            <BindForm tableId={tableId} column={column} concepts={concepts}
                      onCancel={() => setBinding(false)} onDone={msg => { setBinding(false); setDone(msg); loadConcepts() }} />
          )}
        </div>
        <div>
          <p className="text-xs font-medium">Joins</p>
          {partners.length === 0
            ? <p className="text-xs text-muted-foreground">No key declared on this column in the source.</p>
            : (
              <ul className="space-y-0.5 text-xs">
                {partners.map(p => (
                  <li key={p.table + p.column + p.direction}>
                    <span className="text-muted-foreground">{p.direction} </span>
                    <NextLink href={tableHref(p.table)} className="font-mono text-primary hover:underline">{displayId(p.table, sole)}.{p.column}</NextLink>
                  </li>
                ))}
              </ul>
            )}
        </div>
      </div>
    </section>
  )
}

function SegmentForm({ tableId, column, value, type, rows, concepts, parent, onDone }: {
  tableId: string; column: string; value: string; type: string; rows: number
  concepts: Concept[]; parent: string | null; onDone: (msg: string) => void
}) {
  const [mode, setMode] = useState<"new" | "existing">("new")
  const [name, setName] = useState("")
  const [existing, setExisting] = useState("")
  const [under, setUnder] = useState(parent ?? "")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cond = conditionFor(column, value, type)
  const problem = mode === "new" ? newConceptProblem(name, concepts) : existing ? null : "Pick a concept."

  const save = async () => {
    if (problem) { setError(problem); return }
    setBusy(true); setError(null)
    try {
      const concept = mode === "new" ? name.trim() : existing
      if (mode === "new") {
        const r = await fetch("/api/ai/concepts", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: concept, parent: under || null, description: `Rows where ${cond}.` }) })
        if (!r.ok) throw new Error(`The concept could not be created: ${await detail(r)}`)
      }
      const r = await fetch("/api/semantic/concepts/bindings", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bindingBody(tableId, column, concept, "filter", cond, `from the Data map: ${rows} rows`)) })
      if (!r.ok) throw new Error(await detail(r))
      const out = await r.json()
      onDone(out.status === "proposed" ? `Proposed: ${concept} = ${cond}. An administrator approves it.` : `Saved: ${concept} = ${cond}.`)
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save the segment.") } finally { setBusy(false) }
  }

  return (
    <div className="ml-[9.5rem] mt-1 space-y-2 rounded-md border bg-muted/30 p-2 text-xs">
      <p>Rows where <code className="text-2xs">{cond}</code> become a segment.</p>
      <div className="flex gap-3" role="radiogroup" aria-label="Segment of">
        <label className="flex items-center gap-1"><input type="radio" checked={mode === "new"} onChange={() => setMode("new")} />New concept</label>
        <label className="flex items-center gap-1"><input type="radio" checked={mode === "existing"} onChange={() => setMode("existing")} />Existing concept</label>
      </div>
      {mode === "new" ? (
        <div className="flex flex-wrap items-center gap-2">
          <Input aria-label="Segment name" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. 보류 주문" className="h-8 w-44" />
          <label className="flex items-center gap-1 text-muted-foreground">under
            <select aria-label="Parent concept" value={under} onChange={e => setUnder(e.target.value)} className="h-8 rounded border bg-background px-1">
              <option value="">(none)</option>
              {concepts.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </label>
        </div>
      ) : (
        <select aria-label="Concept" value={existing} onChange={e => setExisting(e.target.value)} className="h-8 rounded border bg-background px-1">
          <option value="">Choose…</option>
          {concepts.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
      )}
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <Button size="sm" disabled={busy} onClick={() => void save()}>{busy ? "Saving…" : "Save segment"}</Button>
    </div>
  )
}

function BindForm({ tableId, column, concepts, onCancel, onDone }: {
  tableId: string; column: string; concepts: Concept[]; onCancel: () => void; onDone: (msg: string) => void
}) {
  const [concept, setConcept] = useState("")
  const [role, setRole] = useState<"key" | "attribute">("attribute")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const save = async () => {
    if (!concept) { setError("Pick a concept."); return }
    setBusy(true); setError(null)
    try {
      const r = await fetch("/api/semantic/concepts/bindings", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bindingBody(tableId, column, concept, role, null, "bound from the Data map")) })
      if (!r.ok) throw new Error(await detail(r))
      const out = await r.json()
      onDone(out.status === "proposed" ? `Proposed: ${column} holds ${concept} (${role}). An administrator approves it.` : `Saved: ${column} holds ${concept} (${role}).`)
    } catch (e) { setError(e instanceof Error ? e.message : "Could not bind the column.") } finally { setBusy(false) }
  }
  return (
    <div className="mt-1 space-y-2 rounded-md border bg-muted/30 p-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Concept" value={concept} onChange={e => setConcept(e.target.value)} className="h-8 rounded border bg-background px-1">
          <option value="">Choose a concept…</option>
          {concepts.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
        <select aria-label="Role" value={role} onChange={e => setRole(e.target.value as "key" | "attribute")} className="h-8 rounded border bg-background px-1">
          <option value="attribute">attribute</option>
          <option value="key">key (identifies it)</option>
        </select>
      </div>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button size="sm" disabled={busy} onClick={() => void save()}>{busy ? "Saving…" : "Bind"}</Button>
        <Button size="sm" variant="outline" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  )
}
