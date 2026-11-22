// frontend/app/metrics/page.tsx
"use client"

import { Suspense, useCallback, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { PageHeader } from "@/components/ui/page-header"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { MetricEditor, type TableRef } from "@/components/metrics/metric-editor"
import { JoinsPanel } from "@/components/metrics/joins-panel"
import { ConceptsPanel } from "@/components/metrics/concepts-panel"
import { CapabilityGate, useCapability } from "@/lib/capabilities"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"
import { responseErrorMessage } from "@/lib/auth"
import {
  approvalWarning, metricMatches, metricStatusBadge, pendingApproval, versionDiff,
  type CatalogEntry, type MetricDetail, type MetricSummary, type Viewer,
} from "@/lib/metrics"

const TONE = { ok: "secondary", draft: "outline", retired: "destructive" } as const

async function jsonOrThrow(res: Response, fallback: string) {
  if (!res.ok) throw new Error(await responseErrorMessage(res, fallback))
  return res.json()
}

function MetricsPage() {
  const { toast } = useToast()
  const confirm = useConfirm()
  const router = useRouter()
  const conceptsOn = useCapability("ontology")
  const asked = useSearchParams().get("tab")
  const tab = asked === "joins" ? "joins" : asked === "concepts" && conceptsOn ? "concepts" : "definitions"
  const setTab = (v: string) => router.replace(v === "definitions" ? "/metrics" : `/metrics?tab=${v}`, { scroll: false })
  const [metrics, setMetrics] = useState<MetricSummary[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [viewer, setViewer] = useState<Viewer>({ can_author: false, can_approve: false })
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<MetricDetail | null>(null)
  const [editing, setEditing] = useState<"new" | "version" | null>(null)
  const [showRetired, setShowRetired] = useState(false)
  const [search, setSearch] = useState("")
  const [catalogs, setCatalogs] = useState<CatalogEntry[]>([])
  const [tables, setTables] = useState<TableRef[] | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await jsonOrThrow(await fetch("/api/semantic/metrics"), "Could not load metrics")
      setMetrics(data.metrics); setViewer(data.viewer); setLoadError(null)
    } catch (e) { setLoadError(e instanceof Error ? e.message : "Could not load metrics"); setMetrics(m => m ?? []) }
  }, [])

  const open = useCallback(async (name: string) => {
    setSelected(name); setDetail(null)
    try {
      setDetail(await jsonOrThrow(await fetch(`/api/semantic/metrics/${encodeURIComponent(name)}`), "Could not load metric"))
    } catch (e) { toast(e instanceof Error ? e.message : "Could not load metric", "error") }
  }, [toast])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    fetch("/api/catalogs").then(r => (r.ok ? r.json() : { catalogs: [] }))
      .then(d => setCatalogs(d.catalogs ?? [])).catch(() => setCatalogs([]))
    fetch("/api/catalog/tables").then(r => (r.ok ? r.json() : { tables: [] }))
      .then(d => setTables(d.tables ?? [])).catch(() => setTables([]))
  }, [])

  // What "Approve vN" approves is the server's pending version, shown with its own SQL —
  // never the approved version's fields under a newer number.
  const pending = pendingApproval(detail)
  // What agents get now: the approved version the metric points at.
  const current = detail?.versions.find(v => v.version === detail.metric.version)
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
      toast(`${detail.metric.name} retired`, "success")
      await load(); setSelected(null); setDetail(null)
    } catch (e) { toast(e instanceof Error ? e.message : "Retire failed", "error") }
  }

  const all = metrics ?? []
  const retiredCount = all.filter(m => m.status === "retired").length
  const visible = (showRetired ? all : all.filter(m => m.status !== "retired")).filter(m => metricMatches(m, search))
  const retired = detail?.metric.status === "retired"
  const warn = detail ? approvalWarning(detail.partition_info) : null

  return (
    <div className="mx-auto max-w-[1400px] flex-1 space-y-5 p-8 pt-6">
      <PageHeader title="Metrics"
        description="Approved definitions that agents and people compute the same way. Every result cites the version and who approved it."
        actions={viewer.can_author && tab === "definitions" && (
          <Button onClick={() => { setEditing("new"); setSelected(null); setDetail(null) }}>New metric</Button>
        )} />
      <Tabs value={tab} onValueChange={v => setTab(String(v))}>
        <TabsList>
          <TabsTrigger value="definitions">Definitions</TabsTrigger>
          <TabsTrigger value="joins">Joins</TabsTrigger>
          {conceptsOn && <TabsTrigger value="concepts">Concepts</TabsTrigger>}
        </TabsList>
        <TabsContent value="definitions" className="mt-5">
          <div className="flex flex-wrap items-start gap-5">
            <nav aria-label="Metrics" className="min-w-[220px] flex-[0_1_260px] space-y-2 rounded-xl border bg-card p-3">
              <Input aria-label="Search metrics" value={search} onChange={e => setSearch(e.target.value)}
                     placeholder={metrics ? `Search ${all.length - retiredCount} metrics` : "Search metrics"} />
              {retiredCount > 0 && (
                <label className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
                  <input type="checkbox" checked={showRetired} onChange={e => setShowRetired(e.target.checked)} />
                  Show retired ({retiredCount})
                </label>
              )}
              {metrics === null ? <p className="px-1 py-4 text-sm text-muted-foreground">Loading…</p>
                : loadError ? <p className="px-1 py-4 text-sm text-destructive">{loadError} <button className="underline" onClick={() => void load()}>Retry</button></p>
                : visible.length === 0 ? (
                  <p className="px-1 py-4 text-sm text-muted-foreground">
                    {all.length === 0 ? (viewer.can_author ? "No metrics yet. Use New metric to define the first." : "No metrics yet.")
                      : search ? "No metric matches." : "No active metrics. Tick Show retired to see the rest."}
                  </p>
                ) : (
                  <ul className="space-y-0.5">
                    {visible.map(m => {
                      const b = metricStatusBadge(m)
                      const on = selected === m.name && editing !== "new"
                      return (
                        <li key={m.name}>
                          <button aria-current={on ? "true" : undefined}
                                  className={`w-full rounded-lg px-2.5 py-2 text-left hover:bg-muted ${on ? "bg-primary/10" : ""}`}
                                  onClick={() => { setEditing(null); void open(m.name) }}>
                            <div className="flex items-center justify-between gap-2">
                              <span className="truncate text-sm font-semibold">{m.label}</span>
                              <Badge variant={TONE[b.tone]}>{b.label}</Badge>
                            </div>
                            <div className="truncate font-mono text-xs text-muted-foreground">{m.name}</div>
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                )}
            </nav>

            {editing ? (
              <MetricEditor key={`${editing}-${detail?.metric.name ?? ""}`} mode={editing} base={editing === "version" ? detail : null}
                catalogs={catalogs} tables={tables}
                onDone={async name => { setEditing(null); await load(); await open(name) }}
                onCancel={() => setEditing(null)} />
            ) : detail ? (
              <>
                <section className="min-w-0 flex-[3_1_440px] space-y-4 rounded-xl border bg-card p-5 text-sm">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="text-base font-semibold">{detail.metric.label} <span className="font-mono text-sm font-normal text-muted-foreground">{detail.metric.name}</span></h2>
                      <p className="text-xs text-muted-foreground">
                        {detail.metric.synonyms.length ? `Also called ${detail.metric.synonyms.join(", ")} · ` : ""}{detail.recent_queries} queries in 30 days · owner {detail.metric.owner_name ?? "—"}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {viewer.can_author && !retired && <Button size="sm" variant="outline" onClick={() => setEditing("version")}>New version</Button>}
                      {viewer.can_approve && pending && !retired && <Button size="sm" onClick={() => void approve()}>Approve v{pending.version}</Button>}
                      {viewer.can_approve && !retired && <Button size="sm" variant="ghost" onClick={() => void retire()}>Retire…</Button>}
                    </div>
                  </div>
                  {retired && <p className="rounded-md border bg-muted/40 p-2 text-xs">Retired: agents no longer see it. Its versions stay so past citations resolve.</p>}
                  {current ? (
                    <dl className="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-3 gap-y-1.5">
                      <dt className="text-muted-foreground">Approved version</dt><dd>v{current.version}{current.approved_by_name ? `, by ${current.approved_by_name}` : ""}</dd>
                      <dt className="text-muted-foreground">Measure</dt><dd className="font-mono">{current.measure}</dd>
                      <dt className="text-muted-foreground">Base table</dt><dd className="font-mono">{current.catalog}.{current.base_table}</dd>
                      <dt className="text-muted-foreground">Only rows where</dt><dd className="font-mono">{current.filters ?? "—"}</dd>
                      <dt className="text-muted-foreground">Time</dt>
                      <dd className="font-mono">{current.time_column
                        ? `${current.time_column} · ${current.grains.join(", ") || "no grouping"} · up to ${current.max_period_days} days`
                        : "none — computed over all rows"}</dd>
                      <dt className="text-muted-foreground">Split by</dt>
                      <dd className="font-mono">{current.dimensions.length
                        ? current.dimensions.map(d => `${d.name} (${d.join ? `${d.join.to_table}.` : ""}${d.column})`).join(", ")
                        : "—"}</dd>
                    </dl>
                  ) : (
                    <p className="text-muted-foreground">No approved version yet: agents do not see this metric.</p>
                  )}
                  {pending && pending.version !== detail.metric.version && (
                    <div className="space-y-1 rounded-lg border border-dashed p-3">
                      <h3 className="font-semibold">Waiting for approval: v{pending.version}</h3>
                      <dl className="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-3 gap-y-1">
                        <dt className="text-muted-foreground">Measure</dt><dd className="font-mono">{pending.measure}</dd>
                        <dt className="text-muted-foreground">Base table</dt><dd className="font-mono">{pending.catalog}.{pending.base_table}</dd>
                        <dt className="text-muted-foreground">Only rows where</dt><dd className="font-mono">{pending.filters ?? "—"}</dd>
                      </dl>
                      {pending.example_sql && <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs">{pending.example_sql}</pre>}
                    </div>
                  )}
                  <div className="border-t pt-3">
                    <h3 className="mb-2 font-semibold">Versions</h3>
                    <ol className="space-y-2">
                      {detail.versions.map((v, i) => (
                        <li key={v.version} className="rounded-lg border p-2.5">
                          <div className="flex flex-wrap justify-between gap-2 text-xs">
                            <span><strong>v{v.version}</strong> · {v.created_by_name ?? "—"} · {v.change_note || "no note"}</span>
                            <span className={v.approved_at ? "" : "text-muted-foreground"}>{v.approved_at ? `approved by ${v.approved_by_name}` : "not approved"}</span>
                          </div>
                          <ul className="mt-1 font-mono text-xs text-muted-foreground">
                            {versionDiff(detail.versions[i + 1], v).map(line => <li key={line}>{line}</li>)}
                          </ul>
                        </li>
                      ))}
                    </ol>
                  </div>
                </section>
                <ExplainRail label="How agents compute it">
                  {detail.broken && <RailAttention title="Broken" tone="bad">{detail.broken_reason}</RailAttention>}
                  <RailSection title={current ? `What agents run (v${current.version})` : "Example SQL"}>
                    {detail.example_sql
                      ? <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border bg-background p-2 text-xs text-foreground">{detail.example_sql}</pre>
                      : <p>Shown once a version is approved.</p>}
                  </RailSection>
                  <RailSection title="Where it is used">
                    Agents call it with <span className="font-mono">metric_query</span>; people use it from Analytics when a query matches. Each answer cites &ldquo;{detail.metric.name}{current ? ` v${current.version}` : ""}&rdquo;.
                  </RailSection>
                  {warn && <RailAttention title="Partitioning unknown">{warn}</RailAttention>}
                </ExplainRail>
              </>
            ) : (
              <ExplainRail label="About metrics" className="flex-[5_1_560px]">
                <RailSection title="Select a metric">
                  {selected ? "Loading…" : "Pick one on the left to see its definition, versions and the SQL agents run."}
                </RailSection>
                <RailSection title="How a metric changes">
                  Authors save drafts; an administrator approves a version. Agents always get the approved one, and every result names it.
                  {!viewer.can_author && <p className="mt-1">You can read metrics. Writing drafts needs governance:write.</p>}
                </RailSection>
              </ExplainRail>
            )}
          </div>
        </TabsContent>
        <TabsContent value="joins" className="mt-5">
          <JoinsPanel canApprove={viewer.can_approve} catalogs={catalogs} />
        </TabsContent>
        {conceptsOn && (
          <TabsContent value="concepts" className="mt-5">
            <ConceptsPanel catalogs={catalogs} tables={tables} />
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}

export default function Page() {
  return (
    <CapabilityGate capability="query">
      <Suspense><MetricsPage /></Suspense>
    </CapabilityGate>
  )
}
