"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import ReactFlow, { Background, Controls, type Edge, type Node } from "reactflow"
import "reactflow/dist/style.css"
import { Loader2, Share2 } from "lucide-react"

type GraphEdge = {
  source: string
  target: string
  count: number
  evidence: "observed" | "candidate"
  reason?: string
  join_sql?: string
  joins: { left_column: string; right_column: string; count: number }[]
}
type GraphColumn = { name: string; type: string }
type GraphNode = { id: string; query_count: number; columns: GraphColumn[] }
type Selection =
  | { kind: "node"; node: GraphNode }
  | { kind: "edge"; edge: GraphEdge }
  | null
type Graph = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  statements_scanned: number
  window_days: number
  tables_inspected?: number
}

/** Lay nodes on a circle: the graph is small and undirected, and a ring keeps every
 *  edge visible without a force simulation. */
function ring(nodes: GraphNode[], selectedId?: string): Node[] {
  const n = nodes.length
  const radius = Math.max(160, n * 42)
  return nodes.map((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(n, 1) - Math.PI / 2
    const [schema, table] = node.id.split(".")
    return {
      id: node.id,
      position: { x: radius * Math.cos(angle), y: radius * Math.sin(angle) },
      data: {
        label: (
          <div className="text-left leading-tight">
            <div className="text-[9px] uppercase tracking-wide opacity-60">{schema}</div>
            <div className="text-[12px] font-medium">{table}</div>
            <div className="text-[9px] opacity-60">
              {node.query_count > 0 ? `${node.query_count} queries` : "not queried"}
            </div>
          </div>
        ),
      },
      style: {
        borderRadius: 6,
        padding: "6px 10px",
        fontSize: 12,
        cursor: "pointer",
        background: "var(--card)",
        color: "var(--card-foreground)",
        // Selection has to be visible on the canvas, not only in the side pane.
        border: node.id === selectedId
          ? "2px solid var(--primary)"
          : "1px solid var(--border)",
      },
    }
  })
}

export function RelationshipGraph({ days = 30 }: { days?: number }) {
  const [graph, setGraph] = useState<Graph | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Selection>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/catalog/relationships?days=${days}`)
      if (res.ok) { setGraph(await res.json()); setSelected(null) }
    } catch {
      /* advisory view — never block the catalog on it */
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { void load() }, [load])

  const selectedNodeId = selected?.kind === "node" ? selected.node.id : undefined
  const selectedEdgeId = selected?.kind === "edge"
    ? `${selected.edge.source}-${selected.edge.target}`
    : undefined
  const nodes = useMemo(() => ring(graph?.nodes ?? [], selectedNodeId), [graph, selectedNodeId])
  const edges: Edge[] = useMemo(
    () =>
      (graph?.edges ?? []).map((e, i) => {
        const observed = e.evidence === "observed"
        const isSelected = `${e.source}-${e.target}` === selectedEdgeId
        const j = e.joins[0]
        return {
          id: `${e.source}-${e.target}-${i}`,
          source: e.source,
          target: e.target,
          label: j
            ? `${j.left_column} = ${j.right_column}${observed && e.count > 1 ? `  ×${e.count}` : ""}`
            : observed ? `×${e.count}` : "",
          labelStyle: {
            fontSize: 10,
            fill: observed ? "var(--foreground)" : "var(--muted-foreground)",
            fontStyle: observed ? "normal" : "italic",
          },
          labelBgStyle: { fill: "var(--background)" },
          data: { reason: e.reason },
          // Solid and thick = people ran it. Dashed and thin = we guessed from column
          // naming. The two must never be mistaken for each other.
          // A hairline is almost impossible to hit; reactflow's default 20px hit area
          // still missed on a curve. The visible stroke stays thin.
          interactionWidth: 30,
          style: {
            cursor: "pointer",
            ...(observed
              ? { strokeWidth: Math.min(1 + Math.log2(e.count + 1), 4) }
              : { strokeWidth: 1, strokeDasharray: "4 3", opacity: 0.65 }),
            ...(isSelected ? { stroke: "var(--primary)", strokeWidth: 3, opacity: 1 } : {}),
          },
          // No arrowhead: source/target are sorted alphabetically to make the edge
          // undirected, so an arrow would assert a direction the data never had.
          animated: false,
        }
      }),
    [graph, selectedEdgeId],
  )

  if (loading) {
    return (
      <div className="flex h-[420px] items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Finding relationships…
      </div>
    )
  }

  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="flex h-[420px] flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
        <Share2 className="h-6 w-6 opacity-40" />
        <p>No table relationships to show.</p>
        <p className="text-xs">
          The catalog has no tables, or no key-like columns were found to relate them.
          Running a join in Analytics adds an observed relationship here.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <svg width="22" height="8" aria-hidden><line x1="0" y1="4" x2="22" y2="4"
            stroke="currentColor" strokeWidth="2.5" /></svg>
          <b className="text-foreground">Observed</b> — joins people actually ran (thickness = frequency)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="22" height="8" aria-hidden><line x1="0" y1="4" x2="22" y2="4"
            stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3" opacity="0.7" /></svg>
          <i>Candidate</i> — inferred from column naming, unverified
        </span>
        <span>
          Last {graph.window_days} days · {graph.statements_scanned} queries
          {typeof graph.tables_inspected === "number" && ` · ${graph.tables_inspected} tables`}
          {" · AI-generated queries excluded"}
        </span>
      </div>
      <div className="flex h-[420px] gap-2">
        <div className="min-w-0 flex-1 rounded-md border">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            proOptions={{ hideAttribution: true }}
            onNodeClick={(_e, n) => {
              const found = graph.nodes.find(x => x.id === n.id)
              if (found) setSelected({ kind: "node", node: found })
            }}
            onEdgeClick={(_e, e) => {
              const found = graph.edges.find(
                (x, i) => `${x.source}-${x.target}-${i}` === e.id,
              )
              if (found) setSelected({ kind: "edge", edge: found })
            }}
            onPaneClick={() => setSelected(null)}
          >
            <Background gap={16} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <aside className="w-72 shrink-0 overflow-y-auto rounded-md border bg-muted/20 p-3 text-xs">
          {!selected ? (
            <p className="text-muted-foreground">
              Select a table or a relationship to see its detail.
            </p>
          ) : selected.kind === "node" ? (
            <NodeDetail node={selected.node} graph={graph} />
          ) : (
            <EdgeDetail edge={selected.edge} />
          )}
        </aside>
      </div>
    </div>
  )
}

function DetailHeading({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">{children}</p>
  )
}

function NodeDetail({ node, graph }: { node: GraphNode; graph: Graph }) {
  const [schema, table] = node.id.split(".")
  const related = graph.edges.filter(e => e.source === node.id || e.target === node.id)

  return (
    <div className="space-y-3">
      <div>
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{schema}</p>
        <p className="font-medium text-sm">{table}</p>
        <p className="text-muted-foreground">
          {node.query_count > 0
            ? `Used by ${node.query_count} ${node.query_count === 1 ? "query" : "queries"}`
            : "Not queried in this window"}
        </p>
      </div>

      {node.columns.length > 0 && (
        <div>
          <DetailHeading>Columns ({node.columns.length})</DetailHeading>
          <ul className="space-y-0.5 font-mono text-[11px]">
            {node.columns.map(c => (
              <li key={c.name} className="flex justify-between gap-2">
                <span className="truncate">{c.name}</span>
                <span className="shrink-0 text-muted-foreground">{c.type}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <DetailHeading>Relationships ({related.length})</DetailHeading>
        {related.length === 0 ? (
          <p className="text-muted-foreground">None found.</p>
        ) : (
          <ul className="space-y-1">
            {related.map((e, i) => {
              const other = e.source === node.id ? e.target : e.source
              const j = e.joins[0]
              return (
                <li key={`${other}-${i}`}>
                  <span className="font-mono text-[11px]">{other}</span>
                  <span className="ml-1 text-muted-foreground">
                    {j ? `on ${j.left_column} = ${j.right_column}` : ""}
                    {e.evidence === "observed" ? ` · ×${e.count}` : " · candidate"}
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <a
        href={`/catalog/${schema}/${table}`}
        className="inline-block text-[11px] text-primary hover:underline"
      >
        Open table →
      </a>
    </div>
  )
}

function EdgeDetail({ edge }: { edge: GraphEdge }) {
  const observed = edge.evidence === "observed"
  return (
    <div className="space-y-3">
      <div>
        <DetailHeading>Relationship</DetailHeading>
        <p className="font-mono text-[11px]">{edge.source}</p>
        <p className="font-mono text-[11px]">{edge.target}</p>
        <p className="mt-1">
          {observed ? (
            <span className="text-foreground">
              Observed — used by {edge.count} {edge.count === 1 ? "query" : "queries"}
            </span>
          ) : (
            <span className="text-muted-foreground italic">
              Candidate — {edge.reason || "inferred from column naming"}, unverified
            </span>
          )}
        </p>
      </div>

      <div>
        <DetailHeading>Join keys</DetailHeading>
        <ul className="space-y-0.5 font-mono text-[11px]">
          {edge.joins.map((j, i) => (
            <li key={i} className="flex justify-between gap-2">
              <span className="truncate">{j.left_column} = {j.right_column}</span>
              {observed && <span className="shrink-0 text-muted-foreground">×{j.count}</span>}
            </li>
          ))}
        </ul>
      </div>

      {edge.join_sql && (
        <div>
          <DetailHeading>Start from this</DetailHeading>
          <pre className="overflow-x-auto rounded border bg-background p-2 font-mono text-[10px] leading-relaxed">
{edge.join_sql}
          </pre>
          <a
            href={`/query?sql=${encodeURIComponent(edge.join_sql)}`}
            className="mt-1 inline-block text-[11px] text-primary hover:underline"
          >
            Open in Analytics →
          </a>
          <p className="mt-1 text-[10px] text-muted-foreground">
            Rebuilt from the join keys — never copied from a stored query, which can
            carry values in its WHERE clause.
          </p>
        </div>
      )}
    </div>
  )
}
