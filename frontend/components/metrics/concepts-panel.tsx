"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"
import { responseErrorMessage } from "@/lib/auth"
import { fieldError, type CatalogEntry } from "@/lib/metrics"
import {
  bindingText, cell, conceptRows, coverage, maskHref, matchesSearch, matrixTables, segmentBody, suggestionBody, tableKey, tableLabel,
  valueCondition, type Binding, type Concept, type ConceptViewer, type Feedback, type PiiGap, type Role, type Suggestion,
} from "@/lib/concepts"
import { CatalogSelect, ColumnSelect, TableSelect } from "./catalog-pickers"
import type { TableRef } from "./metric-editor"

type Data = { concepts: Concept[]; bindings: Binding[]; viewer: ConceptViewer }

const chip = "inline-block rounded border px-1.5 font-mono text-2xs leading-5"
const approvedCls = `${chip} border-[var(--dp-good)]/40 bg-[var(--dp-good)]/10 text-[var(--dp-good-text)]`
const waitingCls = `${chip} border-dashed border-[var(--dp-warn)]/60 bg-background text-[var(--dp-warn-text)]`
const ROLE: Record<Role, string> = { key: "key", attribute: "attribute", filter: "segment" }

async function errorText(res: Response, fallback: string) {
  const data = await res.clone().json().catch(() => null)
  return fieldError(data?.detail)?.message ?? await responseErrorMessage(res, fallback)
}

export function ConceptsPanel({ catalogs, tables }: { catalogs: CatalogEntry[]; tables: TableRef[] | null }) {
  const { toast } = useToast()
  const confirm = useConfirm()
  const [data, setData] = useState<Data | null>(null)
  const [state, setState] = useState<"loading" | "ok" | "off" | "error">("loading")
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(null)
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [gaps, setGaps] = useState<PiiGap[]>([])
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [seed, setSeed] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/semantic/concepts")
      if (r.status === 404) { setState("off"); return }
      if (!r.ok) throw new Error()
      setData(await r.json()); setState("ok")
    } catch { setState("error") }
  }, [])
  // Suggestions read every table's columns and the query history: slow, so they load
  // on their own and never hold the matrix back.
  const loadSuggestions = useCallback(async () => {
    try {
      const r = await fetch("/api/semantic/concepts/proposals")
      setSuggestions(r.ok ? (await r.json()).proposals ?? [] : [])
    } catch { setSuggestions([]) }
  }, [])
  // Columns of PII concepts with no mask. Needs governance:read; anyone else sees none.
  const loadGaps = useCallback(async () => {
    try {
      const r = await fetch("/api/semantic/concepts/pii-gaps")
      setGaps(r.ok ? (await r.json()).gaps ?? [] : [])
    } catch { setGaps([]) }
  }, [])
  // What /ai/sql questions suggest. Needs governance:read (the rows are other people's
  // questions, masked); anyone else gets no section.
  const loadFeedback = useCallback(async () => {
    try {
      const r = await fetch("/api/semantic/concepts/feedback")
      setFeedback(r.ok ? await r.json() : null)
    } catch { setFeedback(null) }
  }, [])
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); void loadSuggestions(); void loadGaps(); void loadFeedback() }, [load, loadSuggestions, loadGaps, loadFeedback])

  const concepts = useMemo(() => data?.concepts ?? [], [data])
  const bindings = useMemo(() => data?.bindings ?? [], [data])
  const sugg = useMemo(() => suggestions ?? [], [suggestions])
  const viewer = data?.viewer ?? { can_approve: false, can_propose: false }
  const rows = conceptRows(concepts).filter(r => matchesSearch(r.concept, search, bindings))
  const cols = matrixTables(bindings, sugg)
  const cov = coverage(concepts, bindings, sugg)
  const current = concepts.find(c => c.name === selected) ?? null

  const act = async (fn: () => Promise<Response>, ok: string, fallback: string) => {
    setBusy(true)
    try {
      const res = await fn()
      if (!res.ok) { toast(await errorText(res, fallback), "error"); return false }
      toast(ok, "success"); await load(); await loadSuggestions(); await loadGaps(); await loadFeedback(); return true
    } catch (e) { toast(e instanceof Error ? e.message : fallback, "error"); return false }
    finally { setBusy(false) }
  }
  const post = (url: string, body?: unknown) => fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined,
  })
  const decideSuggestion = (s: Suggestion, status: "approved" | "rejected") =>
    act(() => post("/api/semantic/concepts/bindings", suggestionBody(s, status)),
      status === "approved" ? (viewer.can_approve ? "Binding approved" : "Binding proposed") : "Suggestion rejected", "Could not save")
  const decideStored = (b: Binding, verb: "approve" | "reject") =>
    act(() => post(`/api/semantic/concepts/bindings/${b.id}/${verb}`), verb === "approve" ? "Binding approved" : "Proposal rejected", "Could not save")
  const retire = async (b: Binding) => {
    if (!(await confirm({
      title: `Retire ${b.concept} → ${bindingText(b)}`,
      message: "Agents and search stop using this binding. It is kept as retired, so it is not suggested again.",
      confirmText: "Retire", destructive: true,
    }))) return
    await act(() => fetch(`/api/semantic/concepts/bindings/${b.id}`, { method: "DELETE" }), "Binding retired", "Retire failed")
  }

  if (state === "off") return (
    <p className="rounded-xl border bg-card p-5 text-sm text-muted-foreground">
      Concepts are off on this deployment. An administrator turns them on with <span className="font-mono">ontology.enabled</span> in the Helm values.
    </p>
  )
  if (state === "error") return (
    <p className="rounded-xl border bg-card p-5 text-sm text-destructive">
      Could not load concepts. <button className="underline" onClick={() => void load()}>Retry</button>
    </p>
  )

  return (
    <div className="flex flex-wrap items-start gap-5">
      <section className="min-w-0 flex-[3_1_560px] space-y-3 rounded-xl border bg-card p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Input aria-label="Search concepts or columns" placeholder="Search concepts or columns" value={search}
                 onChange={e => setSearch(e.target.value)} className="h-8 w-60" />
          {cov.waiting > 0 && <Badge variant="outline">{cov.waiting} waiting</Badge>}
          {state === "ok" && cov.unbound.length > 0 && <Badge variant="outline">{cov.unbound.length} bound nowhere</Badge>}
          {suggestions === null && <span className="text-xs text-muted-foreground">Reading column names and query history…</span>}
          <span className="flex-1" />
          {viewer.can_approve && <ImportGlossary pull={viewer.openmetadata === true} onDone={async () => { await load(); await loadSuggestions(); await loadGaps() }} />}
          {(viewer.can_approve || viewer.can_propose) && <NewConcept concepts={concepts} seed={seed} onDone={async n => { setSeed(null); await load(); await loadSuggestions(); await loadFeedback(); setSelected(n) }} />}
        </div>
        {state === "loading" ? <p className="text-sm text-muted-foreground">Loading…</p>
          : concepts.length === 0 ? <p className="text-sm text-muted-foreground">No concepts yet. Add one, such as 고객 with the aliases customer and 회원; matching columns are then suggested here.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Concept</th>
                  {cols.map(t => <th key={t} scope="col" className="px-2 py-2 font-mono font-medium">{tableLabel(t, cols)}</th>)}
                  {cols.length === 0 && <th scope="col" className="px-2 py-2 font-medium">Tables</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map(({ concept: c, depth }) => (
                  <tr key={c.name} className={`border-t ${selected === c.name ? "bg-muted/50" : ""}`}>
                    <th scope="row" className="px-3 py-1.5 text-left font-normal">
                      <button type="button" onClick={() => setSelected(c.name)} aria-pressed={selected === c.name}
                              className="flex items-center gap-1.5 text-left hover:underline" style={{ paddingLeft: depth * 14 }}>
                        {depth > 0 && <span aria-hidden className="text-muted-foreground">└</span>}
                        <span className="font-medium">{c.name}</span>
                        {c.pii && <Badge variant="destructive" className="h-4 px-1 text-2xs">PII</Badge>}
                        {cov.unbound.includes(c.name) && <span className="text-xs text-muted-foreground">unbound</span>}
                      </button>
                    </th>
                    {cols.map(t => {
                      const x = cell(c.name, t, bindings, sugg)
                      const none = !x.approved.length && !x.proposed.length && !x.suggested.length
                      return (
                        <td key={t} className="px-2 py-1.5 align-top">
                          {none ? <span className="text-muted-foreground/50">—</span> : (
                            <div className="flex flex-wrap gap-1">
                              {x.approved.map(b => <span key={b.id} className={approvedCls} title={`${ROLE[b.role]} · approved`}>{b.role === "filter" ? b.filter_sql : b.column}</span>)}
                              {x.proposed.map(b => <span key={b.id} className={waitingCls} title={`${ROLE[b.role]} · proposed by ${b.proposed_by_name ?? "someone"}`}>{b.role === "filter" ? b.filter_sql : b.column}</span>)}
                              {x.suggested.map(s => <span key={s.column} className={waitingCls} title={`suggested: ${s.evidence}`}>{s.column}?</span>)}
                            </div>
                          )}
                        </td>
                      )
                    })}
                    {cols.length === 0 && <td className="px-2 py-1.5 text-xs text-muted-foreground">—</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-muted-foreground">
          <span className={approvedCls}>solid</span> approved · <span className={waitingCls}>dashed</span> proposed or suggested, waiting for an administrator · — not bound.
          Columns are the tables with any binding or suggestion.
        </p>
        {feedback && <FromQuestions feedback={feedback} concepts={concepts} viewer={viewer} busy={busy}
          onNewConcept={w => setSeed(w)}
          onAlias={(c, w) => act(() => post(`/api/semantic/concepts/${encodeURIComponent(c)}/terms`, { term: w }), `${w} added to ${c}`, "Could not add the word")}
          onSegment={(c, v) => act(() => post("/api/semantic/concepts/bindings", segmentBody(v, c)),
            viewer.can_approve ? `Segment added to ${c}` : `Segment proposed for ${c}`, "Could not add the segment")} />}
      </section>

      <aside aria-label="Concept details" className="min-w-0 flex-[2_1_300px] space-y-4 rounded-xl border bg-muted/40 p-5 text-sm lg:sticky lg:top-6">
        {!current ? (
          <div className="space-y-2 text-muted-foreground">
            <h3 className="text-sm font-semibold text-foreground">What a binding is</h3>
            <p>A binding says which column a business word is: <span className="font-mono">고객</span> is <span className="font-mono">customers.id</span> and <span className="font-mono">orders.customer_id</span>; <span className="font-mono">VIP 고객</span> is <span className="font-mono">customers.tier = &apos;VIP&apos;</span>.</p>
            <p>Suggestions come from column names and from joins people ran. An administrator approves each one; {viewer.can_approve ? "you can approve." : viewer.can_propose ? "you can propose." : "you can read."}</p>
            <p>Pick a concept to see and change its bindings.</p>
          </div>
        ) : (
          <ConceptRail key={current.name} concept={current} concepts={concepts} bindings={bindings.filter(b => b.concept === current.name)}
                       suggestions={sugg.filter(s => s.concept === current.name)} viewer={viewer} busy={busy}
                       gaps={gaps.filter(g => g.concept === current.name)}
                       catalogs={catalogs} tables={tables}
                       onSuggestion={decideSuggestion} onStored={decideStored} onRetire={retire}
                       onAdd={body => act(() => post("/api/semantic/concepts/bindings", body),
                         viewer.can_approve ? "Binding approved" : "Binding proposed", "Could not save")} />
        )}
      </aside>
    </div>
  )
}

function ConceptRail({ concept, concepts, bindings, suggestions, gaps, viewer, busy, catalogs, tables, onSuggestion, onStored, onRetire, onAdd }: {
  concept: Concept; concepts: Concept[]; bindings: Binding[]; suggestions: Suggestion[]; gaps: PiiGap[]; viewer: ConceptViewer; busy: boolean
  catalogs: CatalogEntry[]; tables: TableRef[] | null
  onSuggestion: (s: Suggestion, status: "approved" | "rejected") => Promise<unknown>
  onStored: (b: Binding, verb: "approve" | "reject") => Promise<unknown>
  onRetire: (b: Binding) => Promise<unknown>
  onAdd: (body: unknown) => Promise<boolean>
}) {
  const narrower = concepts.filter(c => c.parent === concept.name).map(c => c.name)
  const approved = bindings.filter(b => b.status === "approved")
  const proposed = bindings.filter(b => b.status === "proposed")
  const canWrite = viewer.can_approve || viewer.can_propose
  const where = (b: { catalog: string; namespace: string; table: string }) => tableKey(b)
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold">{concept.name}</h3>
        {concept.pii && <Badge variant="destructive">PII</Badge>}
      </div>
      {concept.description && <p className="text-muted-foreground">{concept.description}</p>}
      <dl className="space-y-1 text-xs">
        <div><dt className="inline text-muted-foreground">Also called </dt><dd className="inline">{concept.terms.length ? concept.terms.join(" · ") : "—"}</dd></div>
        {concept.parent && <div><dt className="inline text-muted-foreground">Part of </dt><dd className="inline">{concept.parent}</dd></div>}
        {narrower.length > 0 && <div><dt className="inline text-muted-foreground">Narrower </dt><dd className="inline">{narrower.join(" · ")}</dd></div>}
      </dl>

      <section className="space-y-1.5 border-t pt-3">
        <h4 className="text-sm font-semibold">Bound to</h4>
        {approved.length === 0 ? <p className="text-xs text-muted-foreground">Nothing yet.</p> : (
          <ul className="space-y-1">
            {approved.map(b => (
              <li key={b.id} className="flex items-center justify-between gap-2">
                <span className="min-w-0"><span className={approvedCls}>{where(b)}{b.role === "filter" ? `: ${b.filter_sql}` : `.${b.column}`}</span> <span className="text-xs text-muted-foreground">{ROLE[b.role]}</span></span>
                {viewer.can_approve && <Button size="sm" variant="ghost" disabled={busy} onClick={() => void onRetire(b)}>Retire…</Button>}
              </li>
            ))}
          </ul>
        )}
      </section>

      {concept.pii && gaps.length > 0 && (
        <section className="space-y-1.5 border-t pt-3">
          <h4 className="text-sm font-semibold">Personal data without a mask</h4>
          <p className="text-xs text-muted-foreground">No column mask covers these columns of {concept.name}, so anyone who may read the table sees them in full. A suggestion only: nothing is masked until an administrator adds a mask.</p>
          <ul className="space-y-1">
            {gaps.map(g => (
              <li key={`${tableKey(g)}.${g.column}`} className="flex items-center justify-between gap-2">
                <span className="min-w-0">
                  <span className="font-mono text-xs">{g.table}.{g.column}</span>
                  {g.key && <span className="text-xs text-muted-foreground"> key: a hash mask keeps joins on it working</span>}
                </span>
                <Link href={maskHref(g)} className="shrink-0 text-xs underline underline-offset-2">Review mask</Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {(proposed.length > 0 || suggestions.length > 0) && (
        <section className="space-y-2 border-t pt-3">
          <h4 className="text-sm font-semibold">Waiting</h4>
          {proposed.map(b => (
            <div key={b.id} className="space-y-1 rounded-lg border border-dashed border-[var(--dp-warn)]/60 bg-background p-2.5">
              <p><span className="font-mono text-xs">{bindingText(b)}</span> <span className="text-xs text-muted-foreground">as {ROLE[b.role]}</span></p>
              <p className="text-xs text-muted-foreground">Proposed by {b.proposed_by_name ?? "someone"}{b.evidence ? `: ${b.evidence}` : ""}</p>
              {viewer.can_approve && (
                <div className="flex gap-1.5">
                  <Button size="sm" disabled={busy} onClick={() => void onStored(b, "approve")}>Approve</Button>
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void onStored(b, "reject")}>Reject</Button>
                </div>
              )}
            </div>
          ))}
          {suggestions.map(s => (
            <div key={`${where(s)}.${s.column}`} className="space-y-1 rounded-lg border border-dashed border-[var(--dp-warn)]/60 bg-background p-2.5">
              <p><span className="font-mono text-xs">{s.table}.{s.column}</span> <span className="text-xs text-muted-foreground">as {ROLE[s.role]} · suggested</span></p>
              <p className="text-xs text-muted-foreground">{s.evidence}.</p>
              {canWrite && (
                <div className="flex gap-1.5">
                  <Button size="sm" disabled={busy} onClick={() => void onSuggestion(s, "approved")}>{viewer.can_approve ? "Approve" : "Propose"}</Button>
                  {viewer.can_approve && <Button size="sm" variant="outline" disabled={busy} onClick={() => void onSuggestion(s, "rejected")}>Reject</Button>}
                </div>
              )}
            </div>
          ))}
        </section>
      )}

      {canWrite && <AddBinding concept={concept.name} catalogs={catalogs} tables={tables} busy={busy} approves={viewer.can_approve} onAdd={onAdd} />}
    </>
  )
}

function AddBinding({ concept, catalogs, tables, busy, approves, onAdd }: {
  concept: string; catalogs: CatalogEntry[]; tables: TableRef[] | null; busy: boolean; approves: boolean
  onAdd: (body: unknown) => Promise<boolean>
}) {
  const [catalog, setCatalog] = useState(catalogs[0]?.name ?? "")
  const [table, setTable] = useState("")
  const [column, setColumn] = useState("")
  const [role, setRole] = useState<Role>("key")
  const [filter, setFilter] = useState("")
  const engine = catalogs.find(c => c.name.toLowerCase() === catalog.toLowerCase())?.engine_catalog ?? catalog
  const inCatalog = tables === null ? null
    : tables.filter(t => t.catalog.toLowerCase() === engine.toLowerCase()).map(t => `${t.namespace}.${t.name}`)
  const ready = catalog && table.includes(".") && column && (role !== "filter" || filter.trim())
  const submit = async () => {
    const ok = await onAdd({ concept, catalog, table, column, role, filter_sql: role === "filter" ? filter : null, source: "manual" })
    if (ok) { setColumn(""); setFilter("") }
  }
  return (
    <section className="space-y-2 border-t pt-3">
      <h4 className="text-sm font-semibold">Add a binding</h4>
      <div className="grid gap-2">
        <div className="space-y-1"><Label htmlFor="cb-catalog" className="text-xs">Catalog</Label>
          <CatalogSelect id="cb-catalog" value={catalog} catalogs={catalogs} onChange={v => { setCatalog(v); setTable(""); setColumn("") }} /></div>
        <div className="space-y-1"><Label htmlFor="cb-table" className="text-xs">Table</Label>
          <TableSelect id="cb-table" value={table} tables={inCatalog} onChange={v => { setTable(v); setColumn("") }} /></div>
        <div className="space-y-1"><Label htmlFor="cb-column" className="text-xs">Column</Label>
          <ColumnSelect id="cb-column" catalog={catalog} table={table} value={column} onChange={setColumn} /></div>
        <div className="space-y-1"><Label htmlFor="cb-role" className="text-xs">It is</Label>
          <select id="cb-role" className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={role} onChange={e => setRole(e.target.value as Role)}>
            <option value="key">a key (identifies the concept)</option>
            <option value="attribute">an attribute</option>
            <option value="filter">a segment (a condition on this table)</option>
          </select></div>
        {role === "filter" && (
          <div className="space-y-1"><Label htmlFor="cb-filter" className="text-xs">Condition</Label>
            <Input id="cb-filter" className="font-mono" placeholder={column ? `${column} = 'VIP'` : "tier = 'VIP'"} value={filter} onChange={e => setFilter(e.target.value)} /></div>
        )}
      </div>
      <Button size="sm" disabled={busy || !ready} onClick={() => void submit()}>{approves ? "Add binding" : "Propose binding"}</Button>
    </section>
  )
}

function NewConcept({ concepts, seed, onDone }: { concepts: Concept[]; seed?: string | null; onDone: (name: string) => Promise<void> }) {
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  // A word suggested by the questions opens the form with it as the name.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (seed) { setName(seed); setOpen(true) }
  }, [seed])
  const [terms, setTerms] = useState("")
  const [parent, setParent] = useState("")
  const [pii, setPii] = useState(false)
  const [saving, setSaving] = useState(false)
  if (!open) return <Button size="sm" variant="outline" onClick={() => setOpen(true)}>New concept</Button>
  const save = async () => {
    setSaving(true)
    try {
      const res = await fetch("/api/ai/concepts", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), parent: parent || null, pii,
                               terms: terms.split(",").map(t => t.trim()).filter(Boolean) }),
      })
      if (!res.ok) { toast(await responseErrorMessage(res, "Could not add the concept"), "error"); return }
      toast(`${name.trim()} added`, "success")
      const n = name.trim()
      setOpen(false); setName(""); setTerms(""); setParent(""); setPii(false)
      await onDone(n)
    } catch (e) { toast(e instanceof Error ? e.message : "Could not add the concept", "error") }
    finally { setSaving(false) }
  }
  return (
    <div className="flex w-full flex-wrap items-end gap-2 rounded-lg border bg-muted/30 p-3">
      <div className="space-y-1"><Label htmlFor="nc-name" className="text-xs">Name</Label>
        <Input id="nc-name" className="h-8 w-36" value={name} onChange={e => setName(e.target.value)} placeholder="고객" /></div>
      <div className="space-y-1"><Label htmlFor="nc-terms" className="text-xs">Also called (comma-separated)</Label>
        <Input id="nc-terms" className="h-8 w-56" value={terms} onChange={e => setTerms(e.target.value)} placeholder="customer, 회원" /></div>
      <div className="space-y-1"><Label htmlFor="nc-parent" className="text-xs">Part of</Label>
        <select id="nc-parent" className="h-8 rounded-md border bg-background px-2 text-sm" value={parent} onChange={e => setParent(e.target.value)}>
          <option value="">None</option>
          {concepts.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select></div>
      <label className="flex h-8 items-center gap-1.5 text-sm"><input type="checkbox" checked={pii} onChange={e => setPii(e.target.checked)} /> Personal data</label>
      <Button size="sm" disabled={saving || !name.trim()} onClick={() => void save()}>Add concept</Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
    </div>
  )
}

type ImportResult = { terms_read: number; created: string[]; terms_added: number; pii_differs: string[]; bindings_proposed: number }

/** Concepts from an OpenMetadata glossary: pulled from the add-on when it runs here, or
 *  from an export file. Column tags become proposals; nothing is approved for you. */
function ImportGlossary({ pull, onDone }: { pull: boolean; onDone: () => Promise<void> }) {
  const { toast } = useToast()
  const file = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const send = async (glossary?: unknown) => {
    setBusy(true)
    try {
      const res = await fetch("/api/semantic/concepts/import/openmetadata", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(glossary === undefined ? {} : { glossary }),
      })
      if (!res.ok) { toast(await errorText(res, "Import failed"), "error"); return }
      const d: ImportResult = await res.json()
      const n = (k: number, one: string) => `${k} ${one}${k === 1 ? "" : "s"}`
      const parts = [`${n(d.terms_read, "term")} read`, `${n(d.created.length, "concept")} added`, `${n(d.terms_added, "word")} added`]
      if (d.bindings_proposed) parts.push(`${n(d.bindings_proposed, "binding")} proposed`)
      if (d.pii_differs.length) parts.push(`PII flag differs and was kept for ${d.pii_differs.join(", ")}`)
      toast(parts.join(", "), "success")
      await onDone()
    } catch (e) { toast(e instanceof Error ? e.message : "Import failed", "error") }
    finally { setBusy(false) }
  }
  const pick = async (f: File | undefined) => {
    if (!f) return
    const text = await f.text()
    let glossary: unknown = text
    if (!f.name.toLowerCase().endsWith(".csv")) {
      try { glossary = JSON.parse(text) } catch { toast("The file is neither JSON nor a CSV export.", "error"); return }
    }
    await send(glossary)
    if (file.current) file.current.value = ""
  }
  return (
    <>
      {pull && <Button size="sm" variant="outline" disabled={busy} onClick={() => void send()}>Pull from OpenMetadata</Button>}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => file.current?.click()}
              title="An OpenMetadata glossary export (CSV) or its API JSON">Import glossary…</Button>
      <input ref={file} type="file" accept=".csv,.json,application/json,text/csv" className="hidden" aria-label="Glossary file"
             onChange={e => void pick(e.target.files?.[0])} />
    </>
  )
}

/** Suggestions from /ai/sql use: words no concept covers, values no segment states, and
 *  joins between keys of different concepts. Shown to governance readers. */
function FromQuestions({ feedback, concepts, viewer, busy, onNewConcept, onAlias, onSegment }: {
  feedback: Feedback; concepts: Concept[]; viewer: ConceptViewer; busy: boolean
  onNewConcept: (word: string) => void
  onAlias: (concept: string, word: string) => Promise<unknown>
  onSegment: (concept: string, v: Feedback["values"][number]) => Promise<unknown>
}) {
  const [target, setTarget] = useState<Record<string, string>>({})
  const canWrite = viewer.can_approve || viewer.can_propose
  const empty = !feedback.words.length && !feedback.values.length && !feedback.joins.length
  const pick = (key: string, label: string) => (
    <select aria-label={label} className="h-7 rounded-md border bg-background px-1.5 text-xs" value={target[key] ?? ""}
            onChange={e => setTarget(t => ({ ...t, [key]: e.target.value }))}>
      <option value="">Concept…</option>
      {concepts.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
    </select>
  )
  return (
    <section aria-label="From questions" className="space-y-3 border-t pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">From questions</h3>
        <span className="text-xs text-muted-foreground">{feedback.questions} questions to Analytics and agents in the last {feedback.days} days</span>
      </div>
      {empty ? (
        <p className="text-xs text-muted-foreground">
          {feedback.questions ? "Nothing to suggest: every word, value and join in recent questions is covered." : "No questions yet. Suggestions appear once people and agents ask in Analytics or over MCP."}
        </p>
      ) : <p className="text-xs text-muted-foreground">Seen in at least two questions. Suggestions only: nothing changes until you add it.</p>}

      {feedback.values.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold">Conditions no segment states</h4>
          <p className="text-xs text-muted-foreground">A segment belongs to a narrower concept (VIP 고객 under 고객): create that concept first, then make the condition its segment.</p>
          <ul className="space-y-1.5">
            {feedback.values.map(v => {
              const key = `v:${v.table}.${v.column}=${v.value}`
              return (
                <li key={key} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs">{v.table.split(".").slice(-1)[0]}: {valueCondition(v)}</span>
                  <span className="text-xs text-muted-foreground" title={v.example}>{v.questions} questions{v.segments_on_column ? " · other values of this column are segments" : ""}</span>
                  {canWrite && <span className="ml-auto flex items-center gap-1.5">{pick(key, `Concept for ${valueCondition(v)}`)}
                    <Button size="sm" variant="outline" className="h-7" disabled={busy || !target[key]} onClick={() => void onSegment(target[key], v)}>Make segment</Button></span>}
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {feedback.words.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold">Words no concept covers</h4>
          <ul className="space-y-1.5">
            {feedback.words.map(w => {
              const key = `w:${w.word}`
              return (
                <li key={key} className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{w.word}</span>
                  <span className="text-xs text-muted-foreground" title={w.examples.join("\n")}>{w.questions} questions</span>
                  {canWrite && <span className="ml-auto flex items-center gap-1.5">
                    {pick(key, `Concept for ${w.word}`)}
                    <Button size="sm" variant="outline" className="h-7" disabled={busy || !target[key]} onClick={() => void onAlias(target[key], w.word)}>Add as alias</Button>
                    <Button size="sm" variant="ghost" className="h-7" disabled={busy} onClick={() => onNewConcept(w.word)}>New concept</Button>
                  </span>}
                </li>
              )
            })}
          </ul>
          <p className="text-xs text-muted-foreground">A word may name a column rather than a concept (국가, 카테고리): bind it as an attribute in that concept&apos;s details instead.</p>
        </div>
      )}

      {feedback.joins.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold">Joins between different concepts</h4>
          <ul className="space-y-1">
            {feedback.joins.map(j => (
              <li key={j.join} className="text-xs">
                <span className="font-mono">{j.join}</span>{" "}
                <span className="text-muted-foreground" title={j.example}>
                  {j.seen} times, {j.unrepaired ? `${j.unrepaired} left in the answer` : "all fixed by the check"}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">Usually a key bound to the wrong concept, or a key missing a binding.</p>
        </div>
      )}
    </section>
  )
}
