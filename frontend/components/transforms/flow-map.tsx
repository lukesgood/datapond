"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { Loader2, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ChoiceGroup } from "@/components/ui/choice-group"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { Input } from "@/components/ui/input"
import { SourceState } from "@/components/ui/source-state"
import {
  NODE_H, NODE_W, edgePath, filterFlow, layout, needsAttention, neighbours, stateText,
  type Flow, type FlowNode,
} from "@/lib/flow-map"
import { ago } from "@/lib/notebooks"
import { parseCron } from "@/lib/schedule"
import { readJson, sourceStatus } from "@/lib/source-state"
import { useToast } from "@/lib/toast"

const TONE: Record<string, string> = {
  failed: "var(--destructive)", stale: "var(--dp-warn)", running: "var(--primary)",
  live: "var(--dp-good)", ok: "var(--dp-good)", never: "var(--muted-foreground)", external: "var(--muted-foreground)",
}
const EDGE: Record<string, { stroke: string; dash?: string; width: number }> = {
  sync: { stroke: "var(--muted-foreground)", width: 1.5 },
  stream: { stroke: "var(--primary)", dash: "5 4", width: 1.8 },
  transform: { stroke: "var(--foreground)", width: 1.4 },
}

function label(flow: Flow, id: string) {
  const n = flow.nodes.find(x => x.id === id)
  return n ? (n.kind === "table" ? n.id : n.name) : id
}

/** Every source, stream and table DataPond moves data between, and the transforms
 *  that build one table from others. Drawn from what exists; nothing here is unsaved. */
export function FlowMap({ canWrite }: { canWrite: boolean }) {
  const router = useRouter()
  const { toast } = useToast()
  const [flow, setFlow] = useState<Flow | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [attention, setAttention] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [running, setRunning] = useState(false)

  const load = useCallback(async () => {
    try {
      setFlow(await readJson<Flow>(await fetch("/api/transforms/flow")))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed")
    }
  }, [])
  useEffect(() => {
    const t = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(t)
  }, [load])

  const shown = useMemo(() => (flow ? filterFlow(flow, query, attention) : null), [flow, query, attention])
  const geo = useMemo(() => (shown ? layout(shown) : null), [shown])
  const pos = useMemo(() => new Map((geo?.placed ?? []).map(p => [p.id, p])), [geo])
  const node = flow?.nodes.find(n => n.id === selected) ?? null
  const attentionCount = flow ? flow.nodes.filter(needsAttention).length : 0
  const tables = flow ? flow.nodes.filter(n => n.kind === "table").length : 0
  const status = sourceStatus({ loading: flow === null, error, empty: tables === 0, hasData: !!flow && tables > 0 })
  // A selection keeps its lines highlighted, so the path through it reads at a glance.
  const lit = useMemo(() => {
    if (!flow || !selected) return new Set<string>()
    return new Set(flow.edges.filter(e => e.from === selected || e.to === selected).map(e => `${e.from}>${e.to}`))
  }, [flow, selected])

  const newFrom = (n: FlowNode) => {
    const sp = new URLSearchParams({ tab: "transforms", edit: "new", from: n.id })
    router.push(`/pipelines?${sp.toString()}`)
  }

  const runNow = async (n: FlowNode) => {
    if (n.written_by?.kind !== "transform") return
    setRunning(true)
    try {
      await readJson(await fetch(`/api/transforms/${encodeURIComponent(n.written_by.ref)}/trigger`, { method: "POST" }))
      toast(`Run started: ${n.written_by.name}`, "info")
    } catch (e) {
      toast(`Could not start ${n.written_by.name}: ${e instanceof Error ? e.message : "failed"}`, "error")
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="flex flex-wrap items-start gap-5">
      <section className="min-w-0 flex-[3_1_640px] overflow-hidden rounded-xl border bg-card">
        <div className="flex flex-wrap items-center gap-2.5 border-b px-3.5 py-3">
          <Input aria-label="Find a table" placeholder="Find a table" value={query} onChange={e => setQuery(e.target.value)} className="h-8 min-w-0 flex-[1_1_180px]" />
          <ChoiceGroup<boolean> label="Show" value={attention} onChange={setAttention}
            options={[{ label: `All · ${tables}`, value: false }, { label: `Needs attention · ${attentionCount}`, value: true, disabled: attentionCount === 0 }]} />
          <div className="ml-auto flex flex-wrap gap-3 text-xs text-muted-foreground" aria-hidden>
            {(["sync", "stream", "transform"] as const).map(k => (
              <span key={k} className="inline-flex items-center gap-1.5">
                <svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke={EDGE[k].stroke} strokeWidth="2" strokeDasharray={EDGE[k].dash} /></svg>{k}
              </span>
            ))}
          </div>
        </div>

        <SourceState status={status} what="the data flow" error={error} onRetry={() => void load()}
          empty={
            <div className="px-5 py-10 text-center">
              <p className="text-sm font-medium">Nothing to draw yet</p>
              <p className="mt-1 text-xs text-muted-foreground">The map shows tables a source syncs, a stream writes or a transform builds. Add a source or a transform and it appears here.</p>
            </div>
          }>
          {geo && shown && (
            <div className="overflow-auto p-3.5">
              <div className="relative" style={{ width: geo.width, height: 26 }}>
                {geo.columns.map(c => (
                  <span key={c.x} className="absolute top-1 text-xs font-semibold text-muted-foreground" style={{ left: c.x }}>{c.label || "tables"}</span>
                ))}
              </div>
              <div className="relative" style={{ width: geo.width, height: geo.height }}>
                {geo.columns.slice(1).map(c => (
                  <div key={c.x} aria-hidden className="absolute rounded-lg bg-muted/40" style={{ left: c.x - 10, width: NODE_W + 20, top: 0, bottom: 0 }} />
                ))}
                <svg width={geo.width} height={geo.height} className="absolute left-0 top-0" role="img"
                     aria-label={`${shown.edges.length} connections. ${shown.edges.slice(0, 20).map(e => `${label(shown, e.from)} to ${label(shown, e.to)} by ${e.kind}${e.via ? ` ${e.via}` : ""}`).join("; ")}`}>
                  {shown.edges.map(e => {
                    const a = pos.get(e.from), b = pos.get(e.to)
                    if (!a || !b) return null
                    const on = lit.has(`${e.from}>${e.to}`)
                    const st = EDGE[e.kind]
                    return <path key={`${e.from}>${e.to}`} d={edgePath(a, b)} fill="none"
                                 stroke={on ? "var(--primary)" : st.stroke} strokeWidth={on ? 3 : st.width}
                                 strokeDasharray={st.dash} opacity={selected && !on ? 0.35 : 1} />
                  })}
                </svg>
                {geo.placed.map(n => {
                  const isSel = n.id === selected
                  const tone = n.kind === "table" ? TONE[n.state ?? "ok"] : undefined
                  return (
                    <div key={n.id} className="absolute" style={{ left: n.x, top: n.y, width: NODE_W, height: NODE_H }}>
                      <button type="button" aria-pressed={isSel} onClick={() => setSelected(isSel ? null : n.id)}
                              className={`flex h-full w-full flex-col justify-center gap-0.5 rounded-lg border px-2.5 text-left transition-shadow ${n.kind === "table" ? "bg-card" : "bg-muted/60"} ${isSel ? "border-2 border-primary shadow-[0_0_0_4px_color-mix(in_oklab,var(--primary)_15%,transparent)]" : n.state === "failed" ? "border-destructive/50" : n.state === "stale" || n.stale_input?.length ? "border-[var(--dp-warn)]/60" : ""}`}>
                        <span className={`truncate text-sm ${n.kind === "table" ? "font-mono" : "font-semibold"}`}>{n.name}</span>
                        <span className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
                          {tone && <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: tone }} />}
                          <span className={n.state === "failed" ? "text-destructive" : ""}>{stateText(n, ago)}</span>
                          {n.kind === "table" && n.stale_input?.length && n.state !== "failed" ? <span>· stale input</span> : null}
                        </span>
                      </button>
                      {canWrite && n.kind === "table" && (
                        <button type="button" aria-label={`New transform reading ${n.id}`} title="New transform reading this table"
                                onClick={() => newFrom(n)}
                                className="absolute -right-2.5 -top-2.5 flex h-6 w-6 items-center justify-center rounded-full border bg-card text-primary hover:bg-primary/10">
                          <Plus className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </SourceState>
        <p className="border-t px-3.5 py-2.5 text-xs text-muted-foreground">
          Drawn from what exists: source syncs, streams, and the tables each transform reads and writes. Edit on the Transforms tab or on the source.
          {flow?.warnings?.length ? ` Partly drawn: ${flow.warnings.join("; ")}.` : ""}
        </p>
      </section>

      <ExplainRail label="Selected">
        {!node || !flow ? (
          <RailSection title="Pick a box">
            <p>A table shows what writes it, what it reads and what reads it, with its last run. “+” on a table starts a transform from it.</p>
          </RailSection>
        ) : (() => {
          const { reads, readBy } = neighbours(flow, node.id)
          const w = node.written_by
          return (
            <>
              <div>
                <p className="text-xs text-muted-foreground">{node.kind === "table" ? node.namespace : node.kind}</p>
                <h3 className={`text-lg font-semibold ${node.kind === "table" ? "font-mono" : ""}`}>{node.name}</h3>
              </div>
              {node.state === "failed" && (
                <RailAttention title={`Last run failed${node.at ? ` · ${ago(node.at)}` : ""}`} tone="bad">
                  The table still holds the previous run&apos;s rows.{readBy.length ? ` ${readBy.map(r => label(flow, r)).join(", ")} read${readBy.length === 1 ? "s" : ""} it.` : ""}
                </RailAttention>
              )}
              {node.state === "stale" && <RailAttention title="Not refreshed in over a day">{node.at ? `Last ${w?.kind === "sync" ? "sync" : "run"} ${ago(node.at)}.` : null}</RailAttention>}
              {node.stale_input?.length && node.state !== "failed" ? (
                <RailAttention title="Built from a stale input">{node.stale_input.join(", ")} failed or went stale; this table reflects its older rows.</RailAttention>
              ) : null}
              <dl className="grid grid-cols-[92px_minmax(0,1fr)] gap-x-2.5 gap-y-1.5 text-sm">
                {node.kind === "table" && <>
                  <dt className="text-muted-foreground">Written by</dt>
                  <dd>{w ? <>{w.name} <span className="text-muted-foreground">· {w.kind}{w.schedule ? ` · ${parseCron(w.schedule)}` : ""}</span></> : <span className="text-muted-foreground">nothing in DataPond</span>}</dd>
                </>}
                <dt className="text-muted-foreground">{node.kind === "table" ? "Reads" : "Feeds"}</dt>
                <dd className="font-mono text-xs">{(node.kind === "table" ? reads : readBy).map(r => label(flow, r)).join(", ") || "—"}</dd>
                {node.kind === "table" && <>
                  <dt className="text-muted-foreground">Read by</dt>
                  <dd className="font-mono text-xs">{readBy.map(r => label(flow, r)).join(", ") || "—"}</dd>
                </>}
              </dl>
              <div className="flex flex-wrap gap-2">
                {w?.kind === "transform" && canWrite && <>
                  <Button size="sm" onClick={() => router.push(`/pipelines?tab=transforms&edit=${encodeURIComponent(w.ref)}`)}>Edit transform</Button>
                  <Button size="sm" variant="outline" disabled={running} onClick={() => void runNow(node)}>
                    {running && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Run now
                  </Button>
                  {w.dag_id && <Button size="sm" variant="outline" onClick={() => router.push(`/pipelines/${encodeURIComponent(w.dag_id!)}`)}>Logs</Button>}
                </>}
                {(w?.kind === "sync" || node.kind === "source") && (
                  <Button size="sm" variant="outline" onClick={() => router.push(`/connectors/connections/${encodeURIComponent(w?.ref ?? node.ref ?? "")}`)}>Open source</Button>
                )}
                {(w?.kind === "stream" || node.kind === "stream") && <Button size="sm" variant="outline" onClick={() => router.push("/streaming")}>Open Streaming</Button>}
              </div>
              {node.kind === "table" && canWrite && (
                <RailSection title="Build on this table">
                  <p>Opens the transform editor reading <code className="font-mono text-foreground">{node.id}</code>.</p>
                  <Button size="sm" variant="outline" className="mt-1.5" onClick={() => newFrom(node)}>New transform from here</Button>
                </RailSection>
              )}
              {node.kind === "table" && (
                <RailSection title="Open in">
                  <p><Link className="text-primary hover:underline" href={`/catalog/${encodeURIComponent(node.namespace ?? "")}/${encodeURIComponent(node.name)}`}>Catalog</Link>{" · "}
                     <Link className="text-primary hover:underline" href={`/query?sql=${encodeURIComponent(`SELECT * FROM ${node.id} LIMIT 100`)}`}>Analytics</Link></p>
                </RailSection>
              )}
            </>
          )
        })()}
      </ExplainRail>
    </div>
  )
}
