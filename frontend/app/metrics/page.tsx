// frontend/app/metrics/page.tsx
"use client"

import { useCallback, useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CapabilityGate } from "@/lib/capabilities"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"
import { responseErrorMessage } from "@/lib/auth"
import {
  approvalWarning, fieldError, joinCandidatePayload, metricStatusBadge, pendingApproval, unresolvedJoinDims, versionDiff,
  type CatalogEntry, type DimensionRow, type MetricDetail, type MetricSummary, type RelationshipEdge, type Viewer,
} from "@/lib/metrics"

type Join = { id: number; catalog: string; from_table: string; to_table: string; on_columns: string[][]; source: string; approved_by_name: string | null }
const GRAINS = ["day", "week", "month", "quarter", "year"]
const TONE = { ok: "secondary", draft: "outline", retired: "destructive" } as const

async function jsonOrThrow(res: Response, fallback: string) {
  if (!res.ok) throw new Error(await responseErrorMessage(res, fallback))
  return res.json()
}

function MetricsPage() {
  const { toast } = useToast()
  const confirm = useConfirm()
  const [metrics, setMetrics] = useState<MetricSummary[]>([])
  const [viewer, setViewer] = useState<Viewer>({ can_author: false, can_approve: false })
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<MetricDetail | null>(null)
  const [editing, setEditing] = useState<"new" | "version" | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await jsonOrThrow(await fetch("/api/semantic/metrics"), "Could not load metrics")
      setMetrics(data.metrics); setViewer(data.viewer)
    } catch (e) { toast(e instanceof Error ? e.message : "Could not load metrics", "error") }
  }, [toast])

  const open = useCallback(async (name: string) => {
    setSelected(name); setDetail(null)
    try {
      setDetail(await jsonOrThrow(await fetch(`/api/semantic/metrics/${encodeURIComponent(name)}`), "Could not load metric"))
    } catch (e) { toast(e instanceof Error ? e.message : "Could not load metric", "error") }
  }, [toast])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  // What "Approve vN" approves is the server's pending version, shown with its own SQL —
  // never the approved version's fields under a newer number.
  const pending = pendingApproval(detail)
  const approve = async () => {
    if (!detail || !pending) return
    const warn = approvalWarning(detail.partition_info)
    if (!(await confirm({
      title: `Approve ${detail.metric.name} v${pending.version}`,
      message: `Agents will compute this metric from v${pending.version}: ${pending.measure}${pending.filters ? ` WHERE ${pending.filters}` : ""}.${warn ? ` ${warn}` : ""}${pending.example_sql ? `\n\n${pending.example_sql}` : ""}`,
      confirmText: "Approve",
    }))) return
    try {
      await jsonOrThrow(await fetch(`/api/semantic/metrics/${detail.metric.name}/versions/${pending.version}/approve`, { method: "POST" }), "Approval failed")
      toast(`${detail.metric.name} v${pending.version} approved`, "success")
      await load(); await open(detail.metric.name)
    } catch (e) { toast(e instanceof Error ? e.message : "Approval failed", "error") }
  }
  const retire = async () => {
    if (!detail) return
    if (!(await confirm({ title: `Retire ${detail.metric.name}`, message: "Agents will no longer see or query it. Its versions stay, so past citations still resolve.", confirmText: "Retire", destructive: true }))) return
    try {
      await jsonOrThrow(await fetch(`/api/semantic/metrics/${detail.metric.name}/retire`, { method: "POST" }), "Retire failed")
      await load(); setSelected(null); setDetail(null)
    } catch (e) { toast(e instanceof Error ? e.message : "Retire failed", "error") }
  }

  return (
    <div className="flex-1 space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Metrics</h1>
          <p className="text-sm text-muted-foreground">Approved definitions agents compute with metric_query. Every result cites the version and its approver.</p>
        </div>
        {viewer.can_author && <Button onClick={() => { setEditing("new"); setSelected(null); setDetail(null) }}>New metric</Button>}
      </div>
      <Tabs defaultValue="metrics">
        <TabsList>
          <TabsTrigger value="metrics">Definitions</TabsTrigger>
          <TabsTrigger value="joins">Joins</TabsTrigger>
        </TabsList>
        <TabsContent value="metrics" className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <Card>
            <CardContent className="p-0">
              {metrics.length === 0 ? (
                <p className="p-6 text-sm text-muted-foreground">No metrics yet.</p>
              ) : (
                <ul className="divide-y">
                  {metrics.map(m => {
                    const b = metricStatusBadge(m)
                    return (
                      <li key={m.name}>
                        <button className={`w-full px-4 py-3 text-left hover:bg-muted ${selected === m.name ? "bg-muted" : ""}`} onClick={() => { setEditing(null); void open(m.name) }}>
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium">{m.label} <span className="font-mono text-xs text-muted-foreground">{m.name}</span></span>
                            <Badge variant={TONE[b.tone]}>{b.label}</Badge>
                          </div>
                          <div className="text-xs text-muted-foreground">{m.catalog} · {m.owner_name ?? "—"}</div>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </CardContent>
          </Card>
          {editing ? (
            <MetricEditor mode={editing} base={editing === "version" ? detail : null}
              onDone={async name => { setEditing(null); await load(); await open(name) }}
              onCancel={() => setEditing(null)} />
          ) : detail ? (
            <Card>
              <CardHeader className="flex flex-row items-start justify-between gap-2">
                <div>
                  <CardTitle>{detail.metric.label} <span className="font-mono text-sm text-muted-foreground">{detail.metric.name}</span></CardTitle>
                  <p className="text-xs text-muted-foreground">{detail.recent_queries} queries in 30 days</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {viewer.can_author && detail.metric.status !== "retired" && <Button size="sm" variant="outline" onClick={() => setEditing("version")}>New version</Button>}
                  {viewer.can_approve && pending && detail.metric.status !== "retired" && <Button size="sm" onClick={approve}>Approve v{pending.version}</Button>}
                  {viewer.can_approve && detail.metric.status !== "retired" && <Button size="sm" variant="ghost" onClick={retire}>Retire</Button>}
                </div>
              </CardHeader>
              <CardContent className="space-y-4 text-sm">
                {detail.broken && <div className="rounded border border-destructive/40 bg-destructive/10 p-2 text-destructive">Broken: {detail.broken_reason}</div>}
                <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1">
                  <dt className="text-muted-foreground">Measure</dt><dd className="font-mono">{detail.metric.measure}</dd>
                  <dt className="text-muted-foreground">Table</dt><dd className="font-mono">{detail.metric.catalog}.{detail.metric.base_table}</dd>
                  <dt className="text-muted-foreground">Filters</dt><dd className="font-mono">{detail.metric.filters ?? "—"}</dd>
                  <dt className="text-muted-foreground">Synonyms</dt><dd>{detail.metric.synonyms.join(", ") || "—"}</dd>
                </dl>
                {detail.example_sql && <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">{detail.example_sql}</pre>}
                {pending && pending.version !== detail.metric.version && (
                  <div className="space-y-1 rounded border border-dashed p-2">
                    <h3 className="font-medium">Pending v{pending.version} (not approved)</h3>
                    <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1">
                      <dt className="text-muted-foreground">Measure</dt><dd className="font-mono">{pending.measure}</dd>
                      <dt className="text-muted-foreground">Table</dt><dd className="font-mono">{pending.catalog}.{pending.base_table}</dd>
                      <dt className="text-muted-foreground">Filters</dt><dd className="font-mono">{pending.filters ?? "—"}</dd>
                    </dl>
                    {pending.example_sql && <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">{pending.example_sql}</pre>}
                  </div>
                )}
                <div>
                  <h3 className="mb-1 font-medium">Versions</h3>
                  <ul className="space-y-2">
                    {detail.versions.map((v, i) => (
                      <li key={v.version} className="rounded border p-2">
                        <div className="flex justify-between text-xs">
                          <span>v{v.version} · {v.created_by_name ?? "—"} · {v.change_note || "no note"}</span>
                          <span>{v.approved_at ? `approved by ${v.approved_by_name}` : "not approved"}</span>
                        </div>
                        <ul className="mt-1 font-mono text-xs text-muted-foreground">
                          {versionDiff(detail.versions[i + 1], v).map(line => <li key={line}>{line}</li>)}
                        </ul>
                      </li>
                    ))}
                  </ul>
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card><CardContent className="p-6 text-sm text-muted-foreground">Select a metric.</CardContent></Card>
          )}
        </TabsContent>
        <TabsContent value="joins" className="mt-4">
          <JoinsTab canApprove={viewer.can_approve} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

type DimRow = { name: string; column: string; join_id: number | null; joinRef?: DimensionRow["join"] }

function MetricEditor({ mode, base, onDone, onCancel }: {
  mode: "new" | "version"; base: MetricDetail | null
  onDone: (name: string) => void; onCancel: () => void
}) {
  const { toast } = useToast()
  const cur = base?.versions[0]
  const [name, setName] = useState(base?.metric.name ?? "")
  const [label, setLabel] = useState(base?.metric.label ?? "")
  const [synonyms, setSynonyms] = useState((base?.metric.synonyms ?? []).join(", "))
  const [catalog, setCatalog] = useState(cur?.catalog ?? "")
  const [table, setTable] = useState(cur?.base_table ?? "")
  const [measure, setMeasure] = useState(cur?.measure ?? "")
  const [filters, setFilters] = useState(cur?.filters ?? "")
  const [timeColumn, setTimeColumn] = useState(cur?.time_column ?? "")
  const [grains, setGrains] = useState<string[]>(cur?.grains ?? [])
  const [maxDays, setMaxDays] = useState(cur?.max_period_days ?? 366)
  const [dims, setDims] = useState<DimRow[]>((cur?.dimensions ?? []).map(d => ({ name: d.name, column: d.column, join_id: null, joinRef: d.join })))
  const [note, setNote] = useState("")
  const [joins, setJoins] = useState<Join[]>([])
  const [joinsLoaded, setJoinsLoaded] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<{ columns: string[]; rows: unknown[][]; citation: { sql: string } } | null>(null)

  useEffect(() => {
    fetch("/api/semantic/joins").then(r => r.ok ? r.json() : { joins: [] }).then(d => {
      setJoins(d.joins)
      // A saved version stores the join by its tables and columns; find the registry row again.
      setDims(prev => prev.map(x => {
        const ref = x.joinRef
        const hit = ref && (d.joins as Join[]).find(j => j.to_table === ref.to_table && JSON.stringify(j.on_columns) === JSON.stringify(ref.on))
        return hit ? { ...x, join_id: hit.id } : x
      }))
    }).catch(() => setJoins([])).finally(() => setJoinsLoaded(true))
  }, [])

  const version = () => ({
    catalog, base_table: table, measure, filters: filters || null, time_column: timeColumn || null,
    grains, max_period_days: maxDays, change_note: note,
    dimensions: dims.filter(d => d.name && d.column).map(d => (d.join_id ? { name: d.name, column: d.column, join_id: d.join_id } : { name: d.name, column: d.column })),
  })
  const save = async () => {
    setErrors({})
    const unresolved = unresolvedJoinDims(dims)
    if (unresolved.length) {
      setErrors({ dimensions: `Pick the join for ${unresolved.join(", ")}: its approved join was not found.` })
      return
    }
    const url = mode === "new" ? "/api/semantic/metrics" : `/api/semantic/metrics/${name}/versions`
    const body = mode === "new"
      ? { name, label, synonyms: synonyms.split(",").map(s => s.trim()).filter(Boolean), version: version() }
      : version()
    try {
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      if (res.ok) { const d = await res.json(); toast(`${d.name} v${d.version} saved as draft`, "success"); onDone(d.name); return }
      const data = await res.json().catch(() => ({}))
      const fe = fieldError(data.detail)
      if (fe) setErrors({ [fe.field]: fe.message })
      else toast(typeof data.detail === "string" ? data.detail : "Save failed", "error")
    } catch (e) { toast(e instanceof Error ? e.message : "Save failed", "error") }
  }
  const runPreview = async () => {
    const latest = base?.versions[0]?.version
    if (!latest) return
    try {
      const res = await fetch(`/api/semantic/metrics/${name}/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version: latest, ...(base?.versions[0]?.time_column ? { period: "last_month" } : {}) }),
      })
      if (!res.ok) { toast(await responseErrorMessage(res, "Preview failed"), "error"); return }
      setPreview(await res.json())
    } catch (e) { toast(e instanceof Error ? e.message : "Preview failed", "error") }
  }
  const err = (f: string) => errors[f] && <p className="text-xs text-destructive">{errors[f]}</p>
  const usable = joins.filter(j => j.catalog.toLowerCase() === catalog.toLowerCase() && j.from_table.toLowerCase() === table.toLowerCase())

  return (
    <Card>
      <CardHeader><CardTitle>{mode === "new" ? "New metric" : `New version of ${name}`}</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        {mode === "new" && (<>
          <label className="block">Name <Input value={name} onChange={e => setName(e.target.value)} placeholder="revenue" />{err("name")}</label>
          <label className="block">Label <Input value={label} onChange={e => setLabel(e.target.value)} placeholder="매출" />{err("label")}</label>
          <label className="block">Synonyms <Input value={synonyms} onChange={e => setSynonyms(e.target.value)} placeholder="매출액, sales" /></label>
        </>)}
        <div className="grid grid-cols-2 gap-2">
          <label className="block">Catalog <Input value={catalog} onChange={e => setCatalog(e.target.value)} />{err("catalog")}</label>
          <label className="block">Base table <Input value={table} onChange={e => setTable(e.target.value)} placeholder="sales.orders" />{err("base_table")}</label>
        </div>
        <label className="block">Measure <Input className="font-mono" value={measure} onChange={e => setMeasure(e.target.value)} placeholder="SUM(amount)" />{err("measure")}</label>
        <label className="block">Filters <Input className="font-mono" value={filters} onChange={e => setFilters(e.target.value)} placeholder="status = 'paid'" />{err("filters")}</label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block">Time column <Input value={timeColumn} onChange={e => setTimeColumn(e.target.value)} />{err("time_column")}</label>
          <label className="block">Max period (days) <Input type="number" min={1} max={3660} value={maxDays} onChange={e => setMaxDays(Number(e.target.value))} /></label>
        </div>
        <div className="flex flex-wrap gap-3">
          {GRAINS.map(g => (
            <label key={g} className="flex items-center gap-1">
              <input type="checkbox" checked={grains.includes(g)} onChange={e => setGrains(e.target.checked ? [...grains, g] : grains.filter(x => x !== g))} /> {g}
            </label>
          ))}
          {err("grains")}
        </div>
        <div className="space-y-2">
          <div className="font-medium">Dimensions</div>
          {dims.map((d, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_1.2fr_auto] gap-2">
              <Input value={d.name} placeholder="name" onChange={e => setDims(dims.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
              <Input value={d.column} placeholder="column" onChange={e => setDims(dims.map((x, j) => j === i ? { ...x, column: e.target.value } : x))} />
              <select className="rounded border bg-background px-2" value={d.join_id ?? ""} onChange={e => setDims(dims.map((x, j) => j === i ? { ...x, join_id: e.target.value ? Number(e.target.value) : null, joinRef: undefined } : x))}>
                <option value="">base table</option>
                {usable.map(j => <option key={j.id} value={j.id}>{j.to_table}</option>)}
              </select>
              <Button size="sm" variant="ghost" onClick={() => setDims(dims.filter((_, j) => j !== i))}>Remove</Button>
            </div>
          ))}
          <Button size="sm" variant="outline" onClick={() => setDims([...dims, { name: "", column: "", join_id: null }])}>Add dimension</Button>
          {err("dimensions")}
        </div>
        <label className="block">Change note <Textarea value={note} onChange={e => setNote(e.target.value)} /></label>
        <div className="flex gap-2">
          <Button onClick={save} disabled={!joinsLoaded}>Save draft</Button>
          {mode === "version" && <Button variant="outline" onClick={runPreview}>Preview latest draft</Button>}
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
        {preview && (
          <div className="space-y-1">
            <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">{preview.citation.sql}</pre>
            <table className="text-xs"><thead><tr>{preview.columns.map(c => <th key={c} className="px-2 text-left">{c}</th>)}</tr></thead>
              <tbody>{preview.rows.slice(0, 20).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="px-2">{String(c)}</td>)}</tr>)}</tbody></table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function JoinsTab({ canApprove }: { canApprove: boolean }) {
  const { toast } = useToast()
  const [joins, setJoins] = useState<Join[]>([])
  const [edges, setEdges] = useState<RelationshipEdge[]>([])
  const [catalogs, setCatalogs] = useState<CatalogEntry[]>([])
  const load = useCallback(async () => {
    const [j, g, c] = await Promise.all([
      fetch("/api/semantic/joins").then(r => r.ok ? r.json() : { joins: [] }),
      fetch("/api/catalog/relationships").then(r => r.ok ? r.json() : { edges: [] }),
      fetch("/api/catalogs").then(r => r.ok ? r.json() : { catalogs: [] }),
    ])
    setJoins(j.joins); setEdges(g.edges ?? []); setCatalogs(c.catalogs ?? [])
  }, [])
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load().catch(() => undefined) }, [load])

  const approve = async (e: RelationshipEdge, reversed: boolean) => {
    const body = joinCandidatePayload(e, catalogs, reversed)
    if (!body) return
    try {
      const res = await fetch("/api/semantic/joins", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      })
      if (res.ok) { toast("Join approved", "success"); await load(); return }
      const data = await res.json().catch(() => ({}))
      toast(fieldError(data.detail)?.message ?? (typeof data.detail === "string" ? data.detail : "Approval failed"), "error")
    } catch (err) { toast(err instanceof Error ? err.message : "Approval failed", "error") }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Approved joins</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          {joins.length === 0 ? <p className="text-muted-foreground">None yet.</p> : joins.map(j => (
            <div key={j.id} className="font-mono text-xs">{j.catalog}: {j.from_table} → {j.to_table} on {j.on_columns.map(p => p.join(" = ")).join(", ")} <span className="text-muted-foreground">({j.source}, {j.approved_by_name})</span></div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Candidates</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="text-xs text-muted-foreground">From query history (observed) and column naming (candidate). Only many-to-one joins can be approved; approval checks the target key is unique.</p>
          {edges.filter(e => e.joins?.length).map(e => (
            <div key={`${e.source}-${e.target}`} className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs">{e.source} → {e.target} on {e.joins![0].left_column} = {e.joins![0].right_column} <Badge variant="outline">{e.evidence === "observed" ? `history ×${e.count}` : "naming"}</Badge></span>
              {canApprove && (
                <span className="flex shrink-0 gap-1">
                  <Button size="sm" variant="outline" onClick={() => void approve(e, false)}>Approve</Button>
                  <Button size="sm" variant="ghost" onClick={() => void approve(e, true)}>Approve reversed</Button>
                </span>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

export default function Page() {
  return (
    <CapabilityGate capability="query">
      <MetricsPage />
    </CapabilityGate>
  )
}
