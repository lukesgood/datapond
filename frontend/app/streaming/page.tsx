"use client"

import { useEffect, useState, useRef } from "react"
import { useConfirm } from "@/lib/confirm"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import {
  AlertCircle, CheckCircle2, XCircle,
  Plus, Trash2, Play, Eye, ArrowRight,
  ChevronRight, ChevronDown, Code2, Loader2, Zap, RefreshCw,
  Radio, Database, Search, AlertTriangle, Copy,
} from "lucide-react"


// ── Types ──────────────────────────────────────────────────────────────────────

interface ClusterInfo {
  status: "healthy" | "degraded" | "down"
  version: string; worker_count: number
  source_count: number; sink_count: number; mv_count: number
}

interface Source {
  id: number; name: string; connector: string
  format: string; row_encode: string; definition: string; created_at: string
}

interface Sink {
  id: number; name: string; connector: string
  sink_type: string; definition: string; created_at: string
}

interface MV {
  id: number; name: string; definition: string; created_at: string
}

interface DdlProgress {
  ddl_id: number; ddl_statement: string; progress: string
}

interface SqlResult {
  columns?: string[]; rows?: any[][]; row_count?: number
  execution_time_ms?: number; message?: string
}

// ── CDC Prerequisites (shown on marketplace card) ─────────────────────────────

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={e => { e.stopPropagation(); navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
      className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
    >
      <Copy className="h-3 w-3" />{copied ? "Copied!" : "Copy"}
    </button>
  )
}

const CDC_PREREQS = [
  {
    label: "WAL Level = logical",
    desc: "PostgreSQL must use logical replication. Requires DB restart.",
    sql: `-- Run as superuser, then restart PostgreSQL
ALTER SYSTEM SET wal_level = logical;`,
  },
  {
    label: "REPLICATION privilege",
    desc: "The connecting user must have REPLICATION role.",
    sql: `ALTER ROLE {user} REPLICATION LOGIN;`,
  },
  {
    label: "CREATE on database",
    desc: "Required to create replication slots.",
    sql: `GRANT CREATE ON DATABASE {db} TO {user};`,
  },
]

function CdcPrereqPanel({ dbName, dbUser }: { dbName?: string; dbUser?: string }) {
  const [open, setOpen] = useState(false)
  const db = dbName || "your_db"
  const user = dbUser || "your_user"

  return (
    <div className="mt-2.5 rounded-lg border border-amber-200 bg-amber-50/70 overflow-hidden">
      <button
        onClick={e => { e.stopPropagation(); setOpen(v => !v) }}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0" />
        <span className="text-xs font-medium text-amber-800">Prerequisites required</span>
        <ChevronDown className={`h-3.5 w-3.5 text-amber-500 ml-auto transition-transform duration-150 ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="border-t border-amber-200 px-3 pb-3 space-y-3">
          {CDC_PREREQS.map((p, i) => (
            <div key={i} className="pt-2.5">
              <p className="text-xs font-semibold text-amber-800">{i + 1}. {p.label}</p>
              <p className="text-[11px] text-amber-700 mt-0.5 mb-1.5">{p.desc}</p>
              <div className="relative rounded bg-amber-900/8 border border-amber-200 px-3 py-1.5">
                <pre className="text-[11px] font-mono text-amber-900 whitespace-pre-wrap pr-12">
                  {p.sql.replace("{db}", db).replace(/{user}/g, user)}
                </pre>
                <div className="absolute top-1.5 right-2">
                  <CopyBtn text={p.sql.replace("{db}", db).replace(/{user}/g, user)} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Streaming sources (marketplace) ───────────────────────────────────────────

const STREAMING_SOURCES = [
  { id: "postgres-cdc", type: "cdc",   name: "PostgreSQL CDC",   icon: "🐘",
    description: "WAL 기반 실시간 변경 캡처 (INSERT / UPDATE / DELETE)",
    features: ["Zero latency", "No source load", "DELETE 반영"], available: true },
  { id: "mysql-cdc",    type: "cdc",   name: "MySQL CDC",         icon: "🐬",
    description: "binlog 기반 MySQL / MariaDB 실시간 변경 캡처",
    features: ["binlog 기반", "MariaDB 지원"], available: false },
  { id: "kafka",        type: "event", name: "Apache Kafka",      icon: "📨",
    description: "Kafka 토픽을 Iceberg 테이블로 실시간 수집",
    features: ["JSON / Avro / CSV", "Schema Registry"], available: true },
  { id: "kinesis",      type: "event", name: "Amazon Kinesis",    icon: "☁️",
    description: "AWS Kinesis Data Streams → Iceberg",
    features: ["AWS 네이티브", "at-least-once"], available: true },
  { id: "pulsar",       type: "event", name: "Apache Pulsar",     icon: "⚡",
    description: "Pulsar 토픽 스트리밍",
    features: ["멀티테넌시"], available: false },
] as const

// ── SQL Templates ──────────────────────────────────────────────────────────────

const SQL_TEMPLATES = [
  {
    label: "Kafka Source",
    sql: `CREATE SOURCE my_source (
  user_id   BIGINT,
  event     VARCHAR,
  ts        TIMESTAMPTZ
) WITH (
  connector = 'kafka',
  topic = 'my-topic',
  properties.bootstrap.server = 'kafka:9092',
  scan.startup.mode = 'latest'
) FORMAT PLAIN ENCODE JSON;`,
  },
  {
    label: "Materialized View",
    sql: `CREATE MATERIALIZED VIEW my_view AS
SELECT
  date_trunc('minute', ts) AS minute,
  event,
  COUNT(*) AS cnt
FROM my_source
GROUP BY 1, 2;`,
  },
  {
    label: "Iceberg Sink",
    sql: `CREATE SINK my_sink
FROM my_view
WITH (
  connector      = 'iceberg',
  type           = 'append-only',
  catalog.type   = 'storage',
  warehouse.path = 's3a://iceberg/warehouse',
  s3.endpoint    = 'http://seaweedfs-s3:8333',
  s3.access.key  = 'datapond',
  s3.secret.key  = 'datapond_dev',
  database.name  = 'default',
  table.name     = 'my_view'
);`,
  },
  {
    label: "List Sources",
    sql: "SELECT id, name, connector, format FROM rw_catalog.rw_sources;",
  },
  {
    label: "List MVs",
    sql: "SELECT id, name, created_at FROM rw_catalog.rw_materialized_views;",
  },
  {
    label: "List Sinks",
    sql: "SELECT id, name, connector, sink_type FROM rw_catalog.rw_sinks;",
  },
]

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtDate(s: string | null) {
  if (!s) return "—"
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
  }).format(new Date(s))
}

// ── Pipeline grouping helper ───────────────────────────────────────────────────
// CDC pipelines are named: {pipeline}_{table}_src / _mv / _sink
// Event pipelines are named: {pipeline}_src / _mv / _sink
// Group by common prefix to show one row per pipeline

interface PipelineGroup {
  name: string          // pipeline prefix
  tables: string[]      // table names
  sources: string[]     // source object names
  views: string[]       // mv object names
  sinks: string[]       // sink object names
  connector: string     // postgres-cdc / kafka / kinesis / etc
  pipeline_type: "cdc" | "event" | "custom"
  created_at: string
}

function getPipelineType(connector: string): "cdc" | "event" | "custom" {
  if (connector === "postgres-cdc") return "cdc"
  if (connector === "kafka" || connector === "kinesis") return "event"
  return "custom"
}

function groupPipelines(sources: Source[], views: MV[], sinks: Sink[]): PipelineGroup[] {
  const map = new Map<string, PipelineGroup>()

  for (const s of sources) {
    if (!s.name.endsWith("_src")) continue
    const prefix = s.name.slice(0, -4)  // strip _src
    const parts = prefix.split("_")

    let pipelineName: string
    let table: string

    if (parts.length === 1) {
      // e.g. "orders_src" → pipeline="orders", table=""
      pipelineName = parts[0]
      table = ""
    } else {
      // e.g. "orders_cdc_customers_src" → pipeline="orders_cdc", table="customers"
      // vs "sample_clickstream_src" → pipeline="sample", table="clickstream"
      // Use last segment as table, rest as pipeline
      table = parts[parts.length - 1]
      pipelineName = parts.slice(0, -1).join("_")
    }

    if (!pipelineName) continue
    if (!map.has(pipelineName)) {
      map.set(pipelineName, {
        name: pipelineName, tables: [], sources: [], views: [], sinks: [],
        connector: s.connector, pipeline_type: getPipelineType(s.connector),
        created_at: s.created_at
      })
    }
    const g = map.get(pipelineName)!
    if (table && !g.tables.includes(table)) g.tables.push(table)
    g.sources.push(s.name)
  }

  // _mv matching — try pipeline_table_mv first, then pipeline_mv
  for (const v of views) {
    if (!v.name.endsWith("_mv")) continue
    const prefix = v.name.slice(0, -3)
    const parts = prefix.split("_")
    // Try longest pipeline name match
    for (let i = parts.length - 1; i >= 1; i--) {
      const pipelineName = parts.slice(0, i).join("_")
      if (map.has(pipelineName)) {
        map.get(pipelineName)!.views.push(v.name)
        break
      }
    }
    // Also try full prefix as pipeline name (no table segment)
    if (map.has(prefix)) map.get(prefix)!.views.push(v.name)
  }

  // _sink matching
  for (const s of sinks) {
    if (!s.name.endsWith("_sink")) continue
    const prefix = s.name.slice(0, -5)
    const parts = prefix.split("_")
    for (let i = parts.length - 1; i >= 1; i--) {
      const pipelineName = parts.slice(0, i).join("_")
      if (map.has(pipelineName)) {
        map.get(pipelineName)!.sinks.push(s.name)
        break
      }
    }
    if (map.has(prefix)) map.get(prefix)!.sinks.push(s.name)
  }

  return Array.from(map.values()).sort((a, b) => b.created_at.localeCompare(a.created_at))
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function StreamingPage() {
  const router = useRouter()
  const [cluster, setCluster] = useState<ClusterInfo | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [sinks, setSinks] = useState<Sink[]>([])
  const [views, setViews] = useState<MV[]>([])
  const [progress, setProgress] = useState<DdlProgress[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // SQL Console
  const [sql, setSql] = useState("")
  const [sqlResult, setSqlResult] = useState<SqlResult | null>(null)
  const [sqlError, setSqlError] = useState<string | null>(null)
  const [sqlRunning, setSqlRunning] = useState(false)
  const sqlRef = useRef<HTMLTextAreaElement>(null)

  // Preview dialog
  const [previewMv, setPreviewMv] = useState<MV | null>(null)
  const [previewData, setPreviewData] = useState<SqlResult | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  // DDL dialogs
  const [showDdl, setShowDdl] = useState<string | null>(null)

  // Pipeline row expansion
  const [expandedPipeline, setExpandedPipeline] = useState<string | null>(null)

  // Tab control — ?tab=add-source from back navigation
  const [activeTab, setActiveTab] = useState(() =>
    typeof window !== "undefined" && new URLSearchParams(window.location.search).get("tab") === "add-source"
      ? "add-source" : "streams"
  )

  // Add Source tab filter state
  const [sourceSearch, setSourceSearch] = useState("")
  const [sourceCat, setSourceCat] = useState("all")

  const fetchAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [clusterRes, sourcesRes, sinksRes, viewsRes, progressRes] = await Promise.all([
        fetch("/api/streaming/cluster"),
        fetch("/api/streaming/sources"),
        fetch("/api/streaming/sinks"),
        fetch("/api/streaming/views"),
        fetch("/api/streaming/progress"),
      ])
      if (clusterRes.ok) setCluster(await clusterRes.json())
      if (sourcesRes.ok) setSources(await sourcesRes.json())
      if (sinksRes.ok) setSinks(await sinksRes.json())
      if (viewsRes.ok) setViews(await viewsRes.json())
      if (progressRes.ok) setProgress(await progressRes.json())
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchAll() }, [])

  // Auto-refresh progress while DDL running
  useEffect(() => {
    if (progress.length === 0) return
    const t = setInterval(async () => {
      const r = await fetch("/api/streaming/progress")
      if (r.ok) setProgress(await r.json())
    }, 2000)
    return () => clearInterval(t)
  }, [progress.length])

  const runSql = async () => {
    if (!sql.trim()) return
    setSqlRunning(true)
    setSqlResult(null)
    setSqlError(null)
    try {
      const res = await fetch("/api/streaming/sql", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql }),
      })
      const data = await res.json()
      if (!res.ok) { setSqlError(data.detail ?? "Error"); return }
      setSqlResult(data)
      fetchAll()
    } catch (e) {
      setSqlError(e instanceof Error ? e.message : "Error")
    } finally {
      setSqlRunning(false)
    }
  }

  const confirm = useConfirm()
  const handleDrop = async (type: string, name: string) => {
    if (!(await confirm({ title: `${type} 삭제`, message: `"${name}" 를 삭제할까요?`, destructive: true, confirmText: "삭제" }))) return
    await fetch(`/api/streaming/${type}/${name}`, { method: "DELETE" })
    fetchAll()
  }

  const handlePreview = async (mv: MV) => {
    setPreviewMv(mv)
    setPreviewLoading(true)
    const res = await fetch(`/api/streaming/views/${mv.name}/data?limit=50`)
    if (res.ok) setPreviewData(await res.json())
    setPreviewLoading(false)
  }

  const handleDropPipeline = async (pipeline: PipelineGroup) => {
    if (!(await confirm({ title: "파이프라인 삭제", message: `"${pipeline.name}" 와 연관 객체 ${pipeline.tables.length * 3}개를 삭제합니다.`, destructive: true, confirmText: "삭제" }))) return
    for (const name of pipeline.sinks)   await fetch(`/api/streaming/sinks/${name}`,   { method: "DELETE" })
    for (const name of pipeline.views)   await fetch(`/api/streaming/views/${name}`,   { method: "DELETE" })
    for (const name of pipeline.sources) await fetch(`/api/streaming/sources/${name}`, { method: "DELETE" })
    fetchAll()
  }

  const pipelines = groupPipelines(sources, views, sinks)

  const statusColor = cluster?.status === "healthy" ? "text-green-600"
    : cluster?.status === "degraded" ? "text-amber-500" : "text-red-500"
  const StatusIcon = cluster?.status === "healthy" ? CheckCircle2
    : cluster?.status === "degraded" ? AlertCircle : XCircle

  // Find source/mv/sink objects for a given pipeline object name
  const findSourceObj = (name: string) => sources.find(s => s.name === name)
  const findViewObj   = (name: string) => views.find(v => v.name === name)
  const findSinkObj   = (name: string) => sinks.find(s => s.name === name)

  return (
    <div className="flex-1 space-y-5 px-6 py-5">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Streaming</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Real-time CDC pipelines via RisingWave — captures every change with sub-second latency
          </p>
        </div>
        <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5"
          onClick={fetchAll} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />{error}
        </div>
      )}

      {/* DDL Progress banner */}
      {progress.length > 0 && (
        <div className="rounded-lg border border-blue-300 bg-blue-50/50 px-4 py-3 space-y-1">
          <p className="text-xs font-medium text-blue-700 flex items-center gap-1.5">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            DDL in progress ({progress.length} job{progress.length > 1 ? "s" : ""})
          </p>
          {progress.map(p => (
            <p key={p.ddl_id} className="text-xs text-blue-600 font-mono truncate">
              {p.ddl_statement} — {p.progress}
            </p>
          ))}
        </div>
      )}

      {/* Cluster status banner */}
      <div className="flex items-center gap-4 px-4 py-2.5 rounded-lg border bg-muted/30 text-sm">
        {loading ? (
          <Skeleton className="h-4 w-48" />
        ) : (
          <>
            <span className="flex items-center gap-1.5">
              <StatusIcon className={`h-4 w-4 ${statusColor}`} />
              <span className="font-medium">RisingWave</span>
              {cluster?.version && (
                <span className="text-muted-foreground">{cluster.version}</span>
              )}
            </span>
            <Separator orientation="vertical" className="h-4" />
            <span className="text-muted-foreground">{pipelines.length} pipeline{pipelines.length !== 1 ? "s" : ""}</span>
            <Separator orientation="vertical" className="h-4" />
            <span className="text-muted-foreground">{cluster?.worker_count ?? "—"} worker{(cluster?.worker_count ?? 0) !== 1 ? "s" : ""}</span>
          </>
        )}
      </div>

      {/* Main tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="h-8">
          <TabsTrigger value="streams" className="text-xs h-7 gap-1.5">
            <Zap className="h-3.5 w-3.5" />
            Active Streams
            {pipelines.length > 0 && (
              <Badge variant="secondary" className="text-[9px] h-4 px-1 ml-0.5">{pipelines.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="add-source" className="text-xs h-7 gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            Add Source
          </TabsTrigger>
          <TabsTrigger value="console" className="text-xs h-7">SQL Console</TabsTrigger>
        </TabsList>

        {/* ── Pipelines (default) ── */}
        <TabsContent value="streams" className="mt-4">
          {loading ? (
            <div className="rounded-lg border overflow-hidden">
              <Table>
                <TableHeader className="bg-muted/40">
                  <TableRow>{["Pipeline","Type","Connector","Tables","Objects","Created",""].map(h => <TableHead key={h} className="text-xs">{h}</TableHead>)}</TableRow>
                </TableHeader>
                <TableBody>
                  {Array(3).fill(0).map((_, i) => (
                    <TableRow key={i}>{Array(6).fill(0).map((_, j) => <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>)}</TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : pipelines.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 space-y-4 text-center border rounded-lg bg-muted/20">
              <div className="rounded-full bg-primary/10 p-4">
                <Zap className="h-8 w-8 text-primary" />
              </div>
              <div>
                <p className="font-medium">No streaming pipelines yet</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Capture database changes or stream events from Kafka/Kinesis into Iceberg
                </p>
              </div>
              <div className="flex items-center gap-3">
                <Button onClick={() => setActiveTab("add-source")} className="gap-1.5">
                  <Plus className="h-4 w-4" />Add Source
                </Button>
                <Button variant="outline" className="gap-1.5" onClick={async () => {
                  const res = await fetch("/api/streaming/sample-streams", { method: "POST" })
                  if (res.ok) fetchAll()
                }}>
                  <Play className="h-4 w-4" />Make Sample Streams
                </Button>
              </div>
              <div className="flex items-center gap-6 text-xs text-muted-foreground">
                <span className="flex items-center gap-1"><ArrowRight className="h-3 w-3" />Source → RisingWave</span>
                <span className="flex items-center gap-1"><ArrowRight className="h-3 w-3" />Materialized View</span>
                <span className="flex items-center gap-1"><ArrowRight className="h-3 w-3" />Iceberg Sink</span>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border overflow-hidden">
              <Table>
                <TableHeader className="bg-muted/40">
                  <TableRow>
                    <TableHead className="text-xs w-6" />
                    <TableHead className="text-xs">Pipeline</TableHead>
                    <TableHead className="text-xs">Type</TableHead>
                    <TableHead className="text-xs">Connector</TableHead>
                    <TableHead className="text-xs">Tables</TableHead>
                    <TableHead className="text-xs">Objects</TableHead>
                    <TableHead className="text-xs">Created</TableHead>
                    <TableHead className="text-xs w-16" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pipelines.map(p => (
                    <>
                      <TableRow
                        key={p.name}
                        className="cursor-pointer hover:bg-muted/30"
                        onClick={() => setExpandedPipeline(prev => prev === p.name ? null : p.name)}
                      >
                        <TableCell className="pr-0">
                          {expandedPipeline === p.name
                            ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                            : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                        </TableCell>
                        <TableCell className="font-medium text-sm">{p.name}</TableCell>
                        <TableCell>
                          {p.pipeline_type === "cdc" && (
                            <Badge className="text-xs bg-primary/10 text-primary border-primary/20 hover:bg-primary/10">CDC</Badge>
                          )}
                          {p.pipeline_type === "event" && (
                            <Badge className="text-xs bg-purple-500/10 text-purple-600 border-purple-200 hover:bg-purple-500/10">Event</Badge>
                          )}
                          {p.pipeline_type === "custom" && (
                            <Badge variant="outline" className="text-xs">Custom</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-xs">{p.connector}</Badge>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1 max-w-[280px]">
                            {p.tables.map(t => (
                              <span key={t} className="text-[10px] font-mono bg-muted px-1.5 py-0.5 rounded">{t}</span>
                            ))}
                          </div>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {p.sources.length} src · {p.views.length} mv · {p.sinks.length} sink
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">{fmtDate(p.created_at)}</TableCell>
                        <TableCell onClick={e => e.stopPropagation()}>
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive"
                            onClick={() => handleDropPipeline(p)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </TableCell>
                      </TableRow>

                      {expandedPipeline === p.name && (
                        <TableRow key={`${p.name}-detail`}>
                          <TableCell colSpan={8} className="bg-muted/20 px-4 py-3">
                            <div className="space-y-2.5 text-xs">

                              {/* Sources */}
                              {p.sources.length > 0 && (
                                <div className="flex items-start gap-2">
                                  <span className="flex items-center gap-1 text-muted-foreground font-medium w-16 shrink-0 mt-0.5">
                                    <Radio className="h-3 w-3" />Sources
                                  </span>
                                  <div className="flex flex-wrap gap-2">
                                    {p.sources.map(sName => {
                                      const obj = findSourceObj(sName)
                                      return (
                                        <span key={sName} className="flex items-center gap-1.5 bg-background border rounded px-2 py-0.5 font-mono">
                                          {sName}
                                          {obj && (
                                            <button
                                              className="text-muted-foreground hover:text-foreground transition-colors"
                                              onClick={() => setShowDdl(obj.definition)}
                                              title="View DDL"
                                            >
                                              <Code2 className="h-3 w-3" />
                                            </button>
                                          )}
                                        </span>
                                      )
                                    })}
                                  </div>
                                </div>
                              )}

                              {/* Materialized Views */}
                              {p.views.length > 0 && (
                                <div className="flex items-start gap-2">
                                  <span className="flex items-center gap-1 text-muted-foreground font-medium w-16 shrink-0 mt-0.5">
                                    <Database className="h-3 w-3" />Views
                                  </span>
                                  <div className="flex flex-wrap gap-2">
                                    {p.views.map(vName => {
                                      const obj = findViewObj(vName)
                                      return (
                                        <span key={vName} className="flex items-center gap-1.5 bg-background border rounded px-2 py-0.5 font-mono">
                                          {vName}
                                          {obj && (
                                            <>
                                              <button
                                                className="text-muted-foreground hover:text-foreground transition-colors"
                                                onClick={() => handlePreview(obj)}
                                                title="Preview data"
                                              >
                                                <Eye className="h-3 w-3" />
                                              </button>
                                              <button
                                                className="text-muted-foreground hover:text-foreground transition-colors"
                                                onClick={() => setShowDdl(obj.definition)}
                                                title="View DDL"
                                              >
                                                <Code2 className="h-3 w-3" />
                                              </button>
                                            </>
                                          )}
                                        </span>
                                      )
                                    })}
                                  </div>
                                </div>
                              )}

                              {/* Sinks */}
                              {p.sinks.length > 0 && (
                                <div className="flex items-start gap-2">
                                  <span className="flex items-center gap-1 text-muted-foreground font-medium w-16 shrink-0 mt-0.5">
                                    <ArrowRight className="h-3 w-3" />Sinks
                                  </span>
                                  <div className="flex flex-wrap gap-2">
                                    {p.sinks.map(sName => {
                                      const obj = findSinkObj(sName)
                                      return (
                                        <span key={sName} className="flex items-center gap-1.5 bg-background border rounded px-2 py-0.5 font-mono">
                                          {sName}
                                          {obj && (
                                            <button
                                              className="text-muted-foreground hover:text-foreground transition-colors"
                                              onClick={() => setShowDdl(obj.definition)}
                                              title="View DDL"
                                            >
                                              <Code2 className="h-3 w-3" />
                                            </button>
                                          )}
                                        </span>
                                      )
                                    })}
                                  </div>
                                </div>
                              )}

                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>

        {/* ── Add Source ── */}
        <TabsContent value="add-source" className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Search sources..."
                className="pl-8 h-8 text-sm"
                value={sourceSearch}
                onChange={e => setSourceSearch(e.target.value)}
              />
            </div>
            <div className="flex gap-1">
              {[
                { id: "all",   label: "All" },
                { id: "cdc",   label: "CDC" },
                { id: "event", label: "Event Stream" },
              ].map(c => (
                <Button key={c.id} variant={sourceCat === c.id ? "secondary" : "ghost"}
                  size="sm" className="h-8 text-xs" onClick={() => setSourceCat(c.id)}>
                  {c.label}
                </Button>
              ))}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {STREAMING_SOURCES.filter(s => {
              const matchCat = sourceCat === "all" || s.type === sourceCat
              const q = sourceSearch.toLowerCase()
              const matchSearch = !q || s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q)
              return matchCat && matchSearch
            }).map(src => (
              <div key={src.id} className="flex flex-col">
                <button
                  disabled={!src.available}
                  onClick={() => { if (!src.available) return; router.push(`/streaming/new?source=${src.id}`) }}
                  className={`flex items-start gap-4 p-4 rounded-xl border text-left transition-all group ${
                    src.available
                      ? "border-border hover:border-primary hover:shadow-sm hover:bg-primary/5 cursor-pointer bg-card"
                      : "border-border/50 opacity-40 cursor-not-allowed bg-muted/20"
                  }`}
                >
                  <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-muted text-2xl shrink-0">
                    {src.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-semibold">{src.name}</span>
                      {!src.available && <Badge variant="secondary" className="text-[10px] h-4 px-1">Soon</Badge>}
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">{src.description}</p>
                    <div className="flex flex-wrap gap-1 mt-2">
                      {src.features.map(f => (
                        <span key={f} className="text-[10px] bg-muted px-1.5 py-0.5 rounded font-medium">{f}</span>
                      ))}
                    </div>
                  </div>
                  {src.available && (
                    <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity" />
                  )}
                </button>
                {/* CDC prerequisites panel — outside card button to prevent click propagation */}
                {src.type === "cdc" && src.available && (
                  <CdcPrereqPanel />
                )}
              </div>
            ))}
          </div>

          <div className="border-t pt-3 flex justify-between text-xs text-muted-foreground">
            <span>{STREAMING_SOURCES.filter(s => s.available).length} available</span>
            <span>{STREAMING_SOURCES.filter(s => !s.available).length} coming soon</span>
          </div>
        </TabsContent>

        {/* ── SQL Console ── */}
        <TabsContent value="console" className="mt-4 space-y-3">
          {/* Templates */}
          <div className="flex gap-2 flex-wrap">
            <span className="text-xs text-muted-foreground self-center">Templates:</span>
            {SQL_TEMPLATES.map(t => (
              <Button key={t.label} variant="outline" size="sm" className="h-7 text-xs"
                onClick={() => setSql(t.sql)}>
                {t.label}
              </Button>
            ))}
          </div>

          {/* Editor */}
          <div className="rounded-lg border overflow-hidden">
            <textarea
              ref={sqlRef}
              value={sql}
              onChange={e => setSql(e.target.value)}
              onKeyDown={e => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); runSql() }
              }}
              className="w-full h-52 p-3 font-mono text-sm bg-background resize-none focus:outline-none"
              placeholder="-- Write RisingWave SQL here (⌘+Enter to run)&#10;-- CREATE SOURCE, CREATE MATERIALIZED VIEW, CREATE SINK, SELECT, DROP..."
              spellCheck={false}
            />
            <div className="flex items-center justify-between px-3 py-2 bg-muted/30 border-t">
              <span className="text-xs text-muted-foreground">⌘ + Enter to run</span>
              <Button size="sm" className="h-7 text-xs gap-1.5"
                onClick={runSql} disabled={sqlRunning}>
                {sqlRunning
                  ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />Running…</>
                  : <><Play className="h-3.5 w-3.5" />Run</>}
              </Button>
            </div>
          </div>

          {/* Error */}
          {sqlError && (
            <div className="rounded-md bg-destructive/10 border border-destructive/30 px-4 py-3 text-sm text-destructive font-mono whitespace-pre-wrap">
              {sqlError}
            </div>
          )}

          {/* Results */}
          {sqlResult && (
            <div className="rounded-lg border overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2 bg-muted/30 border-b text-xs text-muted-foreground">
                {sqlResult.columns
                  ? <span>{sqlResult.row_count} rows · {sqlResult.execution_time_ms}ms</span>
                  : <span className="text-green-600">{sqlResult.message} · {sqlResult.execution_time_ms}ms</span>}
              </div>
              {sqlResult.columns && sqlResult.rows && (
                <div className="overflow-x-auto max-h-72 overflow-y-auto">
                  <Table>
                    <TableHeader className="bg-muted/20 sticky top-0">
                      <TableRow>
                        {sqlResult.columns.map(c => (
                          <TableHead key={c} className="text-xs font-mono">{c}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {sqlResult.rows.map((row, i) => (
                        <TableRow key={i}>
                          {row.map((cell, j) => (
                            <TableCell key={j} className="text-xs font-mono">
                              {cell === null ? <span className="text-muted-foreground italic">null</span> : String(cell)}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* ── DDL Viewer ── */}
      <Dialog open={!!showDdl} onOpenChange={() => setShowDdl(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>DDL Definition</DialogTitle>
          </DialogHeader>
          <pre className="rounded-md bg-muted p-4 text-xs font-mono whitespace-pre-wrap overflow-x-auto max-h-96">
            {showDdl}
          </pre>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setSql(showDdl ?? ""); setShowDdl(null) }}>
              Open in Console
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── MV Preview ── */}
      <Dialog open={!!previewMv} onOpenChange={() => { setPreviewMv(null); setPreviewData(null) }}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>{previewMv?.name}</DialogTitle>
            <DialogDescription>First 50 rows</DialogDescription>
          </DialogHeader>
          {previewLoading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
          ) : previewData?.rows && previewData.rows.length > 0 ? (
            <div className="overflow-auto max-h-96">
              <Table>
                <TableHeader className="sticky top-0 bg-background">
                  <TableRow>
                    {previewData.columns?.map(c => <TableHead key={c} className="text-xs font-mono">{c}</TableHead>)}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {previewData.rows.map((row, i) => (
                    <TableRow key={i}>
                      {row.map((cell, j) => (
                        <TableCell key={j} className="text-xs font-mono">
                          {cell === null ? <span className="text-muted-foreground italic">null</span> : String(cell)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="text-sm text-center py-8 text-muted-foreground">No data yet — stream may not have received events.</p>
          )}
        </DialogContent>
      </Dialog>

    </div>
  )
}
