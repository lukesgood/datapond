"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import ReactFlow, { Background, Controls, MarkerType, type Edge, type Node } from "reactflow"
import "reactflow/dist/style.css"
import { Loader2, Share2 } from "lucide-react"

type GraphEdge = {
  source: string
  target: string
  count: number
  joins: { left_column: string; right_column: string; count: number }[]
}
type GraphNode = { id: string; query_count: number }
type Graph = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  statements_scanned: number
  window_days: number
}

/** Lay nodes on a circle: the graph is small and undirected, and a ring keeps every
 *  edge visible without a force simulation. */
function ring(nodes: GraphNode[]): Node[] {
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
            <div className="text-[9px] opacity-60">쿼리 {node.query_count}회</div>
          </div>
        ),
      },
      style: {
        borderRadius: 6,
        padding: "6px 10px",
        fontSize: 12,
        background: "hsl(var(--card))",
        color: "hsl(var(--card-foreground))",
        border: "1px solid hsl(var(--border))",
      },
    }
  })
}

export function RelationshipGraph({ days = 30 }: { days?: number }) {
  const [graph, setGraph] = useState<Graph | null>(null)
  const [loading, setLoading] = useState(true)

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

  useEffect(() => { void load() }, [load])

  const nodes = useMemo(() => ring(graph?.nodes ?? []), [graph])
  const edges: Edge[] = useMemo(
    () =>
      (graph?.edges ?? []).map((e, i) => ({
        id: `${e.source}-${e.target}-${i}`,
        source: e.source,
        target: e.target,
        label: e.joins[0]
          ? `${e.joins[0].left_column} = ${e.joins[0].right_column}${e.count > 1 ? `  ×${e.count}` : ""}`
          : `×${e.count}`,
        labelStyle: { fontSize: 10, fill: "hsl(var(--muted-foreground))" },
        labelBgStyle: { fill: "hsl(var(--background))" },
        style: { strokeWidth: Math.min(1 + Math.log2(e.count + 1), 4) },
        markerEnd: { type: MarkerType.Arrow },
        animated: false,
      })),
    [graph],
  )

  if (loading) {
    return (
      <div className="flex h-[420px] items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 쿼리 이력에서 관계를 찾는 중…
      </div>
    )
  }

  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="flex h-[420px] flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
        <Share2 className="h-6 w-6 opacity-40" />
        <p>최근 {days}일간 성공한 쿼리에서 테이블 관계를 찾지 못했습니다.</p>
        <p className="text-xs">
          Analytics에서 조인 쿼리를 실행하면 여기에 관계가 쌓입니다 — 추론이 아니라 실제 사용 기록입니다.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        최근 {graph.window_days}일 · 성공 쿼리 {graph.statements_scanned}건에서 추출한{" "}
        <b>실제 조인 관계</b>입니다. 선 굵기는 사용 빈도입니다.
      </p>
      <div className="h-[420px] rounded-md border">
        <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}>
          <Background gap={16} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  )
}
