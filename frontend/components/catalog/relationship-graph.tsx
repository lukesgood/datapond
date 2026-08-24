"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import ReactFlow, { Background, Controls, MarkerType, type Edge, type Node } from "reactflow"
import "reactflow/dist/style.css"
import { Loader2, Share2 } from "lucide-react"

type GraphEdge = {
  source: string
  target: string
  count: number
  evidence: "observed" | "candidate"
  reason?: string
  joins: { left_column: string; right_column: string; count: number }[]
}
type GraphNode = { id: string; query_count: number }
type Graph = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  statements_scanned: number
  window_days: number
  tables_inspected?: number
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
      (graph?.edges ?? []).map((e, i) => {
        const observed = e.evidence === "observed"
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
            fill: observed ? "hsl(var(--foreground))" : "hsl(var(--muted-foreground))",
            fontStyle: observed ? "normal" : "italic",
          },
          labelBgStyle: { fill: "hsl(var(--background))" },
          // Solid and thick = people ran it. Dashed and thin = we guessed from column
          // naming. The two must never be mistaken for each other.
          style: observed
            ? { strokeWidth: Math.min(1 + Math.log2(e.count + 1), 4) }
            : { strokeWidth: 1, strokeDasharray: "4 3", opacity: 0.65 },
          markerEnd: { type: MarkerType.Arrow },
          animated: false,
        }
      }),
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
        <p>표시할 테이블 관계가 없습니다.</p>
        <p className="text-xs">
          카탈로그에 테이블이 없거나, 조인할 만한 키 컬럼이 발견되지 않았습니다.
          Analytics에서 조인 쿼리를 실행하면 관측된 관계가 쌓입니다.
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
          <b className="text-foreground">관측됨</b> — 실제 실행된 조인 (굵기 = 빈도)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="22" height="8" aria-hidden><line x1="0" y1="4" x2="22" y2="4"
            stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3" opacity="0.7" /></svg>
          <i>후보</i> — 컬럼 명명 규칙에서 추정, 미검증
        </span>
        <span>
          최근 {graph.window_days}일 · 쿼리 {graph.statements_scanned}건
          {typeof graph.tables_inspected === "number" && ` · 테이블 ${graph.tables_inspected}개`}
          {" · AI 생성 쿼리 제외"}
        </span>
      </div>
      <div className="h-[420px] rounded-md border">
        <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}>
          <Background gap={16} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  )
}
