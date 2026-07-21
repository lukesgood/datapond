"use client"

import { useEffect, useMemo, useState, useCallback } from "react"
import ReactFlow, {
  Node, Edge, NodeMouseHandler,
  Controls, Background, MiniMap,
  useNodesState, useEdgesState,
  MarkerType, BackgroundVariant,
  Panel, useReactFlow, ReactFlowProvider,
} from "reactflow"
import ELK from "elkjs/lib/elk.bundled.js"
import "reactflow/dist/style.css"
import { AssetNode, AssetNodeData } from "./asset-node"
import { Database, Table2, ShieldCheck } from "lucide-react"

interface RawAssetNode {
  id: string
  type: string
  data: AssetNodeData
}

interface AssetGraphProps {
  dag_id: string
  nodes: RawAssetNode[]
  edges: Edge[]
  taskStates?: Record<string, string>
  onNodeSelect?: (nodeId: string | null) => void
}

const nodeTypes = { source: AssetNode, table: AssetNode, quality: AssetNode }

const NODE_W = 144
const NODE_H = 32

const elk = new ELK()

async function layoutGraph(nodes: Node[], edges: Edge[]): Promise<Node[]> {
  const graph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.spacing.nodeNode": "24",
      "elk.layered.spacing.nodeNodeBetweenLayers": "80",
      "elk.layered.spacing.edgeNodeBetweenLayers": "20",
      "elk.edgeRouting": "SPLINES",
    },
    children: nodes.map((n) => ({
      id: n.id,
      width: NODE_W,
      height: NODE_H,
    })),
    edges: edges.map((e) => ({
      id: e.id,
      sources: [e.source],
      targets: [e.target],
    })),
  }

  const layout = await elk.layout(graph)

  return nodes.map((n) => {
    const elkNode = layout.children?.find((c) => c.id === n.id)
    return {
      ...n,
      position: { x: elkNode?.x ?? 0, y: elkNode?.y ?? 0 },
    }
  })
}

function getConnectedIds(nodeId: string, edges: Edge[]): Set<string> {
  const connected = new Set<string>([nodeId])
  const queue = [nodeId]
  while (queue.length) {
    const cur = queue.pop()!
    for (const e of edges) {
      if (e.target === cur && !connected.has(e.source)) {
        connected.add(e.source)
        queue.push(e.source)
      }
    }
  }
  const dq = [nodeId]
  while (dq.length) {
    const cur = dq.pop()!
    for (const e of edges) {
      if (e.source === cur && !connected.has(e.target)) {
        connected.add(e.target)
        dq.push(e.target)
      }
    }
  }
  return connected
}

export function AssetGraph(props: AssetGraphProps) {
  return (
    <ReactFlowProvider>
      <AssetGraphInner {...props} />
    </ReactFlowProvider>
  )
}

function AssetGraphInner({ nodes: rawNodes, edges: rawEdges, taskStates = {}, onNodeSelect }: AssetGraphProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [layoutVersion, setLayoutVersion] = useState(0)

  const connectedIds = useMemo(
    () => selectedNode ? getConnectedIds(selectedNode, rawEdges) : null,
    [selectedNode, rawEdges]
  )

  // ELK layout is async — trigger fitView after layout completes
  useEffect(() => {
    if (rawNodes.length === 0) return

    const mapped: Node<AssetNodeData>[] = rawNodes.map((n) => ({
      id: n.id,
      type: n.type,
      position: { x: 0, y: 0 },
      data: { ...n.data, state: taskStates[n.id] as AssetNodeData["state"] ?? null },
    }))

    layoutGraph(mapped, rawEdges).then((laidOut) => {
      const styled = connectedIds
        ? laidOut.map((n) => ({ ...n, style: connectedIds.has(n.id) ? { opacity: 1 } : { opacity: 0.12 } }))
        : laidOut
      setNodes(styled)
      setLayoutVersion((v) => v + 1)
    })
  }, [rawNodes, rawEdges, taskStates, connectedIds, setNodes])

  const styledEdges = useMemo(() =>
    rawEdges.map((e) => {
      const lit = connectedIds ? connectedIds.has(e.source) && connectedIds.has(e.target) : true
      return {
        ...e,
        type: "smoothstep",
        animated: taskStates[e.source] === "running",
        style: {
          stroke: lit ? "#94a3b8" : "#e2e8f0",
          strokeWidth: lit ? 1.5 : 0.5,
          opacity: lit ? 1 : 0.4,
        },
        markerEnd: lit
          ? { type: MarkerType.ArrowClosed, color: "#94a3b8", width: 12, height: 12 }
          : undefined,
      }
    }),
    [rawEdges, connectedIds, taskStates]
  )

  useEffect(() => {
    setEdges(styledEdges)
  }, [styledEdges, setEdges])

  // Fit view after layout completes to ensure all nodes are visible
  const { fitView } = useReactFlow()
  useEffect(() => {
    if (layoutVersion > 0 && nodes.length > 0) {
      const timer = setTimeout(() => fitView({ padding: 0.3, maxZoom: 1 }), 50)
      return () => clearTimeout(timer)
    }
  }, [layoutVersion, nodes.length, fitView])

  const handleNodeClick: NodeMouseHandler = useCallback((_, node) => {
    const next = selectedNode === node.id ? null : node.id
    setSelectedNode(next)
    onNodeSelect?.(next)
  }, [selectedNode, onNodeSelect])

  const handlePaneClick = useCallback(() => {
    setSelectedNode(null)
    onNodeSelect?.(null)
  }, [onNodeSelect])

  if (rawNodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
        <Table2 className="h-10 w-10 opacity-20" />
        <p className="text-sm">No asset graph available</p>
        <p className="text-xs opacity-60">Data assets will appear after the pipeline is parsed</p>
      </div>
    )
  }

  return (
    <div className="h-full w-full bg-background rounded-xl border overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        nodeTypes={nodeTypes}
        minZoom={0.4}
        maxZoom={1.5}
        className="!bg-background"
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={0.8} color="#e2e8f0" />
        <Controls
          showInteractive={false}
          className="!bg-background !border-border !rounded-lg !shadow-sm
                     [&>button]:!bg-background [&>button]:!border-border [&>button]:!text-muted-foreground
                     [&>button:hover]:!bg-muted [&>button:hover]:!text-foreground"
        />
        <MiniMap
          nodeColor={(n) => {
            const l = (n.data as AssetNodeData)?.layer
            return l === "bronze" ? "#d97706" : l === "gold" ? "#ca8a04" : l === "quality" ? "#7c3aed" : "#64748b"
          }}
          className="!bg-muted/50 !border-border !rounded-lg"
          maskColor="rgba(255,255,255,0.7)"
          nodeStrokeWidth={0}
        />

        {/* Compact legend */}
        <Panel position="bottom-left">
          <div className="flex items-center gap-3 bg-background border border-border rounded-md px-2.5 py-1.5 shadow-sm mb-2 ml-2">
            {[
              { icon: Database, label: "Source", color: "text-amber-600" },
              { icon: Table2, label: "Table", color: "text-slate-600" },
              { icon: ShieldCheck, label: "Quality", color: "text-violet-600" },
            ].map(({ icon: Icon, label, color }) => (
              <div key={label} className="flex items-center gap-1 text-[9px]">
                <Icon className={`h-2.5 w-2.5 ${color}`} />
                <span className="text-muted-foreground">{label}</span>
              </div>
            ))}
          </div>
        </Panel>
      </ReactFlow>
    </div>
  )
}
