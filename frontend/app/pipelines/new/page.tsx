"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { useRouter } from "next/navigation"
import ReactFlow, {
  Node,
  Edge,
  Connection,
  addEdge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  NodeProps,
  BackgroundVariant,
  MarkerType,
  Panel,
  useReactFlow,
} from "reactflow"
import "reactflow/dist/style.css"
import dagre from "dagre"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Rocket,
  ArrowLeft,
  Trash2,
  LayoutGrid,
  Settings2,
  X,
  Search,
  Undo2,
  Redo2,
} from "lucide-react"

// ── Types ─────────────────────────────────────────────────────────────────────

interface ApiConnection {
  id: string
  name: string
  connector_type: string
}

interface PipelineState {
  pipelineName: string
  schedule: string
  description: string
  advanced: PipelineAdvanced
}

interface BronzeData {
  layer: "bronze"
  name: string
  connectionName: string
  connectionType: string
  table: string
  mode: "full_refresh" | "incremental" | "merge"
  watermarkColumn: string
  primaryKey: string       // Merge/Upsert 기준 키
  filterSql: string        // 추출 조건 (WHERE 절)
  batchSize: string        // 대용량 배치 크기
}

interface SilverData {
  layer: "silver"
  name: string
  sql: string
  mode: "full_refresh" | "incremental"
  qualityCheck: string
  partitionBy: string      // Iceberg 파티션 컬럼
  primaryKey: string       // Dedup 기준 키
  description: string      // 카탈로그 등록용
}

interface GoldData {
  layer: "gold"
  name: string
  sql: string
  aggregation: string
  partitionBy: string
  description: string
}

interface PipelineAdvanced {
  retries: string        // → max_retries (백엔드 PipelineDefinition)
  retryDelay: string     // → retry_delay_minutes
  owner: string          // → owner
  alertOnFailure: boolean // → alert_on_failure
  alertEmail: string     // → alert_email (comma-separated addresses)
  tags: string           // → tags (쉼표 구분 문자열)
  catchup: boolean       // → Airflow DAG catchup
  maxActiveRuns: string  // → Airflow DAG max_active_runs
}

type NodeData = BronzeData | SilverData | GoldData

// ── Layer Styles ──────────────────────────────────────────────────────────────

const LAYER_STYLES = {
  bronze: {
    bar: "bg-amber-500",
    header: "bg-amber-50 border-amber-200",
    border: "border-amber-200",
    selectedBorder: "border-amber-500",
    ring: "ring-amber-200",
    badge: "bg-amber-100 text-amber-800",
    dot: "bg-amber-500",
    label: "BRONZE",
    textColor: "text-amber-700",
    handleColor: "#f59e0b",
  },
  silver: {
    bar: "bg-slate-400",
    header: "bg-slate-50 border-slate-200",
    border: "border-slate-200",
    selectedBorder: "border-slate-500",
    ring: "ring-slate-200",
    badge: "bg-slate-100 text-slate-700",
    dot: "bg-slate-400",
    label: "SILVER",
    textColor: "text-slate-600",
    handleColor: "#94a3b8",
  },
  gold: {
    bar: "bg-yellow-400",
    header: "bg-yellow-50 border-yellow-200",
    border: "border-yellow-200",
    selectedBorder: "border-yellow-500",
    ring: "ring-yellow-200",
    badge: "bg-yellow-100 text-yellow-800",
    dot: "bg-yellow-500",
    label: "GOLD",
    textColor: "text-yellow-700",
    handleColor: "#eab308",
  },
}

// ── Constants ─────────────────────────────────────────────────────────────────

const SCHEDULE_OPTIONS = [
  { value: "@hourly",  label: "Hourly",          cron: "0 * * * *",   desc: "매 정각" },
  { value: "@daily",   label: "Daily",            cron: "0 0 * * *",   desc: "매일 자정 (UTC)" },
  { value: "@weekly",  label: "Weekly",           cron: "0 0 * * 0",   desc: "매주 일요일 자정" },
  { value: "@monthly", label: "Monthly",          cron: "0 0 1 * *",   desc: "매월 1일 자정" },
  { value: "None",     label: "Manual",           cron: "",            desc: "수동 트리거만" },
  { value: "custom",   label: "Custom cron...",   cron: "",            desc: "직접 입력" },
]

const AGGREGATION_OPTIONS = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "custom", label: "Custom" },
]

function uid() {
  return Math.random().toString(36).slice(2, 8)
}

// ── Dagre Auto-Layout ─────────────────────────────────────────────────────────

const LAYER_HEADER_CONFIG: Record<string, { label: string; color: string; barColor: string }> = {
  bronze: { label: "BRONZE",  color: "text-amber-600",  barColor: "bg-amber-400" },
  silver: { label: "SILVER",  color: "text-slate-500",  barColor: "bg-slate-400" },
  gold:   { label: "GOLD",    color: "text-yellow-600", barColor: "bg-yellow-400" },
}

function getLayoutedElements(nodes: Node[], edges: Edge[]) {
  // Filter out existing header nodes before layout
  const dataNodes = nodes.filter(n => n.type !== "layerHeader")

  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: "LR", ranksep: 80, nodesep: 40 })

  dataNodes.forEach((n) => g.setNode(n.id, { width: 224, height: 120 }))
  edges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)

  const layoutedData = dataNodes.map((n) => {
    const pos = g.node(n.id)
    return { ...n, position: { x: pos.x - 112, y: pos.y - 60 } }
  })

  // Compute column x-center per layer and insert header nodes
  const headerNodes: Node[] = []
  const presentLayers = new Set(layoutedData.map(n => (n.data as any).layer as string))

  for (const layer of ["bronze", "silver", "gold"]) {
    if (!presentLayers.has(layer)) continue
    const layerNds = layoutedData.filter(n => (n.data as any).layer === layer)
    const xs = layerNds.map(n => n.position.x)
    const centerX = (Math.min(...xs) + Math.max(...xs) + 224) / 2
    const topY = Math.min(...layerNds.map(n => n.position.y))
    headerNodes.push({
      id: `__header_${layer}`,
      type: "layerHeader",
      position: { x: centerX - 60, y: topY - 44 },
      data: LAYER_HEADER_CONFIG[layer],
      selectable: false,
      draggable: false,
    } as Node)
  }

  return {
    nodes: [...headerNodes, ...layoutedData],
    edges,
  }
}

// ── Edge defaults ─────────────────────────────────────────────────────────────

const DEFAULT_EDGE_OPTIONS = {
  type: "smoothstep",
  animated: true,
  style: { stroke: "#94a3b8", strokeWidth: 2 },
  markerEnd: { type: MarkerType.ArrowClosed, color: "#94a3b8" },
}

// ── Code Generation ───────────────────────────────────────────────────────────

function generateCode(nodes: Node<NodeData>[], edges: Edge[], pipeline: PipelineState): string {
  const bronzeNodes = nodes.filter((n) => n.data.layer === "bronze")
  const silverNodes = nodes.filter((n) => n.data.layer === "silver")
  const goldNodes   = nodes.filter((n) => n.data.layer === "gold")
  const adv = pipeline.advanced

  const getDependsOn = (nodeId: string): string[] =>
    edges
      .filter((e) => e.target === nodeId)
      .map((e) => nodes.find((n) => n.id === e.source)?.data.name)
      .filter((name): name is string => Boolean(name))

  const schedule = pipeline.schedule === "None" ? "None" : `"${pipeline.schedule}"`

  // Parse tags: comma-separated string → Python list
  const tagsList = adv.tags
    .split(",").map(t => t.trim()).filter(Boolean)
  const tagsStr = JSON.stringify(["datapond-pipeline", ...tagsList])

  const lines: string[] = [
    `from app.pipelines.decorators import pipeline, source, live_table, quality`,
    ``,
    `# Medallion Architecture Pipeline`,
    `# Bronze (raw) → Silver (clean) → Gold (aggregate)`,
    ``,
    `@pipeline(`,
    `    name="${pipeline.pipelineName}",`,
    `    schedule=${schedule},`,
    ...(pipeline.description ? [`    description="${pipeline.description}",`] : []),
    `    owner="${adv.owner || "data-team"}",`,
    `    max_retries=${adv.retries || 2},`,
    `    retry_delay_minutes=${adv.retryDelay || 5},`,
    `    tags=${tagsStr},`,
    `    alert_on_failure=${adv.alertOnFailure ? "True" : "False"},`,
    ...(adv.alertEmail ? [`    alert_email="${adv.alertEmail}",`] : []),
    `)`,
    `def ${pipeline.pipelineName}(): pass`,
    ``,
    `# Airflow DAG options (applied by compiler):`,
    `#   catchup=${adv.catchup ? "True" : "False"}`,
    `#   max_active_runs=${adv.maxActiveRuns || 1}`,
    ``,
    `# ── Bronze Layer (Raw Sources) ──────────────────────────────`,
  ]

  for (const n of bronzeNodes) {
    const d = n.data as BronzeData
    lines.push(``)
    lines.push(`@source(`)
    lines.push(`    name="${d.name}",`)
    lines.push(`    connection="${d.connectionName}",`)
    lines.push(`    source_type="${d.connectionType}",`)
    lines.push(`    table="${d.table}",`)
    lines.push(`    mode="${d.mode}",`)
    if (d.mode === "incremental" && d.watermarkColumn)
      lines.push(`    watermark_column="${d.watermarkColumn}",`)
    if (d.primaryKey) lines.push(`    primary_key="${d.primaryKey}",`)
    if (d.filterSql)  lines.push(`    filter="${d.filterSql.replace(/"/g, '\\"')}",`)
    if (d.batchSize)  lines.push(`    batch_size=${d.batchSize},`)
    lines.push(`)`)
    lines.push(`def ${d.name}(): pass`)
  }

  lines.push(``, `# ── Silver Layer (Clean & Validate) ─────────────────────────`)
  for (const n of silverNodes) {
    const d = n.data as SilverData
    const deps = getDependsOn(n.id)
    lines.push(``)
    lines.push(`@live_table(`)
    lines.push(`    mode="${d.mode}",`)
    lines.push(`    depends_on=${JSON.stringify(deps)},`)
    if (d.primaryKey)   lines.push(`    primary_key="${d.primaryKey}",`)
    if (d.partitionBy)  lines.push(`    partition_by="${d.partitionBy}",`)
    if (d.description)  lines.push(`    description="${d.description}",`)
    lines.push(`)`)
    lines.push(`def ${d.name}():`)
    lines.push(`    return """`)
    d.sql.split("\n").forEach((l) => lines.push(`    ${l}`))
    lines.push(`    """`)
    if (d.qualityCheck.trim()) {
      lines.push(``)
      lines.push(`@quality(table="${d.name}")`)
      lines.push(`def check_${d.name}(): return "${d.qualityCheck.replace(/"/g, '\\"')}"`)
    }
  }

  lines.push(``, `# ── Gold Layer (Aggregate & Serve) ──────────────────────────`)
  for (const n of goldNodes) {
    const d = n.data as GoldData
    const deps = getDependsOn(n.id)
    lines.push(``)
    lines.push(`@live_table(`)
    lines.push(`    mode="full_refresh",`)
    lines.push(`    depends_on=${JSON.stringify(deps)},`)
    if (d.partitionBy)  lines.push(`    partition_by="${d.partitionBy}",`)
    if (d.description)  lines.push(`    description="${d.description}",`)
    lines.push(`)`)
    lines.push(`def ${d.name}():`)
    lines.push(`    return """`)
    d.sql.split("\n").forEach((l) => lines.push(`    ${l}`))
    lines.push(`    """`)
  }

  return lines.join("\n")
}

// ── SQL Syntax Highlighting ───────────────────────────────────────────────────

const SQL_KW = new Set([
  'SELECT','FROM','WHERE','JOIN','LEFT','RIGHT','INNER','OUTER','FULL','CROSS',
  'ON','AND','OR','NOT','IN','EXISTS','BETWEEN','LIKE','ILIKE','IS','NULL','AS',
  'GROUP','BY','ORDER','HAVING','LIMIT','OFFSET','UNION','ALL','DISTINCT',
  'CASE','WHEN','THEN','ELSE','END','WITH','OVER','PARTITION','INTO',
  'COUNT','SUM','AVG','MIN','MAX','COALESCE','NULLIF','CAST','DATE',
  'TIMESTAMP','ROW_NUMBER','RANK','DENSE_RANK','LAG','LEAD','EXTRACT',
  'TRUE','FALSE','ASC','DESC','NULLS','FIRST','LAST',
])

function SqlTokens({ sql }: { sql: string }) {
  const parts: React.ReactNode[] = []
  const re = /(\{\{[^}]*\}\})|('(?:[^']|'')*')|(--[^\n]*)|(\/\*[\s\S]*?\*\/)|(\b[A-Za-z_][A-Za-z0-9_]*\b)|(\d+(?:\.\d+)?)|([^\w\s])|(\s+)/g
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(sql)) !== null) {
    const [full, tmpl, str, lc, bc, word, num] = m
    if (tmpl)        parts.push(<span key={i++} className="text-emerald-600">{tmpl}</span>)
    else if (str)    parts.push(<span key={i++} className="text-amber-600">{str}</span>)
    else if (lc||bc) parts.push(<span key={i++} className="text-muted-foreground/60 italic">{full}</span>)
    else if (word && SQL_KW.has(word.toUpperCase())) parts.push(<span key={i++} className="text-blue-500 font-medium">{word}</span>)
    else if (num)    parts.push(<span key={i++} className="text-purple-500">{num}</span>)
    else             parts.push(<span key={i++}>{full}</span>)
  }
  return <>{parts}</>
}

// ── Focus Node (canvas auto-scroll) ──────────────────────────────────────────

function FocusNode({ nodeId, nodes }: { nodeId: string | null; nodes: Node[] }) {
  const { setCenter } = useReactFlow()
  const prevRef = useRef<string | null>(null)
  useEffect(() => {
    if (!nodeId || nodeId === prevRef.current) return
    prevRef.current = nodeId
    const n = nodes.find(n => n.id === nodeId)
    if (!n) return
    const t = setTimeout(() => setCenter(n.position.x + 112, n.position.y + 60, { duration: 600, zoom: 1.2 }), 30)
    return () => clearTimeout(t)
  }, [nodeId, nodes, setCenter])
  return null
}

// ── Custom Nodes ──────────────────────────────────────────────────────────────

function BronzeNode({ data, selected }: NodeProps<BronzeData>) {
  const style = LAYER_STYLES.bronze
  return (
    <div
      className={`relative w-56 rounded-xl border-2 bg-white shadow-sm transition-all
        ${selected ? `${style.selectedBorder} shadow-md ring-2 ${style.ring}` : style.border}`}
    >
      {/* Left color bar */}
      <div className={`absolute left-0 top-0 bottom-0 w-1 rounded-l-xl ${style.bar}`} />

      {/* Header */}
      <div className={`pl-3 pr-3 py-2 border-b ${style.header} rounded-t-xl`}>
        <div className="flex items-center justify-between">
          <span className={`text-[9px] font-bold tracking-[0.15em] ${style.textColor}`}>
            {style.label}
          </span>
          <div className={`h-2 w-2 rounded-full ${style.dot}`} />
        </div>
        <p className="text-sm font-semibold text-gray-800 truncate mt-0.5">
          {data.name || "unnamed"}
        </p>
      </div>

      {/* Body */}
      <div className="pl-3 pr-3 py-2.5 space-y-1.5">
        {data.connectionName ? (
          <p className="text-xs text-gray-600 truncate flex items-center gap-1">
            <span className="text-gray-400">🗄</span> {data.connectionName}
          </p>
        ) : (
          <p className="text-xs text-gray-400 italic">No connection</p>
        )}
        {data.table && (
          <p className="font-mono text-[11px] text-gray-500 truncate">{data.table}</p>
        )}
        <div className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-gray-300" />
          <span className="text-[10px] text-gray-500">{data.mode}</span>
          {data.mode === "incremental" && data.watermarkColumn && (
            <span className="font-mono text-[10px] text-gray-400">{data.watermarkColumn}</span>
          )}
        </div>
      </div>

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Right}
        style={{
          background: style.handleColor,
          border: "2px solid white",
          width: 10,
          height: 10,
        }}
      />
    </div>
  )
}

function SilverNode({ data, selected }: NodeProps<SilverData>) {
  const style = LAYER_STYLES.silver
  const sqlPreview = data.sql
    ? data.sql.split("\n").slice(0, 3).join("\n")
    : "No SQL"
  return (
    <div
      className={`relative w-56 rounded-xl border-2 bg-white shadow-sm transition-all
        ${selected ? `${style.selectedBorder} shadow-md ring-2 ${style.ring}` : style.border}`}
    >
      {/* Left color bar */}
      <div className={`absolute left-0 top-0 bottom-0 w-1 rounded-l-xl ${style.bar}`} />

      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Left}
        style={{
          background: style.handleColor,
          border: "2px solid white",
          width: 10,
          height: 10,
        }}
      />

      {/* Header */}
      <div className={`pl-3 pr-3 py-2 border-b ${style.header} rounded-t-xl`}>
        <div className="flex items-center justify-between">
          <span className={`text-[9px] font-bold tracking-[0.15em] ${style.textColor}`}>
            {style.label}
          </span>
          <div className={`h-2 w-2 rounded-full ${style.dot}`} />
        </div>
        <p className="text-sm font-semibold text-gray-800 truncate mt-0.5">
          {data.name || "unnamed"}
        </p>
      </div>

      {/* Body */}
      <div className="pl-3 pr-3 py-2.5 space-y-1.5">
        <div className="font-mono text-[10px] leading-relaxed" style={{ maxHeight: '3.6em', overflow: 'hidden' }}>
          <SqlTokens sql={sqlPreview} />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-gray-300" />
          <span className="text-[10px] text-gray-500">{data.mode}</span>
        </div>
      </div>

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Right}
        style={{
          background: style.handleColor,
          border: "2px solid white",
          width: 10,
          height: 10,
        }}
      />
    </div>
  )
}

function GoldNode({ data, selected }: NodeProps<GoldData>) {
  const style = LAYER_STYLES.gold
  const sqlPreview = data.sql
    ? data.sql.split("\n").slice(0, 3).join("\n")
    : "No SQL"
  return (
    <div
      className={`relative w-56 rounded-xl border-2 bg-white shadow-sm transition-all
        ${selected ? `${style.selectedBorder} shadow-md ring-2 ${style.ring}` : style.border}`}
    >
      {/* Left color bar */}
      <div className={`absolute left-0 top-0 bottom-0 w-1 rounded-l-xl ${style.bar}`} />

      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Left}
        style={{
          background: style.handleColor,
          border: "2px solid white",
          width: 10,
          height: 10,
        }}
      />

      {/* Header */}
      <div className={`pl-3 pr-3 py-2 border-b ${style.header} rounded-t-xl`}>
        <div className="flex items-center justify-between">
          <span className={`text-[9px] font-bold tracking-[0.15em] ${style.textColor}`}>
            {style.label}
          </span>
          <div className={`h-2 w-2 rounded-full ${style.dot}`} />
        </div>
        <p className="text-sm font-semibold text-gray-800 truncate mt-0.5">
          {data.name || "unnamed"}
        </p>
      </div>

      {/* Body */}
      <div className="pl-3 pr-3 py-2.5 space-y-1.5">
        <div className="font-mono text-[10px] leading-relaxed" style={{ maxHeight: '3.6em', overflow: 'hidden' }}>
          <SqlTokens sql={sqlPreview} />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-gray-300" />
          <span className="text-[10px] text-gray-500">{data.aggregation || "custom"}</span>
        </div>
      </div>
    </div>
  )
}

// ── Layer Header Node (non-interactive, used as column label) ─────────────
function LayerHeaderNode({ data }: NodeProps<{ label: string; color: string; barColor: string }>) {
  return (
    <div className="pointer-events-none select-none flex flex-col items-center gap-1 opacity-70">
      <span className={`text-[11px] font-bold tracking-[0.18em] uppercase ${data.color}`}>
        {data.label}
      </span>
      <div className={`h-0.5 w-12 rounded-full ${data.barColor}`} />
    </div>
  )
}

// nodeTypes must be defined outside the component to prevent re-renders
const nodeTypes = {
  bronzeNode: BronzeNode,
  silverNode: SilverNode,
  goldNode: GoldNode,
  layerHeader: LayerHeaderNode,
}

// ── Initial State ─────────────────────────────────────────────────────────────

const EXAMPLE_NODES: Node<NodeData>[] = [
  {
    id: "bronze-1",
    type: "bronzeNode",
    position: { x: 50, y: 100 },
    data: {
      layer: "bronze",
      name: "raw_orders",
      connectionName: "",
      connectionType: "postgresql",
      table: "public.orders",
      mode: "incremental",
      watermarkColumn: "updated_at",
      primaryKey: "id",
      filterSql: "",
      batchSize: "",
    },
  },
  {
    id: "bronze-2",
    type: "bronzeNode",
    position: { x: 50, y: 280 },
    data: {
      layer: "bronze",
      name: "raw_customers",
      connectionName: "",
      connectionType: "postgresql",
      table: "public.customers",
      mode: "incremental",
      watermarkColumn: "modified_at",
      primaryKey: "id",
      filterSql: "",
      batchSize: "",
    },
  },
  {
    id: "silver-1",
    type: "silverNode",
    position: { x: 350, y: 100 },
    data: {
      layer: "silver",
      name: "clean_orders",
      sql: "SELECT id, customer_id, amount, status\nFROM {{ source('raw_orders') }}\nWHERE amount > 0\n{{ incremental_filter('updated_at') }}",
      mode: "incremental",
      qualityCheck: "amount > 0",
      partitionBy: "DATE(updated_at)",
      primaryKey: "id",
      description: "정제된 주문 데이터",
    },
  },
  {
    id: "silver-2",
    type: "silverNode",
    position: { x: 350, y: 280 },
    data: {
      layer: "silver",
      name: "clean_customers",
      sql: "SELECT id, name, email\nFROM {{ source('raw_customers') }}\nWHERE email IS NOT NULL",
      mode: "incremental",
      qualityCheck: "email IS NOT NULL",
      partitionBy: "",
      primaryKey: "id",
      description: "정제된 고객 데이터",
    },
  },
  {
    id: "gold-1",
    type: "goldNode",
    position: { x: 650, y: 190 },
    data: {
      layer: "gold",
      name: "daily_revenue",
      aggregation: "daily",
      sql: "SELECT DATE(o.created_at) as date,\n  SUM(o.amount) as revenue,\n  COUNT(DISTINCT o.customer_id) as customers\nFROM {{ ref('clean_orders') }} o\nGROUP BY 1\nORDER BY 1 DESC",
      partitionBy: "date",
      description: "일별 매출 집계",
    },
  },
]

const EXAMPLE_EDGES: Edge[] = [
  { id: "e1", source: "bronze-1", target: "silver-1", ...DEFAULT_EDGE_OPTIONS },
  { id: "e2", source: "bronze-2", target: "silver-2", ...DEFAULT_EDGE_OPTIONS },
  { id: "e3", source: "silver-1", target: "gold-1", ...DEFAULT_EDGE_OPTIONS },
  { id: "e4", source: "silver-2", target: "gold-1", ...DEFAULT_EDGE_OPTIONS },
]

// ── Properties Panel Sub-Forms ────────────────────────────────────────────────

interface BronzeFormProps {
  data: BronzeData
  connections: ApiConnection[]
  onChange: (patch: Partial<BronzeData>) => void
  onDelete: () => void
}

function BronzeForm({ data, connections, onChange, onDelete }: BronzeFormProps) {
  const style = LAYER_STYLES.bronze
  return (
    <div className="p-5">
      <div className="flex items-center gap-2 mb-4">
        <div className={`h-3.5 w-1 rounded ${style.bar}`} />
        <span className={`text-xs font-bold tracking-widest ${style.textColor}`}>BRONZE SOURCE</span>
      </div>

      <div className="grid grid-cols-2 gap-4">
      <div className="space-y-1.5">
        <Label className="text-xs">Name</Label>
        <Input
          value={data.name}
          onChange={(e) => onChange({ name: e.target.value.replace(/\s/g, "_") })}
          className="font-mono text-sm h-9"
          placeholder="raw_orders"
        />
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">Connection</Label>
        <Select
          value={data.connectionName}
          onValueChange={(v) => {
            if (!v) return
            const conn = connections.find((c) => c.name === v)
            onChange({ connectionName: v, connectionType: conn?.connector_type ?? "postgresql" })
          }}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Select connection..." />
          </SelectTrigger>
          <SelectContent>
            {connections.length === 0 ? (
              <SelectItem value="__none" disabled>
                No connections available
              </SelectItem>
            ) : (
              connections.map((c) => (
                <SelectItem key={c.id} value={c.name} className="text-xs">
                  {c.name}{" "}
                  <span className="text-muted-foreground">({c.connector_type})</span>
                </SelectItem>
              ))
            )}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">Table</Label>
        <Input value={data.table}
          onChange={(e) => onChange({ table: e.target.value })}
          className="font-mono text-sm h-9" placeholder="public.orders" />
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">Sync Mode</Label>
        <Select value={data.mode} onValueChange={(v) => { if (v) onChange({ mode: v as BronzeData["mode"] }) }}>
          <SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="incremental">Incremental — 증분</SelectItem>
            <SelectItem value="full_refresh">Full Refresh — 전체</SelectItem>
            <SelectItem value="merge">Merge (Upsert)</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {data.mode === "incremental" && (
        <div className="space-y-1.5">
          <Label className="text-xs">Watermark Column</Label>
          <Input value={data.watermarkColumn}
            onChange={(e) => onChange({ watermarkColumn: e.target.value })}
            className="font-mono text-sm h-9" placeholder="updated_at" />
          <p className="text-[11px] text-muted-foreground">마지막 실행 이후 변경된 행만 추출</p>
        </div>
      )}

      {(data.mode === "incremental" || data.mode === "merge") && (
        <div className="space-y-1.5">
          <Label className="text-xs">Primary Key</Label>
          <Input value={data.primaryKey}
            onChange={(e) => onChange({ primaryKey: e.target.value })}
            className="font-mono text-sm h-9" placeholder="id" />
          <p className="text-[11px] text-muted-foreground">복합키: id,tenant_id</p>
        </div>
      )}

      <div className="space-y-1.5">
        <Label className="text-xs">Filter SQL <span className="text-muted-foreground">(선택)</span></Label>
        <Input value={data.filterSql}
          onChange={(e) => onChange({ filterSql: e.target.value })}
          className="font-mono text-sm h-9" placeholder="status != 'deleted'" />
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">Batch Size <span className="text-muted-foreground">(선택)</span></Label>
        <Input value={data.batchSize}
          onChange={(e) => onChange({ batchSize: e.target.value })}
          className="font-mono text-sm h-9" type="number" placeholder="10000" />
      </div>
      </div>{/* end grid */}

      <div className="mt-5 pt-4 border-t">
        <button onClick={onDelete}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md
            bg-red-50 border border-red-200 text-red-700 hover:bg-red-100
            transition-colors text-xs font-medium">
          <Trash2 className="h-3.5 w-3.5" />Delete Node
        </button>
      </div>
    </div>
  )
}

interface SilverFormProps {
  data: SilverData
  onChange: (patch: Partial<SilverData>) => void
  onDelete: () => void
}

function SilverForm({ data, onChange, onDelete }: SilverFormProps) {
  const style = LAYER_STYLES.silver
  return (
    <div className="p-5">
      <div className="flex items-center gap-2 mb-4">
        <div className={`h-3.5 w-1 rounded ${style.bar}`} />
        <span className={`text-xs font-bold tracking-widest ${style.textColor}`}>SILVER TRANSFORM</span>
      </div>

      {/* Top row: 2-column meta */}
      <div className="grid grid-cols-3 gap-4 mb-4">
        <div className="space-y-1.5">
          <Label className="text-xs">Name</Label>
          <Input value={data.name}
            onChange={(e) => onChange({ name: e.target.value.replace(/\s/g, "_") })}
            className="font-mono text-sm h-9" placeholder="clean_orders" />
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs">Mode</Label>
          <Select value={data.mode} onValueChange={(v) => { if (v) onChange({ mode: v as SilverData["mode"] }) }}>
            <SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="incremental">Incremental</SelectItem>
              <SelectItem value="full_refresh">Full Refresh</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs">Primary Key</Label>
          <Input value={data.primaryKey}
            onChange={(e) => onChange({ primaryKey: e.target.value })}
            className="font-mono text-sm h-9" placeholder="id" />
          <p className="text-[11px] text-muted-foreground">Dedup · Merge 기준 키</p>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs">Partition By</Label>
          <Input value={data.partitionBy}
            onChange={(e) => onChange({ partitionBy: e.target.value })}
            className="font-mono text-sm h-9" placeholder="DATE(updated_at)" />
          <p className="text-[11px] text-muted-foreground">Iceberg 파티션 표현식</p>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs">Quality Check</Label>
          <Input value={data.qualityCheck}
            onChange={(e) => onChange({ qualityCheck: e.target.value })}
            className="font-mono text-sm h-9" placeholder="amount > 0" />
          <p className="text-[11px] text-muted-foreground">WHERE 조건 — 실패시 중단</p>
        </div>

        <div className="space-y-1.5 col-span-2">
          <Label className="text-xs">Description</Label>
          <Input value={data.description}
            onChange={(e) => onChange({ description: e.target.value })}
            className="text-sm h-9" placeholder="OpenMetadata 카탈로그 설명" />
        </div>
      </div>{/* end grid */}

      {/* SQL — full width */}
      <div className="mt-4 space-y-1.5">
        <Label className="text-xs font-medium flex items-center gap-2">
          SQL Transform
          <span className="text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-200">SQL</span>
          <span className="text-[11px] font-normal text-muted-foreground">
            {`{{ source('name') }}`} · {`{{ ref('name') }}`} · {`{{ incremental_filter('col') }}`}
          </span>
        </Label>
        <Textarea value={data.sql}
          onChange={(e) => onChange({ sql: e.target.value })}
          className="font-mono text-[13px] resize-y leading-relaxed border-0 bg-slate-950 text-slate-100 rounded-lg focus-visible:ring-1 focus-visible:ring-blue-500 placeholder:text-slate-500"
          style={{ minHeight: 160 }}
          spellCheck={false}
        />
      </div>

      <div className="mt-4 pt-3 border-t">
        <button onClick={onDelete}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md
            bg-red-50 border border-red-200 text-red-700 hover:bg-red-100
            transition-colors text-xs font-medium">
          <Trash2 className="h-3.5 w-3.5" />Delete Node
        </button>
      </div>
    </div>
  )
}

interface GoldFormProps {
  data: GoldData
  onChange: (patch: Partial<GoldData>) => void
  onDelete: () => void
}

function GoldForm({ data, onChange, onDelete }: GoldFormProps) {
  const style = LAYER_STYLES.gold
  return (
    <div className="p-5">
      <div className="flex items-center gap-2 mb-4">
        <div className={`h-3.5 w-1 rounded ${style.bar}`} />
        <span className={`text-xs font-bold tracking-widest ${style.textColor}`}>GOLD AGGREGATE</span>
      </div>

      <div className="grid grid-cols-3 gap-4">
      <div className="space-y-1.5">
        <Label className="text-xs">Name</Label>
        <Input value={data.name}
          onChange={(e) => onChange({ name: e.target.value.replace(/\s/g, "_") })}
          className="font-mono text-xs h-8"
          placeholder="daily_revenue"
        />
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">Aggregation</Label>
        <Select value={data.aggregation} onValueChange={(v) => { if (v) onChange({ aggregation: v }) }}>
          <SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger>
          <SelectContent>
            {AGGREGATION_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">Partition By</Label>
        <Input value={data.partitionBy}
          onChange={(e) => onChange({ partitionBy: e.target.value })}
          className="font-mono text-sm h-9" placeholder="date" />
      </div>

      <div className="space-y-1.5 col-span-2">
        <Label className="text-xs">Description</Label>
        <Input value={data.description}
          onChange={(e) => onChange({ description: e.target.value })}
          className="text-sm h-9" placeholder="일별 매출 집계 테이블" />
      </div>
      </div>{/* end grid */}

      <div className="mt-4 space-y-1.5">
        <Label className="text-xs font-medium flex items-center gap-2">
          SQL Aggregate
          <span className="text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-200">SQL</span>
        </Label>
        <Textarea value={data.sql}
          onChange={(e) => onChange({ sql: e.target.value })}
          className="font-mono text-[13px] resize-y leading-relaxed border-0 bg-slate-950 text-slate-100 rounded-lg focus-visible:ring-1 focus-visible:ring-blue-500"
          style={{ minHeight: 140 }}
          spellCheck={false}
        />
      </div>

      <div className="mt-4 pt-3 border-t">
        <button onClick={onDelete}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md
            bg-red-50 border border-red-200 text-red-700 hover:bg-red-100
            transition-colors text-xs font-medium">
          <Trash2 className="h-3.5 w-3.5" />Delete Node
        </button>
      </div>
    </div>
  )
}

interface PipelineFormProps {
  pipeline: PipelineState
  customSchedule: string
  code: string
  onChange: (patch: Partial<PipelineState>) => void
  onCustomScheduleChange: (v: string) => void
}

function PipelineForm({
  pipeline,
  customSchedule,
  code,
  onChange,
  onCustomScheduleChange,
}: PipelineFormProps) {
  const selectedSchedule = SCHEDULE_OPTIONS.find(o => o.value === pipeline.schedule)

  return (
    <div className="p-5 space-y-0 divide-y">

      {/* ── 1. Basic ─────────────────────────────────────────────── */}
      <div className="pb-5 grid grid-cols-3 gap-4">
        <p className="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">
          Basic
        </p>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium">
            Pipeline Name <span className="text-destructive">*</span>
          </Label>
          <Input
            value={pipeline.pipelineName}
            onChange={(e) => onChange({ pipelineName: e.target.value.replace(/[^a-z0-9_]/gi, "_") })}
            className="font-mono text-sm h-9"
            placeholder="my_pipeline"
          />
          <p className="text-[11px] text-muted-foreground">
            영문·숫자·언더스코어만 허용 (Airflow DAG ID로 사용)
          </p>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium">Description</Label>
          <Textarea
            value={pipeline.description}
            onChange={(e) => onChange({ description: e.target.value })}
            className="text-xs resize-none"
            rows={2}
            placeholder="이 파이프라인이 하는 일을 설명하세요"
          />
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium">Owner</Label>
          <Input
            value={pipeline.advanced.owner}
            onChange={(e) => onChange({ advanced: { ...pipeline.advanced, owner: e.target.value } })}
            className="text-xs h-8"
            placeholder="data-engineering-team"
          />
          <p className="text-[11px] text-muted-foreground">담당자 또는 팀 (Airflow DAG owner)</p>
        </div>
      </div>

      {/* ── 2. Schedule ──────────────────────────────────────────── */}
      <div className="py-5 space-y-3">
        <p className="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">
          Schedule
        </p>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium">Trigger</Label>
          <Select value={pipeline.schedule} onValueChange={(v) => { if (v) onChange({ schedule: v }) }}>
            <SelectTrigger className="h-9 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SCHEDULE_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  <div className="flex items-center justify-between gap-6 w-full">
                    <span className="font-medium">{o.label}</span>
                    {o.cron && (
                      <code className="text-[11px] text-muted-foreground font-mono">{o.cron}</code>
                    )}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* 선택된 스케줄 설명 */}
          {selectedSchedule && (
            <div className="flex items-center gap-2 rounded-md bg-muted/40 border px-3 py-2">
              {selectedSchedule.cron ? (
                <code className="text-xs font-mono text-foreground flex-1">{selectedSchedule.cron}</code>
              ) : (
                <span className="text-xs text-muted-foreground flex-1">{selectedSchedule.desc}</span>
              )}
              <span className="text-[11px] text-muted-foreground">{selectedSchedule.desc}</span>
            </div>
          )}
        </div>

        {pipeline.schedule === "custom" && (
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Cron Expression</Label>
            <Input
              value={customSchedule}
              onChange={(e) => onCustomScheduleChange(e.target.value)}
              className="font-mono text-sm h-9"
              placeholder="0 6 * * 1-5"
            />
            <div className="rounded-md bg-muted/40 border px-3 py-2 text-[11px] text-muted-foreground space-y-0.5">
              <p className="font-medium text-foreground text-xs mb-1">Cron 형식: 분 시 일 월 요일</p>
              <p><code className="font-mono">0 6 * * *</code> — 매일 오전 6시</p>
              <p><code className="font-mono">0 */4 * * *</code> — 4시간마다</p>
              <p><code className="font-mono">0 9 * * 1-5</code> — 평일 오전 9시</p>
              <p><code className="font-mono">30 23 * * 0</code> — 매주 일요일 23:30</p>
            </div>
          </div>
        )}

        <div className="flex items-center justify-between rounded-md border px-3 py-2.5">
          <div>
            <p className="text-xs font-medium">Catchup</p>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              과거 누락된 실행 자동 보완 (주의: 대량 실행 발생 가능)
            </p>
          </div>
          <Switch
            checked={pipeline.advanced.catchup}
            onCheckedChange={(v) => onChange({ advanced: { ...pipeline.advanced, catchup: v } })}
          />
        </div>
      </div>

      {/* ── 3. Tagging ───────────────────────────────────────────── */}
      <div className="py-5 space-y-3">
        <p className="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">
          Tags
        </p>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium">Tags</Label>
          <Input
            value={pipeline.advanced.tags}
            onChange={(e) => onChange({ advanced: { ...pipeline.advanced, tags: e.target.value } })}
            className="text-sm h-8"
            placeholder="sales, daily, production"
          />
          <p className="text-[11px] text-muted-foreground">
            쉼표로 구분 — Airflow UI 검색·필터링에 사용됩니다.{" "}
            <code className="bg-muted px-1 rounded">datapond-pipeline</code>은 자동 포함
          </p>
        </div>
      </div>

      {/* ── 4. Reliability ───────────────────────────────────────── */}
      <div className="py-5 space-y-3">
        <p className="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">
          Reliability
        </p>

        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Retries</Label>
            <Input
              value={pipeline.advanced.retries}
              onChange={(e) => onChange({ advanced: { ...pipeline.advanced, retries: e.target.value } })}
              type="number" min="0" max="10"
              className="font-mono text-sm h-8"
              placeholder="2"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Retry Delay (분)</Label>
            <Input
              value={pipeline.advanced.retryDelay}
              onChange={(e) => onChange({ advanced: { ...pipeline.advanced, retryDelay: e.target.value } })}
              type="number" min="1"
              className="font-mono text-sm h-8"
              placeholder="5"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium">Max Active Runs</Label>
          <Input
            value={pipeline.advanced.maxActiveRuns}
            onChange={(e) => onChange({ advanced: { ...pipeline.advanced, maxActiveRuns: e.target.value } })}
            type="number" min="1" max="10"
            className="font-mono text-sm h-8"
            placeholder="1"
          />
          <p className="text-[11px] text-muted-foreground">
            동시 실행 허용 DAG Run 수. 1 권장 (데이터 중복 방지)
          </p>
        </div>
      </div>

      {/* ── 5. Alerts ────────────────────────────────────────────── */}
      <div className="py-5 space-y-3">
        <p className="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">
          Alerts
        </p>

        <div className="flex items-center justify-between rounded-md border px-3 py-2.5">
          <div>
            <p className="text-xs font-medium">이메일 알림</p>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              파이프라인 실패·재시도 시 이메일 발송
            </p>
          </div>
          <Switch
            checked={pipeline.advanced.alertOnFailure}
            onCheckedChange={(v) => onChange({ advanced: { ...pipeline.advanced, alertOnFailure: v } })}
          />
        </div>

        {pipeline.advanced.alertOnFailure && (
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">수신 이메일</Label>
            <Input
              value={pipeline.advanced.alertEmail}
              onChange={(e) => onChange({ advanced: { ...pipeline.advanced, alertEmail: e.target.value } })}
              type="email"
              className="text-sm h-8"
              placeholder="oncall@company.com, data-team@company.com"
            />
            <p className="text-[11px] text-muted-foreground">
              콤마로 여러 주소 입력 가능 —
              실제 발송을 위해 Airflow SMTP 설정이 필요합니다
              (<a href="/settings" className="underline hover:text-foreground">Settings 참고</a>)
            </p>
          </div>
        )}

        {pipeline.advanced.alertOnFailure && !pipeline.advanced.alertEmail && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
            수신 이메일을 입력하지 않으면 알림이 전송되지 않습니다.
          </div>
        )}
      </div>

      {/* ── 4. Generated Code ────────────────────────────────────── */}
      <div className="p-4 space-y-2">
        <p className="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">
          Generated Code
        </p>
        <pre className="font-mono text-[10px] bg-muted/50 border p-3 rounded-lg
                        overflow-auto max-h-52 text-muted-foreground leading-relaxed
                        whitespace-pre">
          {code}
        </pre>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function NewPipelinePage() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [validateResult, setValidateResult] = useState<{
    success: boolean
    pipeline_name?: string
    warnings?: string[]
    errors?: string[]
  } | null>(null)
  const [deployResult, setDeployResult] = useState<{
    success: boolean
    pipeline_name: string
    dag_id: string
    dag_file: string
  } | null>(null)
  const [overwrite, setOverwrite] = useState(false)
  const [connections, setConnections] = useState<ApiConnection[]>([])
  const [customSchedule, setCustomSchedule] = useState("")
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [canvasHeight, setCanvasHeight] = useState(320)  // px, draggable
  const isResizingPanel = useRef(false)
  const [deployed, setDeployed] = useState(false)

  const [pipeline, setPipeline] = useState<PipelineState>({
    pipelineName: "my_pipeline",
    schedule: "@daily",
    description: "",
    advanced: {
      retries: "2",
      retryDelay: "5",
      owner: "data-team",
      alertOnFailure: true,
      alertEmail: "",
      tags: "datapond",
      catchup: false,
      maxActiveRuns: "1",
    },
  })

  const [nodes, setNodes, onNodesChange] = useNodesState<NodeData>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  // ── Undo / Redo history ────────────────────────────────────────────────────
  const historyRef = useRef<Array<{ nodes: Node<NodeData>[]; edges: Edge[] }>>([{ nodes: [], edges: [] }])
  const historyIdxRef = useRef(0)
  const [canUndo, setCanUndo] = useState(false)
  const [canRedo, setCanRedo] = useState(false)

  const saveHistoryWith = useCallback((ns: Node<NodeData>[], es: Edge[]) => {
    const h = historyRef.current.slice(0, historyIdxRef.current + 1)
    h.push({ nodes: ns.map(n => ({ ...n, data: { ...n.data } })), edges: es.map(e => ({ ...e })) })
    historyRef.current = h.length > 20 ? h.slice(h.length - 20) : h
    historyIdxRef.current = historyRef.current.length - 1
    setCanUndo(historyIdxRef.current > 0)
    setCanRedo(historyIdxRef.current < historyRef.current.length - 1)
  }, [])

  const undo = useCallback(() => {
    if (historyIdxRef.current <= 0) return
    historyIdxRef.current--
    const snap = historyRef.current[historyIdxRef.current]
    setNodes(snap.nodes as Node<NodeData>[])
    setEdges(snap.edges)
    setSelectedNodeId(null)
    setCanUndo(historyIdxRef.current > 0)
    setCanRedo(historyIdxRef.current < historyRef.current.length - 1)
  }, [setNodes, setEdges])

  const redo = useCallback(() => {
    if (historyIdxRef.current >= historyRef.current.length - 1) return
    historyIdxRef.current++
    const snap = historyRef.current[historyIdxRef.current]
    setNodes(snap.nodes as Node<NodeData>[])
    setEdges(snap.edges)
    setSelectedNodeId(null)
    setCanUndo(historyIdxRef.current > 0)
    setCanRedo(historyIdxRef.current < historyRef.current.length - 1)
  }, [setNodes, setEdges])

  useEffect(() => {
    fetch("/api/connectors/connections")
      .then((r) => r.json())
      .then((d) => setConnections(Array.isArray(d) ? d : []))
      .catch(() => {})
  }, [])

  // ── Keyboard shortcuts (Ctrl+Z / Ctrl+Y / Ctrl+K) ───────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey
      if (meta && e.key === "k") { e.preventDefault(); setSearchOpen(v => !v); setSearchQuery("") }
      if (e.key === "Escape") setSearchOpen(false)
      if (meta && e.key === "z" && !e.shiftKey) { e.preventDefault(); undo() }
      if (meta && (e.key === "y" || (e.key === "z" && e.shiftKey))) { e.preventDefault(); redo() }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [undo, redo])

  // ── Canvas / panel vertical resize ──────────────────────────────────────
  const startPanelResize = (e: React.MouseEvent) => {
    e.preventDefault()
    isResizingPanel.current = true
    const startY = e.clientY
    const startH = canvasHeight
    const onMove = (ev: MouseEvent) => {
      if (!isResizingPanel.current) return
      setCanvasHeight(Math.min(600, Math.max(150, startH + ev.clientY - startY)))
    }
    const onUp = () => {
      isResizingPanel.current = false
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup", onUp)
    }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
  }

  const onConnect = useCallback(
    (params: Connection) => {
      const sourceNode = nodes.find((n) => n.id === params.source)
      const targetNode = nodes.find((n) => n.id === params.target)
      // 역방향(하위→상위 레이어)만 차단, 동일 레이어간 + 건너뛰기 모두 허용
      const layerOrder: Record<string, number> = { bronze: 0, silver: 1, gold: 2 }
      const srcLayer = sourceNode?.data.layer ?? ""
      const tgtLayer = targetNode?.data.layer ?? ""
      if (layerOrder[srcLayer] === undefined || layerOrder[tgtLayer] === undefined) return
      if (layerOrder[srcLayer] > layerOrder[tgtLayer]) return  // 역방향 차단
      if (params.source === params.target) return              // 자기 자신 연결 차단
      const newEdges = addEdge({ ...params, ...DEFAULT_EDGE_OPTIONS } as Edge, edges)
      setEdges(newEdges)
      saveHistoryWith(nodes, newEdges)
    },
    [nodes, edges, setEdges, saveHistoryWith],
  )

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node<NodeData>) => {
    if (node.type === "layerHeader") return   // header nodes are non-interactive
    setSelectedNodeId(node.id)
    setDrawerOpen(true)
  }, [])

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null)
    setDrawerOpen(false)
  }, [])

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null

  const updateNode = useCallback(
    (id: string, patch: Partial<NodeData>) => {
      setNodes((nds) =>
        nds.map((n) =>
          n.id === id ? { ...n, data: { ...n.data, ...patch } as NodeData } : n,
        ),
      )
    },
    [setNodes],
  )

  const deleteNode = useCallback(
    (id: string) => {
      const newNodes = nodes.filter((n) => n.id !== id)
      const newEdges = edges.filter((e) => e.source !== id && e.target !== id)
      setNodes(newNodes)
      setEdges(newEdges)
      setSelectedNodeId(null)
      saveHistoryWith(newNodes, newEdges)
    },
    [nodes, edges, setNodes, setEdges, saveHistoryWith],
  )

  const addNode = useCallback(
    (layer: "bronze" | "silver" | "gold") => {
      const id = `${layer}-${uid()}`
      const xOffsets = { bronze: 80, silver: 380, gold: 680 }

      // Smart placement: stack below the lowest same-layer node
      const sameLayer = nodes.filter(n => n.type !== "layerHeader" && n.data.layer === layer)
      const yPos = sameLayer.length > 0 ? Math.max(...sameLayer.map(n => n.position.y)) + 145 : 80

      const baseData: Record<string, NodeData> = {
        bronze: {
          layer: "bronze",
          name: `raw_${uid()}`,
          connectionName: "",
          connectionType: "postgresql",
          table: "",
          mode: "incremental",
          watermarkColumn: "updated_at",
          primaryKey: "id",
          filterSql: "",
          batchSize: "",
        } as BronzeData,
        silver: {
          layer: "silver",
          name: `clean_${uid()}`,
          sql: "SELECT *\nFROM {{ source('') }}\n{{ incremental_filter('updated_at') }}",
          mode: "incremental",
          qualityCheck: "",
          partitionBy: "",
          primaryKey: "id",
          description: "",
        } as SilverData,
        gold: {
          layer: "gold",
          name: `agg_${uid()}`,
          aggregation: "daily",
          sql: "SELECT\n  date,\n  SUM(amount) as total\nFROM {{ ref('') }}\nGROUP BY 1",
          partitionBy: "date",
          description: "",
        } as GoldData,
      }

      const typeMap = { bronze: "bronzeNode", silver: "silverNode", gold: "goldNode" }

      const newNode: Node<NodeData> = {
        id,
        type: typeMap[layer],
        position: { x: xOffsets[layer], y: yPos },
        data: baseData[layer],
      }
      const newNodes = [...nodes, newNode]
      setNodes(newNodes)
      saveHistoryWith(newNodes, edges)
      setSelectedNodeId(id)
    },
    [nodes, edges, setNodes, saveHistoryWith],
  )

  const autoLayout = useCallback(() => {
    const { nodes: ln, edges: le } = getLayoutedElements(nodes, edges)
    setNodes(ln as Node<NodeData>[])
    setEdges(le)
  }, [nodes, edges, setNodes, setEdges])

  const effectiveSchedule =
    pipeline.schedule === "custom" ? customSchedule || "@daily" : pipeline.schedule

  const currentCode = generateCode(nodes, edges, {
    ...pipeline,
    schedule: effectiveSchedule,
  })

  const handleValidate = async () => {
    setLoading(true)
    setError(null)
    setValidateResult(null)
    try {
      const res = await fetch("/api/pipelines/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: currentCode }),
      })
      const data = await res.json()
      setValidateResult(data)
      if (!data.success) setError(data.errors?.join("\n") || "Validation failed")
    } catch (e) {
      setError(e instanceof Error ? e.message : "Validation failed")
    } finally {
      setLoading(false)
    }
  }

  const handleDeploy = async () => {
    setLoading(true)
    setError(null)
    try {
      const compRes = await fetch("/api/pipelines/compile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: currentCode }),
      })
      const compData = await compRes.json()
      if (!compData.success)
        throw new Error(compData.errors?.join("\n") || "Compile failed")

      const dagArtifact = compData.artifacts?.find(
        (a: { type: string; content: string }) => a.type === "airflow_dag",
      )
      if (!dagArtifact?.content) throw new Error("No DAG code generated")

      const deployRes = await fetch("/api/pipelines/deploy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_name: compData.pipeline_name,
          dag_code: dagArtifact.content,
          overwrite,
        }),
      })
      const deployData = await deployRes.json()
      if (deployRes.status === 409) {
        setError(`Pipeline '${compData.pipeline_name}' already exists.`)
        setOverwrite(true)
        return
      }
      if (!deployData.success) throw new Error(deployData.message || "Deploy failed")
      setDeployResult(deployData)
      setDeployed(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Deploy failed")
    } finally {
      setLoading(false)
    }
  }

  // ── Deployed success screen ─────────────────────────────────────────────────
  if (deployed && deployResult) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6">
        <div className="h-16 w-16 rounded-full bg-emerald-50 flex items-center justify-center">
          <CheckCircle2 className="h-8 w-8 text-emerald-600" />
        </div>
        <div className="text-center">
          <p className="text-xl font-semibold">Pipeline Deployed!</p>
          <p className="text-muted-foreground mt-1">Airflow will pick it up within 30 seconds</p>
        </div>
        <div className="rounded-lg border bg-muted/30 p-4 text-sm w-80 space-y-2">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Pipeline</span>
            <code className="font-mono">{deployResult.pipeline_name}</code>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">DAG ID</span>
            <code className="font-mono">{deployResult.dag_id}</code>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">File</span>
            <code className="font-mono text-xs">{deployResult.dag_file}</code>
          </div>
        </div>
        <div className="flex gap-3">
          <Button variant="outline" onClick={() => router.push("/pipelines")}>
            Back to Pipelines
          </Button>
          <Button
            onClick={() => {
              setDeployed(false)
              setDeployResult(null)
              setError(null)
              setValidateResult(null)
              setOverwrite(false)
            }}
          >
            Create Another
          </Button>
        </div>
      </div>
    )
  }

  // ── Main layout ─────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col" style={{ height: "calc(100vh - 56px)" }}>

      {/* Top toolbar */}
      <div className="flex items-center justify-between px-4 h-12 border-b shrink-0 bg-background gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 text-xs shrink-0"
            onClick={() => router.push("/pipelines")}
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </Button>
          <Separator orientation="vertical" className="h-4 shrink-0" />
          <Input
            value={pipeline.pipelineName}
            onChange={(e) =>
              setPipeline((p) => ({
                ...p,
                pipelineName: e.target.value.replace(/\s/g, "_"),
              }))
            }
            className="font-mono text-sm h-7 w-48 shrink-0"
            placeholder="pipeline_name"
          />
          {/* Schedule badge */}
          <span className="text-xs text-muted-foreground hidden sm:block">
            {effectiveSchedule !== "None" ? effectiveSchedule : "Manual"}
          </span>
          <Separator orientation="vertical" className="h-4 shrink-0" />
          <Button
            variant="ghost" size="sm"
            className="h-7 w-7 p-0 shrink-0"
            onClick={undo} disabled={!canUndo}
            title="Undo (Ctrl+Z)"
          >
            <Undo2 className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost" size="sm"
            className="h-7 w-7 p-0 shrink-0"
            onClick={redo} disabled={!canRedo}
            title="Redo (Ctrl+Y)"
          >
            <Redo2 className="h-3.5 w-3.5" />
          </Button>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {error && (
            <div className="flex items-center gap-1.5 text-xs text-destructive">
              <XCircle className="h-3.5 w-3.5 shrink-0" />
              <span className="max-w-48 truncate">{error}</span>
            </div>
          )}
          {validateResult?.success && (
            <div className="flex items-center gap-1.5 text-xs text-emerald-600">
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
              <span>Validated</span>
            </div>
          )}
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs gap-1.5"
            onClick={handleValidate}
            disabled={loading}
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5" />
            )}
            Validate
          </Button>
          <Button
            size="sm"
            className="h-8 text-xs gap-1.5"
            onClick={handleDeploy}
            disabled={loading}
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Rocket className="h-3.5 w-3.5" />
            )}
            {overwrite ? "Overwrite & Deploy" : "Deploy"}
          </Button>
        </div>
      </div>

      {/* Top: Canvas / Bottom: Tabbed Properties Panel */}
      <div className="flex flex-1 flex-col overflow-hidden">

        {/* ── Canvas — resizable top section ── */}
        <div className="relative overflow-hidden" style={{ height: canvasHeight }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            nodeTypes={nodeTypes}
            fitView
            className="bg-background"
          >
            <FocusNode nodeId={selectedNodeId} nodes={nodes} />
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#e2e8f0" />
            <Controls />
            <MiniMap
              nodeColor={(n) => {
                if (n.type === "bronzeNode") return "#f59e0b"
                if (n.type === "silverNode") return "#94a3b8"
                return "#eab308"
              }}
              className="!bottom-4 !right-3"
            />
            {/* no static layer labels — labels are injected as header nodes in the graph */}

            {/* Empty state overlay */}
            {nodes.length === 0 && (
              <Panel position="top-center">
                <div className="mt-16 flex flex-col items-center gap-4 text-center pointer-events-auto">
                  <div className="rounded-2xl border-2 border-dashed border-muted-foreground/20 bg-background/80 backdrop-blur px-10 py-8 space-y-3">
                    <p className="text-base font-semibold">빈 파이프라인</p>
                    <p className="text-sm text-muted-foreground max-w-xs">
                      하단 팔레트에서 노드를 추가하거나<br />예시 Medallion 파이프라인으로 시작하세요
                    </p>
                    <div className="flex gap-2 justify-center pt-1">
                      <button
                        onClick={() => addNode("bronze")}
                        className="px-3 py-1.5 rounded-lg border-2 border-amber-200 bg-amber-50
                          hover:bg-amber-100 text-xs font-medium text-amber-800 transition-colors"
                      >
                        + Bronze Source
                      </button>
                      <button
                        onClick={() => {
                          setNodes(EXAMPLE_NODES.map(n => ({...n})))
                          setEdges(EXAMPLE_EDGES.map(e => ({...e})))
                          setTimeout(autoLayout, 50)
                        }}
                        className="px-3 py-1.5 rounded-lg border bg-background
                          hover:bg-muted text-xs font-medium text-muted-foreground transition-colors"
                      >
                        예시 불러오기
                      </button>
                    </div>
                  </div>
                </div>
              </Panel>
            )}
          </ReactFlow>
        </div>

        {/* ── Drag handle ── */}
        <div
          onMouseDown={startPanelResize}
          className="h-1.5 shrink-0 cursor-row-resize bg-border/40
                     hover:bg-primary/50 active:bg-primary/70 transition-colors"
          title="드래그해서 캔버스 / 패널 비율 조절"
        />

        {/* ── Bottom: Tabbed Properties Panel ── */}
        <div className="flex flex-col border-t bg-background overflow-hidden"
          style={{ height: `calc(100% - ${canvasHeight}px - 6px)` }}>

          {/* Tab bar */}
          <div
            className="flex items-center border-b bg-muted/20 shrink-0 overflow-x-auto"
            style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' } as React.CSSProperties}
          >
            {/* Pipeline Config tab — always first */}
            <button
              onClick={() => setSelectedNodeId(null)}
              className={`flex items-center gap-1.5 px-4 h-9 text-xs font-medium whitespace-nowrap
                border-b-2 transition-colors shrink-0
                ${!selectedNode
                  ? "border-primary text-primary bg-background"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/40"
                }`}
            >
              <Settings2 className="h-3.5 w-3.5" />
              Pipeline Config
            </button>

            <div className="w-px h-5 bg-border mx-0.5 shrink-0" />

            {/* Dynamic node tabs — one per node */}
            {nodes.filter(n => n.type !== "layerHeader").map((n) => {
              const d = n.data as BronzeData | SilverData | GoldData
              const color = n.data.layer === "bronze" ? "bg-amber-500"
                : n.data.layer === "silver" ? "bg-slate-400" : "bg-yellow-400"
              const isActive = selectedNodeId === n.id
              return (
                <button
                  key={n.id}
                  onClick={() => setSelectedNodeId(n.id)}
                  className={`flex items-center gap-1.5 px-3 h-9 text-xs font-medium whitespace-nowrap
                    border-b-2 transition-colors shrink-0
                    ${isActive
                      ? "border-primary text-foreground bg-background"
                      : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/40"
                    }`}
                >
                  <div className={`h-2 w-1 rounded-full ${color}`} />
                  {d.name || `${n.data.layer}-${n.id.slice(-4)}`}
                </button>
              )
            })}

            {/* Node count + search shortcut */}
            <div className="ml-auto flex items-center gap-2 px-3 shrink-0">
              <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                {nodes.filter(n => n.type !== "layerHeader").length} nodes
              </span>
              <button
                onClick={() => { setSearchOpen(true); setSearchQuery("") }}
                className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground border rounded px-1.5 py-0.5 transition-colors"
                title="Search nodes (Ctrl+K)"
              >
                <Search className="h-2.5 w-2.5" />
                <span>⌘K</span>
              </button>
            </div>
          </div>

          {/* Tab content — scrollable, 2-column grid */}
          <div className="flex-1 overflow-y-auto">
            {selectedNode?.data.layer === "bronze" && (
              <BronzeForm
                data={selectedNode.data as BronzeData}
                connections={connections}
                onChange={(patch) => updateNode(selectedNode.id, patch)}
                onDelete={() => deleteNode(selectedNode.id)}
              />
            )}
            {selectedNode?.data.layer === "silver" && (
              <SilverForm
                data={selectedNode.data as SilverData}
                onChange={(patch) => updateNode(selectedNode.id, patch)}
                onDelete={() => deleteNode(selectedNode.id)}
              />
            )}
            {selectedNode?.data.layer === "gold" && (
              <GoldForm
                data={selectedNode.data as GoldData}
                onChange={(patch) => updateNode(selectedNode.id, patch)}
                onDelete={() => deleteNode(selectedNode.id)}
              />
            )}
            {!selectedNode && (
              <PipelineForm
                pipeline={pipeline}
                customSchedule={customSchedule}
                code={currentCode}
                onChange={(patch) => setPipeline((p) => ({ ...p, ...patch }))}
                onCustomScheduleChange={setCustomSchedule}
              />
            )}
          </div>
        </div>
      </div>

      {/* Bottom palette bar */}
      <div className="h-14 border-t bg-muted/20 flex items-center gap-3 px-6 shrink-0">
        <span className="text-xs text-muted-foreground font-medium mr-2">Add Node:</span>

        {/* Bronze */}
        <button
          onClick={() => addNode("bronze")}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border-2 border-amber-200
            bg-amber-50 hover:bg-amber-100 transition-colors text-xs font-medium text-amber-800"
        >
          <div className="h-3 w-0.5 bg-amber-500 rounded" />
          Bronze Source
        </button>

        {/* Silver */}
        <button
          onClick={() => addNode("silver")}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border-2 border-slate-200
            bg-slate-50 hover:bg-slate-100 transition-colors text-xs font-medium text-slate-700"
        >
          <div className="h-3 w-0.5 bg-slate-400 rounded" />
          Silver Transform
        </button>

        {/* Gold */}
        <button
          onClick={() => addNode("gold")}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border-2 border-yellow-200
            bg-yellow-50 hover:bg-yellow-100 transition-colors text-xs font-medium text-yellow-800"
        >
          <div className="h-3 w-0.5 bg-yellow-400 rounded" />
          Gold Aggregate
        </button>

        {/* Search */}
        <button
          onClick={() => { setSearchOpen(true); setSearchQuery("") }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border bg-background hover:bg-muted transition-colors text-xs text-muted-foreground"
          title="Search nodes (Ctrl+K)"
        >
          <Search className="h-3.5 w-3.5" />
          Search
        </button>

        <div className="flex-1" />

        {/* Auto Layout */}
        <button
          onClick={autoLayout}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border bg-background
            hover:bg-muted transition-colors text-xs text-muted-foreground"
        >
          <LayoutGrid className="h-3.5 w-3.5" />
          Auto Layout
        </button>
      </div>

      {/* Search overlay (Cmd+K) */}
      {searchOpen && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center pt-28 bg-black/40 backdrop-blur-sm"
          onClick={() => setSearchOpen(false)}
        >
          <div
            className="bg-background rounded-xl border shadow-2xl w-full max-w-md overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 px-4 py-3 border-b">
              <Search className="h-4 w-4 text-muted-foreground shrink-0" />
              <input
                autoFocus
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search nodes by name..."
                className="flex-1 text-sm outline-none bg-transparent placeholder:text-muted-foreground"
              />
              <kbd className="text-[10px] text-muted-foreground border rounded px-1.5 py-0.5 shrink-0">esc</kbd>
            </div>
            <div className="max-h-72 overflow-y-auto py-1">
              {(() => {
                const q = searchQuery.toLowerCase()
                const filtered = nodes
                  .filter(n => n.type !== "layerHeader")
                  .filter(n => !q || (n.data as NodeData).name?.toLowerCase().includes(q))
                if (filtered.length === 0) return (
                  <p className="px-4 py-8 text-center text-sm text-muted-foreground">No nodes found</p>
                )
                return filtered.map(n => {
                  const d = n.data as BronzeData | SilverData | GoldData
                  const dot = n.data.layer === "bronze" ? "bg-amber-500" : n.data.layer === "silver" ? "bg-slate-400" : "bg-yellow-400"
                  const badge = n.data.layer === "bronze" ? "bg-amber-50 text-amber-700" : n.data.layer === "silver" ? "bg-slate-100 text-slate-600" : "bg-yellow-50 text-yellow-700"
                  return (
                    <button
                      key={n.id}
                      className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted/60 text-sm transition-colors"
                      onClick={() => {
                        setSelectedNodeId(n.id)
                        setSearchOpen(false)
                        setSearchQuery("")
                      }}
                    >
                      <div className={`h-2 w-2 rounded-full shrink-0 ${dot}`} />
                      <span className="font-mono flex-1 text-left truncate">{d.name || n.id}</span>
                      <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded capitalize ${badge}`}>{n.data.layer}</span>
                    </button>
                  )
                })
              })()}
            </div>
            <div className="border-t px-4 py-2 flex items-center gap-4 text-[11px] text-muted-foreground bg-muted/20">
              <span><kbd className="border rounded px-1">↑↓</kbd> navigate</span>
              <span><kbd className="border rounded px-1">↵</kbd> select</span>
              <span><kbd className="border rounded px-1">esc</kbd> close</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
