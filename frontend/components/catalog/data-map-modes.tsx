"use client"

import { useEffect, useMemo, useState } from "react"
import NextLink from "next/link"
import ReactFlow, { Background, Controls, MarkerType, Position, type Edge, type Node } from "reactflow"
import { Loader2 } from "lucide-react"
import type { Flow } from "@/lib/flow-map"
import type { Binding, Concept } from "@/lib/concepts"
import { conceptsAround, lineageAround, lineageLayout, schemaNeighbours, type LineageNode } from "@/lib/data-map"
import { displayId, splitTableId, tableHref, type Neighbour } from "@/lib/relationship-view"
import { keyBadges, snapshotLabel, type Snapshot, type TableKeys } from "@/lib/table-profile"
import { ColumnDrill } from "@/components/catalog/column-drill"
import { conceptHref, impactLines, impactUrl, type Impact, type ImpactResponse } from "@/lib/concept-map"

type Loaded<T> = { data: T | null; loading: boolean; failed: boolean }

/** GET a JSON document once per `url`; a failure is reported, not passed off as empty. */
function useJson<T>(url: string | null): Loaded<T> {
  const [state, setState] = useState<Loaded<T> & { url: string | null }>({ data: null, loading: !!url, failed: false, url })
  useEffect(() => {
    if (!url) return
    let cancelled = false
    const t = window.setTimeout(() => {
      setState({ data: null, loading: true, failed: false, url })
      fetch(url)
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
        .then((d: T) => { if (!cancelled) setState({ data: d, loading: false, failed: false, url }) })
        .catch(() => { if (!cancelled) setState({ data: null, loading: false, failed: true, url }) })
    }, 0)
    return () => { cancelled = true; window.clearTimeout(t) }
  }, [url])
  return state.url === url ? state : { data: null, loading: !!url, failed: false }
}

const Busy = ({ what }: { what: string }) => (
  <div className="flex h-[200px] items-center justify-center text-sm text-muted-foreground">
    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> {what}
  </div>
)
const Note = ({ children }: { children: React.ReactNode }) => (
  <p className="rounded-md border p-4 text-xs text-muted-foreground">{children}</p>
)

// ── Lineage ─────────────────────────────────────────────────────────────────────

const KIND_LABEL: Record<string, string> = { source: "source", stream: "stream", table: "table" }
const STATE_LABEL: Record<string, string> = {
  ok: "fresh", failed: "last run failed", running: "running", stale: "stale", never: "never run", live: "live", external: "",
}

/** What feeds the centre and what it feeds: sync jobs, streams and transforms, from the
 *  flow map. Upstream on the left, downstream on the right. */
export function LineageView({ centre, sole, onPick }: { centre: string; sole: string | null; onPick: (id: string) => void }) {
  const flow = useJson<Flow>("/api/transforms/flow")
  const impact = useJson<ImpactResponse>(impactUrl([centre]))
  const lineage = useMemo(() => (flow.data ? lineageAround(flow.data, centre) : null), [flow.data, centre])
  const catalog = splitTableId(centre).catalog
  const mine = impact.data?.tables[centre.toLowerCase()] ?? null
  const days = impact.data?.days ?? 30
  const panel = <ImpactPanel impact={mine} days={days} loading={impact.loading} failed={impact.failed} />
  if (flow.loading) return <Busy what="Reading the flow map…" />
  if (flow.failed || !lineage) return <div className="space-y-3"><Note>The flow map could not be read.</Note>{panel}</div>
  if (!lineage.found) {
    return (
      <div className="space-y-3">
        <Note>
          Nothing DataPond runs writes this table or reads from it: no sync, stream or transform.
          It may be loaded from outside, or read live from its source.
        </Note>
        {panel}
      </div>
    )
  }
  const pos = lineageLayout(lineage.nodes)
  // What uses the table past the transforms, one summary node per kind, in a lane of its own.
  const uses = impactLines(mine, days)
  const lastLane = Math.max(0, ...lineage.nodes.map(n => n.lane))
  const usesX = (lastLane + 1) * (190 + 110)
  const centreY = pos[lineage.nodes.find(n => n.lane === 0)?.id ?? ""]?.y ?? 0
  const pickable = (n: LineageNode) => n.kind === "table" && n.lane !== 0 && !!catalog
  const nodes: Node[] = lineage.nodes.map(n => ({
    id: n.id,
    position: pos[n.id],
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    data: {
      label: (
        <div className="text-left">
          <p className="truncate font-mono text-2xs font-medium">{n.kind === "table" ? `${n.namespace}.${n.name}` : n.name}</p>
          <p className="text-2xs text-muted-foreground">
            {KIND_LABEL[n.kind]}{n.state && STATE_LABEL[n.state] ? ` · ${STATE_LABEL[n.state]}` : ""}
          </p>
        </div>
      ),
    },
    style: {
      width: 180, borderRadius: 6, padding: "4px 8px",
      cursor: pickable(n) ? "pointer" : "default",
      background: "var(--card)", color: "var(--card-foreground)",
      border: n.lane === 0 ? "2px solid var(--primary)"
        : n.state === "failed" || n.state === "stale" ? "1px solid var(--dp-warn)" : "1px solid var(--border)",
    },
  }))
  const centreId = lineage.nodes.find(n => n.lane === 0)?.id
  uses.forEach((u, i) => nodes.push({
    id: `uses:${u.kind}`,
    position: { x: usesX, y: centreY + (i - (uses.length - 1) / 2) * 64 },
    targetPosition: Position.Left,
    data: { label: (
      <div className="text-left">
        <p className="truncate text-2xs font-medium" title={u.text}>{u.text}</p>
        <p className="text-2xs text-muted-foreground">{u.kind}</p>
      </div>
    ) },
    style: { width: 240, borderRadius: 6, padding: "4px 8px", background: "var(--muted)", color: "var(--foreground)", border: "1px dashed var(--border)" },
  }))
  const edges: Edge[] = lineage.edges.map(e => ({
    id: `${e.from}>${e.to}`, source: e.from, target: e.to,
    // The sync's connection is the node on the left already; a transform's name is not.
    label: e.kind === "transform" && e.via ? e.via : e.kind,
    labelStyle: { fontSize: 10 }, labelBgPadding: [4, 2] as [number, number], labelBgStyle: { fill: "var(--card)" },
    markerEnd: { type: MarkerType.ArrowClosed },
    style: e.kind === "stream" ? { strokeDasharray: "4 3" } : undefined,
  }))
  if (centreId) for (const u of uses) edges.push({
    id: `${centreId}>uses:${u.kind}`, source: centreId, target: `uses:${u.kind}`,
    style: { strokeDasharray: "2 3" }, markerEnd: { type: MarkerType.ArrowClosed },
  })
  const up = lineage.nodes.filter(n => n.lane < 0).length
  const down = lineage.nodes.filter(n => n.lane > 0).length
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        {up} upstream · {down} downstream. Lines are what runs: a sync job, a stream, or a transform that reads one table and writes another.
        Grey boxes on the right are what uses the table: metrics, concepts, dashboards and queries.
      </p>
      <div className="h-[320px] rounded-md border">
        <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}
                   nodesDraggable={false} nodesConnectable={false}
                   onNodeClick={(_e, n) => {
                     const hit = lineage.nodes.find(x => x.id === n.id)
                     if (hit && pickable(hit)) onPick(`${catalog}.${hit.namespace}.${hit.name}`.toLowerCase())
                   }}>
          <Background gap={16} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {sole === null && catalog && (
        <p className="text-2xs text-muted-foreground">Tables downstream are shown in {catalog}; the flow map does not tell catalogs apart.</p>
      )}
      {panel}
    </div>
  )
}

/** What breaks if this table changes: everything recorded as depending on it. */
function ImpactPanel({ impact, days, loading, failed }: {
  impact: Impact | null; days: number; loading: boolean; failed: boolean
}) {
  if (loading) return <p className="text-xs text-muted-foreground">Looking up what uses this table…</p>
  if (failed) return <p className="text-xs text-muted-foreground">What uses this table could not be read.</p>
  if (!impact) return null
  const q = impact.queries
  const nothing = !impact.metrics.length && !impact.concepts.length && !impact.dashboards.length && !q.calls
  return (
    <section aria-label="What uses this table" className="rounded-md border p-3 text-xs">
      <h3 className="text-sm font-semibold">What uses this table</h3>
      <p className="mb-2 text-2xs text-muted-foreground">Check these before changing or dropping a column: they are what breaks.</p>
      {nothing ? (
        <p className="text-muted-foreground">Nothing recorded: no approved metric, concept binding or dashboard, and no query in the last {days} days.</p>
      ) : (
        <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-[110px_minmax(0,1fr)]">
          {impact.metrics.length > 0 && <>
            <dt className="text-muted-foreground">Metrics</dt>
            <dd className="flex flex-wrap gap-1.5">{impact.metrics.map(m => (
              <NextLink key={m.name} href="/metrics" className="rounded border px-1.5 font-mono hover:bg-muted">{m.name}{m.version ? ` v${m.version}` : ""}</NextLink>
            ))}</dd>
          </>}
          {impact.concepts.length > 0 && <>
            <dt className="text-muted-foreground">Concepts</dt>
            <dd className="space-y-0.5">{impact.concepts.map(c => (
              <p key={`${c.concept}.${c.column}.${c.filter_sql ?? ""}`}>
                <NextLink href={conceptHref(c.concept)} className="text-primary hover:underline">{c.concept}</NextLink>
                <span className="text-muted-foreground"> · {c.role === "filter" ? `segment ${c.filter_sql}` : `${c.column} (${c.role})`}</span>
              </p>
            ))}</dd>
          </>}
          {impact.dashboards.length > 0 && <>
            <dt className="text-muted-foreground">Dashboards</dt>
            <dd className="flex flex-wrap gap-x-3">{impact.dashboards.map(d => (
              <NextLink key={d.id} href={`/dashboards/${d.id}`} className="text-primary hover:underline">{d.name}</NextLink>
            ))}</dd>
          </>}
          {q.calls > 0 && <>
            <dt className="text-muted-foreground">Queried</dt>
            <dd>
              {q.calls}× in the last {days} days by {q.people === 1 ? "1 person" : `${q.people} people`}
              {q.services > 0 && <> and {q.services === 1 ? "1 service key" : `${q.services} service keys`} ({q.service_calls}×)</>}.
              {q.callers.length > 0 && (
                <span className="block text-muted-foreground">
                  Most: {q.callers.map(c => `${c.name}${c.kind === "service" ? " (key)" : ""} ${c.calls}×`).join(", ")}
                </span>
              )}
            </dd>
          </>}
        </dl>
      )}
    </section>
  )
}

// ── Schema ──────────────────────────────────────────────────────────────────────

type Detail = { columns: { name: string; type: string }[]; row_count?: number | null }
type ConceptChips = Record<string, { concept: string; role: string }[]>

function detailUrl(id: string, part = "") {
  const { catalog, namespace, table } = splitTableId(id)
  const q = catalog ? `?catalog=${encodeURIComponent(catalog)}` : ""
  return `/api/catalog/tables/${encodeURIComponent(namespace)}/${encodeURIComponent(table)}${part}${q}`
}

function chipsFor(bindings: Binding[] | null, id: string): ConceptChips {
  const out: ConceptChips = {}
  for (const b of bindings ?? []) {
    if (b.status !== "approved" || `${b.catalog}.${b.namespace}.${b.table}`.toLowerCase() !== id.toLowerCase()) continue
    ;(out[b.column.toLowerCase()] ??= []).push({ concept: b.concept, role: b.role })
  }
  return out
}

const SHOWN_COLUMNS = 12

function SchemaCard({ id, centre, joinColumns, via, sole, bindings, onPick, snapshots, onColumn, drilled }: {
  id: string; centre: boolean; joinColumns: string[]; via: string; sole: string | null
  bindings: Binding[] | null; onPick: (id: string) => void; snapshots?: Snapshot[] | null
  onColumn: (table: string, column: string) => void; drilled: string | null
}) {
  const detail = useJson<Detail>(detailUrl(id))
  const keys = useJson<TableKeys>(detailUrl(id, "/keys"))
  const [all, setAll] = useState(false)
  // A keys answer of an unexpected shape (an older backend, a proxy page) must not take
  // the map down: no badges rather than a crash.
  const okKeys = keys.data && Array.isArray(keys.data.primary) && Array.isArray(keys.data.foreign) ? keys.data : null
  const badges = keyBadges(okKeys)
  const chips = chipsFor(bindings, id)
  const joins = new Set(joinColumns.map(c => c.toLowerCase()))
  const cols = Array.isArray(detail.data?.columns) ? detail.data.columns : []
  // Join, key and concept columns first: they are what the ERD is for.
  const ranked = [...cols].sort((a, b) => {
    const w = (c: { name: string }) => (joins.has(c.name.toLowerCase()) ? 0 : badges[c.name.toLowerCase()] ? 1 : chips[c.name.toLowerCase()] ? 2 : 3)
    return w(a) - w(b)
  })
  const shown = all ? ranked : ranked.slice(0, SHOWN_COLUMNS)
  return (
    <section aria-label={`Schema of ${displayId(id, sole)}`}
             className={`rounded-md border bg-card p-3 text-xs ${centre ? "border-primary/60 ring-1 ring-primary/30" : ""}`}>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        {centre
          ? <p className="truncate font-mono font-semibold">{displayId(id, sole)}</p>
          : <button type="button" onClick={() => onPick(id)} className="truncate text-left font-mono font-semibold text-primary hover:underline">{displayId(id, sole)}</button>}
        <NextLink href={tableHref(id)} className="shrink-0 text-2xs text-muted-foreground hover:text-foreground hover:underline">Open</NextLink>
      </div>
      {!centre && via && <p className="mb-1.5 break-all font-mono text-2xs text-muted-foreground">{displayId(via, sole)}</p>}
      {detail.loading ? <p className="text-muted-foreground">Reading columns…</p>
        : detail.failed ? <p className="text-muted-foreground">Columns could not be read.</p>
        : (
          <ul className="space-y-0.5">
            {shown.map(c => {
              const k = c.name.toLowerCase()
              return (
                <li key={c.name} className="flex flex-wrap items-baseline gap-1.5">
                  <button type="button" onClick={() => onColumn(id, c.name)} title="Values, meaning and joins of this column"
                          aria-pressed={drilled === c.name}
                          className={`font-mono hover:underline ${joins.has(k) ? "font-semibold text-primary" : ""} ${drilled === c.name ? "rounded bg-primary/10 px-0.5" : ""}`}>{c.name}</button>
                  <span className="text-2xs text-muted-foreground">{c.type}</span>
                  {(badges[k] ?? []).map(b => <span key={b.label} title={b.title} className="rounded bg-muted px-1 text-2xs font-medium">{b.label}</span>)}
                  {(chips[k] ?? []).map(ch => <span key={ch.concept + ch.role} title={`Bound to concept ${ch.concept} (${ch.role})`} className="rounded border px-1 text-2xs">{ch.concept}</span>)}
                </li>
              )
            })}
          </ul>
        )}
      {ranked.length > SHOWN_COLUMNS && (
        <button type="button" onClick={() => setAll(v => !v)} className="mt-1 text-2xs text-primary hover:underline">
          {all ? "Fewer columns" : `${ranked.length - SHOWN_COLUMNS} more columns`}
        </button>
      )}
      {centre && snapshots && snapshots.length > 0 && (
        <div className="mt-2 border-t pt-1.5">
          <p className="text-2xs font-medium text-muted-foreground">Snapshots</p>
          <ul className="text-2xs text-muted-foreground">{snapshots.slice(0, 4).map(s => <li key={s.at}>{snapshotLabel(s)}</li>)}</ul>
        </div>
      )}
    </section>
  )
}

/** An ERD of the centre and its nearest known neighbours (declared keys and joins people
 *  ran — never guesses): columns, PK/FK from the source, concept chips, and the columns
 *  that join each neighbour to the centre in bold. */
export function SchemaView({ centre, around, sole, bindings, onPick }: {
  centre: string; around: Neighbour[]; sole: string | null; bindings: Binding[] | null; onPick: (id: string) => void
}) {
  const s = useMemo(() => schemaNeighbours(centre, around), [centre, around])
  const profile = useJson<{ snapshots?: Snapshot[] }>(detailUrl(centre, "/profile"))
  const [drill, setDrill] = useState<{ table: string; column: string } | null>(null)
  const pick = (table: string, column: string) =>
    setDrill(d => (d && d.table === table && d.column === column ? null : { table, column }))
  const drilledOn = (id: string) => (drill && drill.table === id ? drill.column : null)
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        The table and {s.others.length ? `its ${s.others.length} nearest neighbour${s.others.length === 1 ? "" : "s"}` : "no known neighbours"}.
        Bold columns join to the centre; PK/FK come from the source database. Click a column for its values.
      </p>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <SchemaCard id={centre} centre joinColumns={s.centre.joinColumns} via="" sole={sole} bindings={bindings}
                    onPick={onPick} snapshots={profile.data?.snapshots ?? null} onColumn={pick} drilled={drilledOn(centre)} />
        {s.others.map(o => (
          <SchemaCard key={o.id} id={o.id} centre={false} joinColumns={o.joinColumns} via={o.via} sole={sole}
                      bindings={bindings} onPick={onPick} onColumn={pick} drilled={drilledOn(o.id)} />
        ))}
      </div>
      {drill && (
        <ColumnDrill key={`${drill.table}.${drill.column}`} tableId={drill.table} column={drill.column} sole={sole}
                     onClose={() => setDrill(null)} />
      )}
    </div>
  )
}

// ── Concepts ────────────────────────────────────────────────────────────────────

/** The business concepts this table's columns hold, and for each, the other tables
 *  that hold it — which is how two tables are logically related (both hold a key of
 *  고객), derived from approved bindings rather than drawn by hand. */
export function ConceptsView({ centre, sole, concepts, bindings, failed, onPick }: {
  centre: string; sole: string | null; concepts: Concept[] | null; bindings: Binding[] | null; failed: boolean
  onPick: (id: string) => void
}) {
  const here = useMemo(() => conceptsAround(concepts ?? [], bindings ?? [], centre), [concepts, bindings, centre])
  if (failed) return <Note>Concepts could not be read (they may be turned off for this deployment).</Note>
  if (!concepts || !bindings) return <Busy what="Reading concepts…" />
  if (here.length === 0) {
    return (
      <Note>
        No approved concept is bound to this table&apos;s columns. Bind one in{" "}
        <NextLink href="/metrics?tab=concepts" className="text-primary hover:underline">Semantic model → Concepts</NextLink>{" "}
        and it shows here, with the other tables that hold it.
      </Note>
    )
  }
  const conceptNodes = here.map((c, i) => ({ c, x: 200, y: (i - (here.length - 1) / 2) * 80 }))
  const tableNodes: { id: string; x: number; y: number; from: string }[] = []
  conceptNodes.forEach(({ c, y }) => {
    c.elsewhere.slice(0, 4).forEach((e, j) => {
      if (tableNodes.some(t => t.id === e.table)) return
      tableNodes.push({ id: e.table, x: 400, y: y + (j - Math.min(c.elsewhere.length - 1, 3) / 2) * 30, from: c.concept })
    })
  })
  const nodes: Node[] = [
    { id: "centre", position: { x: 0, y: 0 }, sourcePosition: Position.Right, targetPosition: Position.Left,
      data: { label: <span className="font-mono text-2xs font-semibold">{displayId(centre, sole)}</span> },
      style: { width: 170, borderRadius: 6, padding: "4px 8px", border: "2px solid var(--primary)", background: "var(--card)", color: "var(--card-foreground)" } },
    ...conceptNodes.map(({ c, x, y }) => ({
      id: `c:${c.concept}`, position: { x, y }, sourcePosition: Position.Right, targetPosition: Position.Left,
      data: { label: <span className="text-2xs font-medium">{c.concept}{c.pii ? " · PII" : ""}</span> },
      style: { width: 150, borderRadius: 999, padding: "4px 10px", border: "1px solid var(--primary)", background: "var(--muted)", color: "var(--foreground)" },
    })),
    ...tableNodes.map(t => ({
      id: t.id, position: { x: t.x, y: t.y }, sourcePosition: Position.Right, targetPosition: Position.Left,
      data: { label: <span className="font-mono text-2xs">{displayId(t.id, sole)}</span> },
      style: { width: 190, borderRadius: 6, padding: "2px 8px", border: "1px solid var(--border)", background: "var(--card)", color: "var(--card-foreground)", cursor: "pointer" },
    })),
  ]
  const edges: Edge[] = [
    ...here.map(c => ({ id: `centre>${c.concept}`, source: "centre", target: `c:${c.concept}`,
      label: c.here.map(h => h.role === "filter" ? `segment: ${h.filter_sql}` : h.column).join(", "), labelStyle: { fontSize: 9 } })),
    ...here.flatMap(c => c.elsewhere.slice(0, 4).map(e => ({ id: `${c.concept}>${e.table}`, source: `c:${c.concept}`, target: e.table,
      style: e.role === "key" ? undefined : { strokeDasharray: "4 3" } }))),
  ]
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Concepts this table holds (from approved bindings), and the other tables that hold the same concept.
        A solid line is a key; dashed is an attribute.
      </p>
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="h-[320px] rounded-md border">
          <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}
                     nodesDraggable={false} nodesConnectable={false}
                     onNodeClick={(_e, n) => { if (tableNodes.some(t => t.id === n.id)) onPick(n.id) }}>
            <Background gap={16} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <ul className="max-h-[320px] space-y-2 overflow-y-auto pr-1 text-xs">
          {here.map(c => (
            <li key={c.concept} className="rounded-md border p-2">
              <p className="font-medium"><NextLink href={conceptHref(c.concept)} className="hover:underline">{c.concept}</NextLink>{c.pii && <span className="ml-1.5 rounded bg-muted px-1 text-2xs">PII</span>}
                {c.parent && <span className="ml-1.5 text-2xs font-normal text-muted-foreground">in {c.parent}</span>}</p>
              <p className="text-2xs text-muted-foreground">
                Here: {c.here.map(h => h.role === "filter" ? `segment ${h.filter_sql}` : `${h.column} (${h.role})`).join(", ")}
              </p>
              {c.elsewhere.length > 0 ? (
                <p className="mt-0.5 text-2xs">
                  Also in:{" "}
                  {c.elsewhere.map((e, i) => (
                    <span key={e.table}>
                      {i > 0 && ", "}
                      <button type="button" onClick={() => onPick(e.table)} className="font-mono text-primary hover:underline">{displayId(e.table, sole)}</button>
                      <span className="text-muted-foreground">.{e.columns.join("/")}</span>
                    </span>
                  ))}
                </p>
              ) : <p className="mt-0.5 text-2xs text-muted-foreground">Only this table holds it.</p>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
