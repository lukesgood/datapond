"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import ReactFlow, { Background, Controls, type Edge, type Node } from "reactflow"
import "reactflow/dist/style.css"
import { Check, Copy, Loader2, Search, Share2 } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import {
  egoLayout, hubs, neighbours, searchTables,
  type Neighbour, type RelGraph,
} from "@/lib/relationship-view"

// How many neighbours are drawn around the selected table; the list shows them all.
const DRAWN = 12

/** Relationships between catalog tables, read from one table at a time.
 *
 *  It used to draw every table on one ring with every join labelled, which past a
 *  dozen tables was a knot of crossing lines, with guesses from column naming mixed
 *  in with joins people ran. The question here is about one table — what does it join
 *  to, on what, how often — so the screen starts from a table: its neighbours ranked by
 *  observed use, drawn around it, guesses off unless asked for, and each join one click
 *  from a query.
 */
export function RelationshipGraph({ days = 30 }: { days?: number }) {
  const [graph, setGraph] = useState<RelGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [withCandidates, setWithCandidates] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/catalog/relationships?days=${days}`)
      if (res.ok) setGraph(await res.json())
    } catch {
      /* advisory view — never block the catalog on it */
    } finally {
      setLoading(false)
    }
  }, [days])

  // A fetch on mount that shows a spinner while it runs. `loading` starts true, so
  // the synchronous set inside `load` is a no-op, not a cascade.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  const top = useMemo(() => (graph ? hubs(graph, 10) : []), [graph])
  // Open on the most-connected table rather than an empty canvas.
  const current = selected ?? top[0]?.id ?? null
  const around = useMemo(
    () => (graph && current ? neighbours(graph, current, { includeCandidates: withCandidates }) : []),
    [graph, current, withCandidates])
  const hiddenCandidates = useMemo(
    () => (graph && current && !withCandidates
      ? neighbours(graph, current, { includeCandidates: true }).length - around.length
      : 0),
    [graph, current, withCandidates, around])
  const matches = useMemo(() => (graph ? searchTables(graph, query) : []), [graph, query])

  if (loading) {
    return (
      <div className="flex h-[360px] items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Finding relationships…
      </div>
    )
  }
  if (!graph || graph.nodes.length === 0 || top.length === 0) {
    return (
      <div className="flex h-[240px] flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
        <Share2 className="h-6 w-6 opacity-40" />
        <p>No table relationships to show.</p>
        <p className="text-xs">
          Running a join in Analytics adds an observed relationship here.
        </p>
      </div>
    )
  }

  const node = graph.nodes.find(n => n.id === current)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-64">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input value={query} onChange={e => setQuery(e.target.value)}
                 placeholder="Find a table…" className="pl-8 h-9" aria-label="Find a table" />
        </div>
        <div className="flex items-center gap-2">
          <Checkbox id="rel-candidates" checked={withCandidates}
                    onCheckedChange={v => setWithCandidates(v === true)} />
          <Label htmlFor="rel-candidates" className="text-xs font-normal cursor-pointer">
            Include guesses from column names
          </Label>
        </div>
        <span className="text-xs text-muted-foreground">
          Joins from the last {graph.window_days ?? days} days
          {typeof graph.statements_scanned === "number" && ` · ${graph.statements_scanned} queries read`}
          {" · AI-generated queries excluded"}
        </span>
      </div>

      <div className="flex gap-3 min-h-[360px]">
        {/* Where to start: a search, or the tables most joins touch. */}
        <aside className="w-60 shrink-0 rounded-md border p-2 text-xs">
          {query.trim() ? (
            <>
              <p className="mb-1 px-1 text-2xs uppercase tracking-wide text-muted-foreground">
                Matches ({matches.length})
              </p>
              {matches.length === 0
                ? <p className="px-1 text-muted-foreground">No table matches.</p>
                : <TableList items={matches.map(m => ({ id: m.id, hint: `${m.query_count} queries` }))}
                             current={current} onPick={id => { setSelected(id); setQuery("") }} />}
            </>
          ) : (
            <>
              <p className="mb-1 px-1 text-2xs uppercase tracking-wide text-muted-foreground">
                Most connected
              </p>
              <TableList items={top.map(h => ({
                            id: h.id,
                            hint: h.observed > 0 ? `${h.observed} joins` : `${h.candidates} guesses`,
                          }))}
                         current={current} onPick={setSelected} />
            </>
          )}
        </aside>

        <div className="min-w-0 flex-1 space-y-3">
          {current && (
            <>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <p className="text-2xs uppercase tracking-wide text-muted-foreground">
                    {current.split(".")[0]}
                  </p>
                  <p className="text-sm font-medium">{current.split(".")[1]}</p>
                  <p className="text-xs text-muted-foreground">
                    {node && node.query_count > 0 ? `Used by ${node.query_count} queries` : "Not queried in this window"}
                    {" · "}{around.length} related
                    {hiddenCandidates > 0 && ` · ${hiddenCandidates} guesses hidden`}
                  </p>
                </div>
                <a href={`/catalog/${current.split(".")[0]}/${current.split(".")[1]}`}
                   className="text-xs text-primary hover:underline">
                  Open table →
                </a>
              </div>

              {around.length === 0 ? (
                <p className="rounded-md border p-4 text-xs text-muted-foreground">
                  No joins against this table were run in this window.
                  {hiddenCandidates > 0 && " Turn on guesses to see tables whose column names suggest a join."}
                </p>
              ) : (
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
                  <Neighbourhood center={current} around={around} onPick={setSelected} />
                  <NeighbourList around={around} onPick={setSelected} />
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function TableList({ items, current, onPick }: {
  items: { id: string; hint: string }[]
  current: string | null
  onPick: (id: string) => void
}) {
  return (
    <ul className="space-y-0.5">
      {items.map(it => (
        <li key={it.id}>
          <button type="button" onClick={() => onPick(it.id)}
                  aria-current={it.id === current}
                  className={`flex w-full items-baseline justify-between gap-2 rounded px-1.5 py-1 text-left hover:bg-muted ${it.id === current ? "bg-muted font-medium" : ""}`}>
            <span className="truncate font-mono text-2xs">{it.id}</span>
            <span className="shrink-0 text-2xs text-muted-foreground">{it.hint}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

/** The selected table and its first neighbours — no crossing edges, no labels on the
 *  canvas (the list beside it carries the join keys). Clicking a neighbour re-centres. */
function Neighbourhood({ center, around, onPick }: {
  center: string
  around: Neighbour[]
  onPick: (id: string) => void
}) {
  const { nodes: laid, hidden } = useMemo(() => egoLayout(center, around, DRAWN), [center, around])
  const nodes: Node[] = laid.map(n => ({
    id: n.id,
    position: n.position,
    data: { label: <span className="font-mono text-2xs">{n.id.split(".")[1]}</span> },
    style: {
      borderRadius: 6, padding: "4px 8px", cursor: n.id === center ? "default" : "pointer",
      background: "var(--card)", color: "var(--card-foreground)",
      border: n.id === center ? "2px solid var(--primary)" : "1px solid var(--border)",
    },
  }))
  const edges: Edge[] = around.slice(0, DRAWN).map(n => {
    const observed = n.evidence === "observed"
    return {
      id: `${center}-${n.other}`,
      source: center,
      target: n.other,
      // Solid, thicker for more use = people ran it. Dashed = a guess.
      style: observed
        ? { strokeWidth: Math.min(1 + Math.log2(n.count + 1), 4) }
        : { strokeWidth: 1, strokeDasharray: "4 3", opacity: 0.6 },
    }
  })
  return (
    <div className="h-[320px] rounded-md border">
      <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}
                 nodesDraggable={false}
                 onNodeClick={(_e, n) => { if (n.id !== center) onPick(n.id) }}>
        <Background gap={16} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
      {hidden > 0 && (
        <p className="px-2 pb-1 text-2xs text-muted-foreground">+{hidden} more in the list</p>
      )}
    </div>
  )
}

function NeighbourList({ around, onPick }: { around: Neighbour[]; onPick: (id: string) => void }) {
  return (
    <ul className="max-h-[320px] space-y-2 overflow-y-auto pr-1 text-xs">
      {around.map(n => <NeighbourRow key={n.other} n={n} onPick={onPick} />)}
    </ul>
  )
}

function NeighbourRow({ n, onPick }: { n: Neighbour; onPick: (id: string) => void }) {
  const [copied, setCopied] = useState(false)
  const observed = n.evidence === "observed"
  const copy = async () => {
    if (!n.joinSql) return
    try {
      await navigator.clipboard.writeText(n.joinSql)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard refused — the SQL is still one click away in Analytics */ }
  }
  return (
    <li className="rounded-md border p-2">
      <div className="flex items-baseline justify-between gap-2">
        <button type="button" onClick={() => onPick(n.other)}
                className="truncate text-left font-mono text-2xs text-primary hover:underline">
          {n.other}
        </button>
        <span className={`shrink-0 text-2xs ${observed ? "text-foreground" : "italic text-muted-foreground"}`}>
          {observed ? `run ${n.count}×` : "guess"}
        </span>
      </div>
      {n.on && <p className="mt-0.5 break-all font-mono text-2xs text-muted-foreground">{n.on}</p>}
      {!observed && n.reason && <p className="mt-0.5 text-2xs italic text-muted-foreground">{n.reason} — unverified</p>}
      {n.joinSql && (
        <div className="mt-1 flex gap-3">
          <a href={`/query?sql=${encodeURIComponent(n.joinSql)}`}
             className="text-2xs text-primary hover:underline">Open in Analytics →</a>
          <button type="button" onClick={copy}
                  className="inline-flex items-center gap-1 text-2xs text-muted-foreground hover:text-foreground">
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            {copied ? "Copied" : "Copy JOIN"}
          </button>
        </div>
      )}
    </li>
  )
}

