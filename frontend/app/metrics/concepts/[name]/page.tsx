"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import dynamic from "next/dynamic"
import { useParams } from "next/navigation"
import { ArrowLeft, Loader2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { PageHeader } from "@/components/ui/page-header"
import { CapabilityGate } from "@/lib/capabilities"
import { maskHref, type Binding, type Concept, type ConceptViewer, type PiiGap } from "@/lib/concepts"
import type { Flow } from "@/lib/flow-map"
import { tableHref } from "@/lib/relationship-view"
import {
  askSql, columnsByRole, conceptHref, conceptTables, impactUrl, metricsAcross, narrower, relatedConcepts, sourcesOf,
  type ImpactResponse,
} from "@/lib/concept-map"

const OntologyMap = dynamic(() => import("@/components/metrics/ontology-map").then(m => m.OntologyMap), { ssr: false })

type Data = { concepts: Concept[]; bindings: Binding[]; viewer: ConceptViewer }

function decoded(v: unknown): string {
  const s = Array.isArray(v) ? v[0] : String(v ?? "")
  try { return decodeURIComponent(s) } catch { return s }
}

/** GET a JSON document, or null when it is missing, refused or fails: every part of the
 *  page but the concept itself is optional. */
async function optional<T>(url: string): Promise<T | null> {
  try {
    const r = await fetch(url)
    return r.ok ? ((await r.json()) as T) : null
  } catch { return null }
}

/** One concept on one page (Data Map step 4): what it is, what it relates to, which
 *  columns hold it, where those rows come from, what measures it and what needs
 *  attention. Every line is derived from approved bindings, the flow map and the
 *  catalog's impact lookup. */
export default function ConceptPage() {
  return (
    <CapabilityGate capability="ontology">
      <ConceptPageInner />
    </CapabilityGate>
  )
}

function ConceptPageInner() {
  const name = decoded(useParams().name)
  const [data, setData] = useState<Data | null>(null)
  const [state, setState] = useState<"loading" | "ok" | "error">("loading")
  const [flow, setFlow] = useState<Flow | null>(null)
  const [gaps, setGaps] = useState<PiiGap[]>([])
  const [impact, setImpact] = useState<ImpactResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch("/api/semantic/concepts")
      .then(r => { if (!r.ok) throw new Error(); return r.json() })
      .then((d: Data) => { if (!cancelled) { setData(d); setState("ok") } })
      .catch(() => { if (!cancelled) setState("error") })
    void optional<Flow>("/api/transforms/flow").then(f => { if (!cancelled) setFlow(f) })
    void optional<{ gaps: PiiGap[] }>("/api/semantic/concepts/pii-gaps").then(g => { if (!cancelled) setGaps(g?.gaps ?? []) })
    return () => { cancelled = true }
  }, [])

  const concept = data?.concepts.find(c => c.name === name) ?? null
  const bindings = useMemo(() => data?.bindings ?? [], [data])
  const tables = useMemo(() => conceptTables(name, bindings), [name, bindings])
  const tablesKey = tables.join("|")
  useEffect(() => {
    if (!tablesKey) return
    let cancelled = false
    void optional<ImpactResponse>(impactUrl(tablesKey.split("|"))).then(r => { if (!cancelled) setImpact(r) })
    return () => { cancelled = true }
  }, [tablesKey])

  const back = (
    <Link href="/metrics?tab=concepts" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-3.5 w-3.5" />Concepts
    </Link>
  )
  if (state === "loading") {
    return <div className="mx-auto max-w-5xl space-y-4 px-6 py-6">{back}<p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading…</p></div>
  }
  if (state === "error" || !data) {
    return <div className="mx-auto max-w-5xl space-y-4 px-6 py-6">{back}<p className="text-sm text-destructive">Concepts could not be read.</p></div>
  }
  if (!concept) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 px-6 py-6">{back}
        <p className="text-sm text-muted-foreground">No concept is called “{name}”. It may have been renamed; pick it from the list.</p>
      </div>
    )
  }

  const related = relatedConcepts(name, bindings)
  const kids = narrower(name, data.concepts)
  const cols = columnsByRole(name, bindings)
  const from = sourcesOf(flow, tables)
  const measured = metricsAcross(impact)
  const dashboards = impact ? [...new Map(Object.values(impact.tables).flatMap(i => i.dashboards).map(d => [d.id, d])).values()] : []
  const calls = impact ? Object.values(impact.tables).reduce((n, i) => n + i.queries.calls, 0) : 0
  const myGaps = gaps.filter(g => g.concept === name)
  const waiting = bindings.filter(b => b.concept === name && b.status === "proposed").length
  const sql = askSql(name, bindings)
  const mapTable = cols.keys[0]?.table ?? tables[0]
  const short = (id: string) => id.split(".").slice(1).join(".")

  return (
    <div className="mx-auto max-w-5xl space-y-5 px-6 py-6">
      {back}
      <PageHeader
        title={concept.name}
        description={concept.description || "No description yet. Edit the concept in Semantic model → Concepts to say what it means."}
        actions={
          <div className="flex flex-wrap gap-2">
            {mapTable && (
              <Button size="sm" variant="outline" render={<Link href={`/catalog?table=${encodeURIComponent(mapTable)}&map=concepts`} />}>
                Show on map
              </Button>
            )}
            {sql && (
              <Button size="sm" render={<Link href={`/query?sql=${encodeURIComponent(sql)}`} />}>
                Ask in Analytics
              </Button>
            )}
          </div>
        }
      />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <dl className="space-y-4 rounded-xl border bg-card p-5 text-sm">
          <Row label="Is">
            <span className="flex flex-wrap items-center gap-1.5">
              {concept.pii ? <Badge variant="destructive">Personal data</Badge> : <span className="text-muted-foreground">Not personal data.</span>}
              {concept.parent && <>Part of <Link className="text-primary hover:underline" href={conceptHref(concept.parent)}>{concept.parent}</Link>.</>}
            </span>
            <span className="mt-1 block text-xs text-muted-foreground">Also called {concept.terms.length ? concept.terms.join(", ") : "nothing else yet"}.</span>
          </Row>
          <Row label="Related">
            {related.length === 0 ? <Empty>No other concept shares a table with it by key.</Empty> : (
              <ul className="space-y-0.5">
                {related.map(r => (
                  <li key={r.concept}>
                    <Link className="text-primary hover:underline" href={conceptHref(r.concept)}>{r.concept}</Link>
                    <span className="text-xs text-muted-foreground"> via {r.via.map(v => `${short(v.table)}.${v.column}`).join(", ")}</span>
                  </li>
                ))}
              </ul>
            )}
          </Row>
          <Row label="Narrower">
            {kids.length === 0 ? <Empty>None.</Empty> : (
              <span className="flex flex-wrap gap-1.5">
                {kids.map(k => <Link key={k.name} href={conceptHref(k.name)} className="rounded-full border px-2 py-0.5 text-xs hover:bg-muted">{k.name}</Link>)}
              </span>
            )}
          </Row>
          <Row label="Columns">
            {cols.keys.length + cols.attributes.length + cols.segments.length === 0 ? <Empty>Bound to no column yet.</Empty> : (
              <ul className="space-y-0.5 text-xs">
                {cols.keys.map(c => <ColumnItem key={`k${c.table}.${c.column}`} c={c} role="key" short={short} />)}
                {cols.attributes.map(c => <ColumnItem key={`a${c.table}.${c.column}`} c={c} role="attribute" short={short} />)}
                {cols.segments.map(c => <ColumnItem key={`s${c.table}.${c.column}.${c.filter_sql}`} c={c} role="segment" short={short} />)}
              </ul>
            )}
          </Row>
          <Row label="Comes from">
            {from.length === 0 ? <Empty>{tables.length ? "No sync or stream DataPond runs writes these tables." : "—"}</Empty> : (
              <ul className="space-y-0.5 text-xs">
                {from.map(f => <li key={`${f.table}<${f.from}`}><span className="font-mono">{f.from}</span> → <span className="font-mono">{short(f.table)}</span> <span className="text-muted-foreground">({f.kind})</span></li>)}
              </ul>
            )}
          </Row>
          <Row label="Metrics on its tables">
            {measured.length === 0 ? <Empty>{impact ? "No approved metric is built on these tables." : "—"}</Empty> : (
              <span className="flex flex-wrap gap-1.5">
                {measured.map(m => <Link key={m.name} href="/metrics" className="rounded border px-1.5 py-0.5 font-mono text-xs hover:bg-muted">{m.name}{m.version ? ` v${m.version}` : ""}</Link>)}
              </span>
            )}
            {(dashboards.length > 0 || calls > 0) && (
              <span className="mt-1 block text-xs text-muted-foreground">
                {dashboards.length > 0 && <>Read by {dashboards.length === 1 ? "1 dashboard" : `${dashboards.length} dashboards`}. </>}
                {calls > 0 && <>Its tables were queried {calls}× in the last {impact?.days ?? 30} days.</>}
              </span>
            )}
          </Row>
          <Row label="Attention">
            {myGaps.length === 0 && waiting === 0 && !(cols.keys.length + cols.attributes.length + cols.segments.length === 0) ? <Empty>Nothing.</Empty> : (
              <ul className="space-y-0.5 text-xs">
                {myGaps.map(g => (
                  <li key={`${g.table}.${g.column}`}>
                    <span className="font-mono">{g.table}.{g.column}</span>: personal data with no column mask.{" "}
                    <Link href={maskHref(g)} className="underline underline-offset-2">Review mask</Link>
                  </li>
                ))}
                {waiting > 0 && <li>{waiting === 1 ? "1 binding waits" : `${waiting} bindings wait`} for an administrator in Concepts.</li>}
                {cols.keys.length + cols.attributes.length + cols.segments.length === 0 && <li>Bound to no column, so search and agents cannot use it.</li>}
              </ul>
            )}
          </Row>
        </dl>

        <section aria-label="Concept map" className="space-y-2 rounded-xl border bg-card p-4">
          <h2 className="text-sm font-semibold">On the map</h2>
          <OntologyMap concepts={data.concepts} bindings={bindings} centre={name} height={360} />
        </section>
      </div>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-3">
      <dt className="pt-0.5 text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  )
}

const Empty = ({ children }: { children: React.ReactNode }) => <span className="text-xs text-muted-foreground">{children}</span>

function ColumnItem({ c, role, short }: { c: { table: string; column: string; filter_sql: string | null }; role: string; short: (id: string) => string }) {
  return (
    <li>
      <Link href={tableHref(c.table)} className="font-mono text-primary hover:underline">{short(c.table)}</Link>
      <span className="font-mono">.{c.column}</span>
      <span className="text-muted-foreground"> · {role}{c.filter_sql ? `: ${c.filter_sql}` : ""}</span>
    </li>
  )
}
