"use client"

import { useEffect, useMemo, useCallback } from "react"
import ReactFlow, {
  Node, Edge, NodeProps,
  Controls, Background, MiniMap,
  useNodesState, useEdgesState,
  MarkerType, BackgroundVariant,
  Handle, Position, Panel,
} from "reactflow"
import dagre from "dagre"
import "reactflow/dist/style.css"
import { CheckCircle2, XCircle, Clock, PlayCircle, AlertCircle, Zap, Box } from "lucide-react"

// ── Types ──────────────────────────────────────────────────────────────────
interface TaskData {
  label: string
  operator?: string
  trigger_rule?: string
  state?: "success" | "failed" | "running" | "queued" | "skipped" | null
}

interface DagGraphProps {
  dag_id: string
  nodes: Node<TaskData>[]
  edges: Edge[]
  taskStates?: Record<string, string>  // task_id → state (from latest run)
}

// ── State config ───────────────────────────────────────────────────────────
const STATE_STYLES: Record<string, { bg: string; border: string; icon: React.ReactNode; dot: string }> = {
  success: {
    bg: "bg-emerald-50",
    border: "border-emerald-400",
    icon: <CheckCircle2 className="h-3 w-3 text-emerald-600" />,
    dot: "bg-emerald-500",
  },
  failed: {
    bg: "bg-red-50",
    border: "border-red-400",
    icon: <XCircle className="h-3 w-3 text-red-600" />,
    dot: "bg-red-500",
  },
  running: {
    bg: "bg-blue-50",
    border: "border-blue-400",
    icon: <Clock className="h-3 w-3 text-blue-600 animate-spin" />,
    dot: "bg-blue-500",
  },
  queued: {
    bg: "bg-yellow-50",
    border: "border-yellow-400",
    icon: <PlayCircle className="h-3 w-3 text-yellow-600" />,
    dot: "bg-yellow-500",
  },
  skipped: {
    bg: "bg-slate-50",
    border: "border-slate-300",
    icon: <AlertCircle className="h-3 w-3 text-slate-400" />,
    dot: "bg-slate-400",
  },
  default: {
    bg: "bg-white",
    border: "border-slate-200",
    icon: <Box className="h-3 w-3 text-slate-400" />,
    dot: "bg-slate-300",
  },
}

// ── Task Node ──────────────────────────────────────────────────────────────
function TaskNode({ data, selected }: NodeProps<TaskData>) {
  const state = data.state ?? "default"
  const style = STATE_STYLES[state] ?? STATE_STYLES.default

  // Short operator label
  const opLabel = data.operator
    ? data.operator.replace("Operator", "").replace("operator", "")
    : null

  return (
    <div className={`
      relative rounded-xl border-2 bg-white w-44 shadow-sm transition-all
      ${selected ? "border-primary shadow-md ring-2 ring-primary/20" : style.border}
    `}>
      {/* State indicator bar (top) */}
      <div className={`absolute top-0 left-3 right-3 h-0.5 rounded-full ${style.dot} opacity-80`} />

      <Handle
        type="target"
        position={Position.Left}
        style={{ background: "#94a3b8", border: "2px solid white", width: 10, height: 10 }}
      />

      <div className={`px-3 py-2.5 rounded-xl ${state !== "default" ? style.bg : ""}`}>
        {/* Header */}
        <div className="flex items-center justify-between gap-1 mb-1">
          <div className="flex items-center gap-1.5 min-w-0">
            {style.icon}
            <span className="text-xs font-semibold truncate">{data.label}</span>
          </div>
        </div>

        {/* Operator badge */}
        {opLabel && (
          <div className="flex items-center gap-1 mt-1">
            <Zap className="h-2.5 w-2.5 text-muted-foreground shrink-0" />
            <span className="text-[10px] text-muted-foreground truncate">{opLabel}</span>
          </div>
        )}

        {/* Trigger rule (if not default) */}
        {data.trigger_rule && data.trigger_rule !== "all_success" && (
          <div className="mt-1.5">
            <span className="text-[9px] bg-muted text-muted-foreground px-1.5 py-0.5 rounded font-mono">
              {data.trigger_rule}
            </span>
          </div>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Right}
        style={{ background: "#94a3b8", border: "2px solid white", width: 10, height: 10 }}
      />
    </div>
  )
}

const nodeTypes = { taskNode: TaskNode }

// ── dagre auto-layout ──────────────────────────────────────────────────────
function layoutGraph(nodes: Node[], edges: Edge[]) {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: "LR", ranksep: 80, nodesep: 50 })

  nodes.forEach((n) => g.setNode(n.id, { width: 176, height: 80 }))
  edges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)

  return nodes.map((n) => {
    const pos = g.node(n.id)
    return { ...n, position: { x: pos.x - 88, y: pos.y - 40 } }
  })
}

// ── Main component ─────────────────────────────────────────────────────────
export function DagGraph({ nodes: rawNodes, edges: rawEdges, taskStates = {} }: DagGraphProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<TaskData>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  // Merge task states + apply dagre layout
  const laidOutNodes = useMemo(() => {
    if (rawNodes.length === 0) return []
    const withState = rawNodes.map((n) => ({
      ...n,
      type: "taskNode",
      data: {
        ...n.data,
        state: (taskStates[n.id] as TaskData["state"]) ?? null,
      },
    }))
    return layoutGraph(withState, rawEdges)
  }, [rawNodes, rawEdges, taskStates])

  const styledEdges = useMemo(() =>
    rawEdges.map((e) => ({
      ...e,
      type: "smoothstep",
      animated: taskStates[e.source] === "running",
      style: { stroke: "#94a3b8", strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: "#94a3b8" },
    })),
    [rawEdges, taskStates]
  )

  useEffect(() => {
    setNodes(laidOutNodes)
    setEdges(styledEdges)
  }, [laidOutNodes, styledEdges, setNodes, setEdges])

  const autoLayout = useCallback(() => {
    setNodes((ns) => layoutGraph(ns, edges))
  }, [edges, setNodes])

  if (rawNodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
        <Box className="h-10 w-10 opacity-20" />
        <p className="text-sm">No task graph available</p>
        <p className="text-xs opacity-60">Airflow tasks will appear here after the DAG is parsed</p>
      </div>
    )
  }

  // Legend
  const legendItems = [
    { state: "success", label: "Success" },
    { state: "running", label: "Running" },
    { state: "failed",  label: "Failed" },
    { state: "queued",  label: "Queued" },
    { state: "default", label: "Pending" },
  ]

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        className="bg-background"
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#e2e8f0" />
        <Controls />
        <MiniMap
          nodeColor={(n) => {
            const s = (n.data as TaskData).state
            return s === "success" ? "#10b981"
              : s === "failed"  ? "#ef4444"
              : s === "running" ? "#3b82f6"
              : s === "queued"  ? "#f59e0b"
              : "#94a3b8"
          }}
          className="!bottom-4 !right-4"
        />

        {/* Legend */}
        <Panel position="bottom-left">
          <div className="flex items-center gap-3 bg-background/90 border rounded-lg px-3 py-2 shadow-sm mb-4 ml-4">
            {legendItems.map(({ state, label }) => {
              const s = STATE_STYLES[state]
              return (
                <div key={state} className="flex items-center gap-1.5 text-[11px]">
                  <div className={`h-2 w-2 rounded-full ${s.dot}`} />
                  <span className="text-muted-foreground">{label}</span>
                </div>
              )
            })}
          </div>
        </Panel>

        {/* Auto-layout button */}
        <Panel position="top-right">
          <button
            onClick={autoLayout}
            className="mt-2 mr-2 px-3 py-1.5 rounded-lg border bg-background text-xs
                       text-muted-foreground hover:bg-muted transition-colors shadow-sm"
          >
            Auto Layout
          </button>
        </Panel>
      </ReactFlow>
    </div>
  )
}
