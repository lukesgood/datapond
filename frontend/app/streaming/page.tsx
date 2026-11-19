"use client"
import { supportBadge, supportTier } from "@/lib/capability-support"
import { CapabilityGate, useCapabilities } from "@/lib/capabilities"

import { Fragment, Suspense, useCallback, useEffect, useState, useRef } from "react"
import { useToast } from "@/lib/toast"
import { ErrorBox } from "@/components/ui/error-box"
import { useConfirm } from "@/lib/confirm"
import { useRouter, useSearchParams } from "next/navigation"
import { NewStream } from "@/components/streaming/new-stream"
import { PageHeader } from "@/components/ui/page-header"
import { useHasPermission } from "@/lib/permissions"
import type { StreamKind } from "@/lib/streaming"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
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
  Radio, Database,
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
  columns?: string[]; rows?: unknown[][]; row_count?: number
  execution_time_ms?: number; message?: string
}

// ── Streaming sources (marketplace) ───────────────────────────────────────────


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
  -- On MinIO also set s3.endpoint, s3.access.key and s3.secret.key.
  -- On AWS leave them out: RisingWave uses its own credential chain.
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

async function responseError(response: Response, fallback: string) {
  try {
    const data = await response.json()
    return typeof data?.detail === "string" ? data.detail : fallback
  } catch {
    return fallback
  }
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

function StreamingPageInner() {
  const router = useRouter()
  const caps = useCapabilities()
  const streamingTier = supportTier("streaming", caps.support ?? {})
  const streamingBadge = streamingTier ? supportBadge(streamingTier) : null
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

  const [activeTab, setActiveTab] = useState("streams")
  const canWrite = useHasPermission("pipeline:write")
  const params = useSearchParams()
  const newParam = params.get("new")
  const newKind: StreamKind | null = canWrite && newParam
    ? (["cdc", "kafka", "kinesis"].includes(newParam) ? newParam as StreamKind : "cdc") : null
  const openNew = (kind: StreamKind | null) => router.replace(kind ? `/streaming?new=${kind}` : "/streaming")

  // Sample streams creation state
  const [makingSamples, setMakingSamples] = useState(false)

  const fetchAll = useCallback(async () => {
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
      const failed = [["cluster status", clusterRes], ["sources", sourcesRes], ["sinks", sinksRes], ["views", viewsRes]]
        .filter(([, r]) => !(r as Response).ok)
      if (failed.length) {
        const parts = await Promise.all(failed.map(async ([w, r]) =>
          `${w} (${await responseError(r as Response, `HTTP ${(r as Response).status}`)})`))
        setError(`Could not load ${parts.join(", ")}. What shows may be incomplete.`)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => { void fetchAll() }, 0)
    return () => window.clearTimeout(timer)
  }, [fetchAll])

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

  const { toast } = useToast()
  const confirm = useConfirm()

  const handleMakeSamples = async () => {
    setMakingSamples(true)
    try {
      const res = await fetch("/api/streaming/sample-streams", { method: "POST" })
      if (!res.ok) {
        toast(await responseError(res, "Failed to create sample streams"), "error")
        return
      }
      const data = await res.json()
      toast(`Created ${data.created}/${data.total} sample streams`, "success")
      fetchAll()
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed to create sample streams", "error")
    } finally {
      setMakingSamples(false)
    }
  }

  const handlePreview = async (mv: MV) => {
    setPreviewMv(mv)
    setPreviewLoading(true)
    const res = await fetch(`/api/streaming/views/${encodeURIComponent(mv.name)}/data?limit=50`)
    if (res.ok) setPreviewData(await res.json())
    else toast(await responseError(res, "Could not read the view"), "error")
    setPreviewLoading(false)
  }

  const handleDropPipeline = async (pipeline: PipelineGroup) => {
    const operations = [
      ...pipeline.sinks.map(name => ({ type: "sinks", name })),
      ...pipeline.views.map(name => ({ type: "views", name })),
      ...pipeline.sources.map(name => ({ type: "sources", name })),
    ]
    if (!(await confirm({ title: "Delete Pipeline", message: `Delete "${pipeline.name}" and its ${operations.length} associated objects.`, destructive: true, confirmText: "Delete" }))) return

    const deleted: string[] = []
    try {
      for (const operation of operations) {
        const response = await fetch(
          `/api/streaming/${operation.type}/${operation.name}`,
          { method: "DELETE" },
        )
        if (!response.ok) {
          const detail = await responseError(response, `${operation.name} deletion failed`)
          throw new Error(`${operation.name}: ${detail}`)
        }
        deleted.push(operation.name)
      }
      toast(`Pipeline "${pipeline.name}" deleted`, "success")
    } catch (e) {
      const detail = e instanceof Error ? e.message : "Deletion failed"
      const outcome = deleted.length > 0
        ? `Partial deletion: removed ${deleted.length}/${operations.length} objects before ${detail}`
        : `Pipeline deletion failed: ${detail}`
      toast(outcome, "error")
    } finally {
      void fetchAll()
    }
  }

  const pipelines = groupPipelines(sources, views, sinks)

  // Summary of active streams — derived from actually-present catalog objects.
  // "Live" = full source→view→sink set exists; "Partial" flags a broken/incomplete pipeline.
  const isPipelineLive = (p: PipelineGroup) =>
    p.sources.length > 0 && p.views.length > 0 && p.sinks.length > 0
  const cdcCount = pipelines.filter(p => p.pipeline_type === "cdc").length
  const eventCount = pipelines.filter(p => p.pipeline_type === "event").length
  const tableCount = pipelines.reduce((n, p) => n + p.tables.length, 0)
  const liveCount = pipelines.filter(isPipelineLive).length

  const statusColor = cluster?.status === "healthy" ? "text-[var(--dp-good-text)]"
    : cluster?.status === "degraded" ? "text-[var(--dp-warn-text)]" : "text-destructive"
  const StatusIcon = cluster?.status === "healthy" ? CheckCircle2
    : cluster?.status === "degraded" ? AlertCircle : XCircle

  // Find source/mv/sink objects for a given pipeline object name
  const findSourceObj = (name: string) => sources.find(s => s.name === name)
  const findViewObj   = (name: string) => views.find(v => v.name === name)
  const findSinkObj   = (name: string) => sinks.find(s => s.name === name)

  return (
    <div className="flex-1 space-y-5 px-6 py-5">

      <PageHeader
        title="Streaming"
        description="Database changes and event streams written to Iceberg continuously, through RisingWave."
        actions={<>
          <Button variant="outline" size="sm" onClick={fetchAll} disabled={loading}>
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />Refresh
          </Button>
          {canWrite && <Button variant="outline" size="sm" onClick={() => setActiveTab("console")}>SQL console</Button>}
          {canWrite && <Button size="sm" onClick={() => openNew("cdc")}><Plus className="mr-1.5 h-3.5 w-3.5" />New stream</Button>}
        </>}>
        {streamingBadge && (
          <p className="mt-1 text-xs text-muted-foreground" title={streamingBadge.title}>
            {streamingBadge.label} — {streamingBadge.title}
          </p>
        )}
      </PageHeader>

      {error && <ErrorBox msg={error} />}

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

      {newKind && (
        <NewStream key={newKind} kind={newKind} existingSources={sources.map(x => x.name)}
                   onCreated={() => { void fetchAll(); openNew(null) }} onCancel={() => openNew(null)} />
      )}

      {/* Main tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="h-8">
          <TabsTrigger value="streams" className="text-xs h-7 gap-1.5">
            <Zap className="h-3.5 w-3.5" />
            Active Streams
            {pipelines.length > 0 && (
              <Badge variant="secondary" className="text-2xs h-4 px-1 ml-0.5">{pipelines.length}</Badge>
            )}
          </TabsTrigger>
          {canWrite && <TabsTrigger value="console" className="text-xs h-7">SQL console</TabsTrigger>}
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
                {canWrite && <Button onClick={() => openNew("cdc")} className="gap-1.5">
                  <Plus className="h-4 w-4" />New stream
                </Button>}
                {canWrite && <Button variant="outline" className="gap-1.5"
                  onClick={handleMakeSamples} disabled={makingSamples}>
                  {makingSamples
                    ? <><Loader2 className="h-4 w-4 animate-spin" />Creating…</>
                    : <><Play className="h-4 w-4" />Make sample streams</>}
                </Button>}
              </div>
              <div className="flex items-center gap-6 text-xs text-muted-foreground">
                <span className="flex items-center gap-1"><ArrowRight className="h-3 w-3" />Source → RisingWave</span>
                <span className="flex items-center gap-1"><ArrowRight className="h-3 w-3" />Materialized View</span>
                <span className="flex items-center gap-1"><ArrowRight className="h-3 w-3" />Iceberg Sink</span>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Summary of active streams — honest counts from present objects */}
              <div className="flex flex-wrap items-center gap-2">
                {[
                  { label: "Pipelines", value: pipelines.length },
                  { label: "CDC", value: cdcCount },
                  { label: "Event", value: eventCount },
                  { label: "Tables", value: tableCount },
                  { label: "Live", value: liveCount, good: true },
                ].map(s => (
                  <div key={s.label} className="rounded-md border px-2.5 py-1 flex items-center gap-1.5">
                    <span className={`dp-num text-sm font-bold tabular-nums ${s.good && s.value > 0 ? "text-[var(--dp-good-text)]" : ""}`}>{s.value}</span>
                    <span className="text-xs text-muted-foreground">{s.label}</span>
                  </div>
                ))}
              </div>

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
                    <Fragment key={p.name}>
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
                        <TableCell className="font-medium text-sm">
                          <div className="flex items-center gap-2">
                            {p.name}
                            {isPipelineLive(p) ? (
                              <span className="inline-flex items-center gap-1 rounded-full border border-[var(--dp-good)]/30 bg-[var(--dp-good)]/10 px-1.5 py-0.5 text-2xs font-medium text-[var(--dp-good-text)]"
                                title="Full source → view → sink set is materializing">
                                <span className="h-1.5 w-1.5 rounded-full bg-[var(--dp-good)]" />Live
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 rounded-full border border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/10 px-1.5 py-0.5 text-2xs font-medium text-[var(--dp-warn-text)]"
                                title="Incomplete — missing a source, view, or sink object">
                                <span className="h-1.5 w-1.5 rounded-full bg-[var(--dp-warn)]" />Partial
                              </span>
                            )}
                          </div>
                        </TableCell>
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
                              <span key={t} className="text-2xs font-mono bg-muted px-1.5 py-0.5 rounded">{t}</span>
                            ))}
                          </div>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {p.sources.length} src · {p.views.length} mv · {p.sinks.length} sink
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">{fmtDate(p.created_at)}</TableCell>
                        <TableCell onClick={e => e.stopPropagation()}>
                          {canWrite && <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive"
                            aria-label={`Delete ${p.name}`} onClick={() => handleDropPipeline(p)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>}
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
                                              aria-label="View DDL" title="View DDL"
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
                                              {canWrite && <button
                                                className="text-muted-foreground hover:text-foreground transition-colors"
                                                onClick={() => handlePreview(obj)}
                                                aria-label={`Preview ${vName}`} title="Preview data"
                                              >
                                                <Eye className="h-3 w-3" />
                                              </button>}
                                              <button
                                                className="text-muted-foreground hover:text-foreground transition-colors"
                                                onClick={() => setShowDdl(obj.definition)}
                                                aria-label="View DDL" title="View DDL"
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
                                              aria-label="View DDL" title="View DDL"
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
                    </Fragment>
                  ))}
                </TableBody>
              </Table>
              </div>
            </div>
          )}
        </TabsContent>

        {/* ── Add Source ── */}

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
                  : <span className="text-[var(--dp-good-text)]">{sqlResult.message} · {sqlResult.execution_time_ms}ms</span>}
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
            <Button variant="outline" onClick={() => { setSql(showDdl ?? ""); setShowDdl(null); setActiveTab("console") }}>
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

export default function StreamingPage() {
  return (
    <CapabilityGate capability="streaming">
      <Suspense><StreamingPageInner /></Suspense>
    </CapabilityGate>
  )
}
