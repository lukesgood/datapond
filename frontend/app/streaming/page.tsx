"use client"

import { useEffect, useState, useRef } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import {
  Radio, RefreshCw, AlertCircle, CheckCircle2, XCircle,
  Plus, Trash2, Play, Eye, Server, ArrowRight, Database,
  ChevronRight, Code2, Loader2, Zap,
} from "lucide-react"

// ── Types ──────────────────────────────────────────────────────────────────────

interface Worker {
  id: number; host: string; port: string; type: string; state: string
  parallelism: number; rw_version: string
  total_memory_bytes: number; total_cpu_cores: number; started_at: string
}

interface ClusterInfo {
  status: "healthy" | "degraded" | "down"
  version: string; worker_count: number
  source_count: number; sink_count: number; mv_count: number
  workers: Worker[]
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

function fmtBytes(b: number) {
  if (b > 1e9) return `${(b / 1e9).toFixed(1)} GB`
  if (b > 1e6) return `${(b / 1e6).toFixed(0)} MB`
  return `${(b / 1e3).toFixed(0)} KB`
}

function fmtDate(s: string | null) {
  if (!s) return "—"
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
  }).format(new Date(s))
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function StreamingPage() {
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

  // Create dialogs
  const [createSource, setCreateSource] = useState(false)
  const [createSink, setCreateSink] = useState(false)
  const [createMv, setCreateMv] = useState(false)

  // Create form state
  const [sourceForm, setSourceForm] = useState({
    name: "", connector: "kafka", topic: "", bootstrap_servers: "",
    format: "plain", row_encode: "json", columns_sql: "user_id BIGINT, event VARCHAR, ts TIMESTAMPTZ",
  })
  const [sinkForm, setSinkForm] = useState({
    name: "", from_mv: "", connector: "iceberg",
    sink_type: "append-only", iceberg_schema: "default", iceberg_table: "",
  })
  const [mvForm, setMvForm] = useState({ name: "", definition: "SELECT * FROM my_source" })
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

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

  const handleDrop = async (type: string, name: string) => {
    if (!confirm(`Drop ${type} "${name}"?`)) return
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

  const handleCreateSource = async () => {
    setCreating(true); setCreateError(null)
    const res = await fetch("/api/streaming/sources", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sourceForm),
    })
    if (res.ok) { setCreateSource(false); fetchAll() }
    else { const d = await res.json(); setCreateError(d.detail) }
    setCreating(false)
  }

  const handleCreateSink = async () => {
    setCreating(true); setCreateError(null)
    const res = await fetch("/api/streaming/sinks", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sinkForm),
    })
    if (res.ok) { setCreateSink(false); fetchAll() }
    else { const d = await res.json(); setCreateError(d.detail) }
    setCreating(false)
  }

  const handleCreateMv = async () => {
    setCreating(true); setCreateError(null)
    const res = await fetch("/api/streaming/views", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(mvForm),
    })
    if (res.ok) { setCreateMv(false); fetchAll() }
    else { const d = await res.json(); setCreateError(d.detail) }
    setCreating(false)
  }

  const statusColor = cluster?.status === "healthy" ? "text-green-600"
    : cluster?.status === "degraded" ? "text-amber-500" : "text-red-500"
  const StatusIcon = cluster?.status === "healthy" ? CheckCircle2
    : cluster?.status === "degraded" ? AlertCircle : XCircle

  return (
    <div className="flex-1 space-y-5 px-6 py-5">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Streaming</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            RisingWave 실시간 파이프라인 관리
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

      {/* Cluster stats */}
      <div className="grid gap-4 md:grid-cols-5">
        <Card className="md:col-span-1">
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <Zap className="h-4 w-4" />Cluster
            </CardDescription>
            <CardTitle className={`text-lg flex items-center gap-1.5 ${statusColor}`}>
              {cluster && <StatusIcon className="h-5 w-5" />}
              <span className="capitalize">{loading ? "…" : (cluster?.status ?? "—")}</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            {cluster?.version ?? ""}
          </CardContent>
        </Card>
        {[
          { label: "Sources",  value: cluster?.source_count, icon: Radio,     action: () => setCreateSource(true) },
          { label: "Views",    value: cluster?.mv_count,     icon: Database,   action: () => setCreateMv(true) },
          { label: "Sinks",    value: cluster?.sink_count,   icon: ArrowRight, action: () => setCreateSink(true) },
          { label: "Workers",  value: cluster?.worker_count, icon: Server,     action: null },
        ].map(({ label, value, icon: Icon, action }) => (
          <Card key={label} className="cursor-default">
            <CardHeader className="pb-2">
              <CardDescription className="flex items-center justify-between">
                <span className="flex items-center gap-1.5"><Icon className="h-4 w-4" />{label}</span>
                {action && (
                  <button onClick={action}
                    className="h-5 w-5 rounded flex items-center justify-center hover:bg-muted transition-colors">
                    <Plus className="h-3 w-3" />
                  </button>
                )}
              </CardDescription>
              <CardTitle className="text-2xl">{loading ? "…" : (value ?? "—")}</CardTitle>
            </CardHeader>
          </Card>
        ))}
      </div>

      {/* Main tabs */}
      <Tabs defaultValue="sources">
        <TabsList className="h-8">
          <TabsTrigger value="sources" className="text-xs h-7">Sources ({sources.length})</TabsTrigger>
          <TabsTrigger value="views"   className="text-xs h-7">Materialized Views ({views.length})</TabsTrigger>
          <TabsTrigger value="sinks"   className="text-xs h-7">Sinks ({sinks.length})</TabsTrigger>
          <TabsTrigger value="console" className="text-xs h-7">SQL Console</TabsTrigger>
          <TabsTrigger value="cluster" className="text-xs h-7">Cluster</TabsTrigger>
        </TabsList>

        {/* ── Sources ── */}
        <TabsContent value="sources" className="mt-4">
          <div className="flex justify-end mb-3">
            <Button size="sm" className="h-8 text-xs gap-1.5" onClick={() => setCreateSource(true)}>
              <Plus className="h-3.5 w-3.5" />New Source
            </Button>
          </div>
          <div className="rounded-lg border overflow-hidden">
            <Table>
              <TableHeader className="bg-muted/40">
                <TableRow>
                  <TableHead className="text-xs">Name</TableHead>
                  <TableHead className="text-xs">Connector</TableHead>
                  <TableHead className="text-xs">Format</TableHead>
                  <TableHead className="text-xs">Encode</TableHead>
                  <TableHead className="text-xs">Created</TableHead>
                  <TableHead className="text-xs w-20" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sources.length === 0 ? (
                  <TableRow><TableCell colSpan={6} className="py-12 text-center text-sm text-muted-foreground">
                    No sources. Click <strong>New Source</strong> to create one.
                  </TableCell></TableRow>
                ) : sources.map(s => (
                  <TableRow key={s.id}>
                    <TableCell className="font-medium text-sm">{s.name}</TableCell>
                    <TableCell><Badge variant="outline" className="text-xs">{s.connector}</Badge></TableCell>
                    <TableCell className="text-xs text-muted-foreground uppercase">{s.format}</TableCell>
                    <TableCell className="text-xs text-muted-foreground uppercase">{s.row_encode}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{fmtDate(s.created_at)}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon" className="h-7 w-7"
                          onClick={() => setShowDdl(s.definition)}>
                          <Code2 className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive"
                          onClick={() => handleDrop("sources", s.name)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* ── Materialized Views ── */}
        <TabsContent value="views" className="mt-4">
          <div className="flex justify-end mb-3">
            <Button size="sm" className="h-8 text-xs gap-1.5" onClick={() => setCreateMv(true)}>
              <Plus className="h-3.5 w-3.5" />New View
            </Button>
          </div>
          <div className="rounded-lg border overflow-hidden">
            <Table>
              <TableHeader className="bg-muted/40">
                <TableRow>
                  <TableHead className="text-xs">Name</TableHead>
                  <TableHead className="text-xs">Created</TableHead>
                  <TableHead className="text-xs w-28" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {views.length === 0 ? (
                  <TableRow><TableCell colSpan={3} className="py-12 text-center text-sm text-muted-foreground">
                    No materialized views. Click <strong>New View</strong> to create one.
                  </TableCell></TableRow>
                ) : views.map(v => (
                  <TableRow key={v.id}>
                    <TableCell className="font-medium text-sm">{v.name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{fmtDate(v.created_at)}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon" className="h-7 w-7"
                          onClick={() => handlePreview(v)}>
                          <Eye className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7"
                          onClick={() => setShowDdl(v.definition)}>
                          <Code2 className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive"
                          onClick={() => handleDrop("views", v.name)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* ── Sinks ── */}
        <TabsContent value="sinks" className="mt-4">
          <div className="flex justify-end mb-3">
            <Button size="sm" className="h-8 text-xs gap-1.5" onClick={() => setCreateSink(true)}>
              <Plus className="h-3.5 w-3.5" />New Sink
            </Button>
          </div>
          <div className="rounded-lg border overflow-hidden">
            <Table>
              <TableHeader className="bg-muted/40">
                <TableRow>
                  <TableHead className="text-xs">Name</TableHead>
                  <TableHead className="text-xs">Connector</TableHead>
                  <TableHead className="text-xs">Type</TableHead>
                  <TableHead className="text-xs">Created</TableHead>
                  <TableHead className="text-xs w-20" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sinks.length === 0 ? (
                  <TableRow><TableCell colSpan={5} className="py-12 text-center text-sm text-muted-foreground">
                    No sinks. Click <strong>New Sink</strong> to route data to Iceberg or other targets.
                  </TableCell></TableRow>
                ) : sinks.map(s => (
                  <TableRow key={s.id}>
                    <TableCell className="font-medium text-sm">{s.name}</TableCell>
                    <TableCell><Badge variant="outline" className="text-xs">{s.connector}</Badge></TableCell>
                    <TableCell className="text-xs text-muted-foreground">{s.sink_type}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{fmtDate(s.created_at)}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon" className="h-7 w-7"
                          onClick={() => setShowDdl(s.definition)}>
                          <Code2 className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive"
                          onClick={() => handleDrop("sinks", s.name)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
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

        {/* ── Cluster ── */}
        <TabsContent value="cluster" className="mt-4">
          <div className="rounded-lg border overflow-hidden">
            <Table>
              <TableHeader className="bg-muted/40">
                <TableRow>
                  <TableHead className="text-xs">ID</TableHead>
                  <TableHead className="text-xs">Host</TableHead>
                  <TableHead className="text-xs">Type</TableHead>
                  <TableHead className="text-xs">State</TableHead>
                  <TableHead className="text-xs">Memory</TableHead>
                  <TableHead className="text-xs">CPUs</TableHead>
                  <TableHead className="text-xs">Version</TableHead>
                  <TableHead className="text-xs">Started</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(cluster?.workers ?? []).map(w => (
                  <TableRow key={w.id}>
                    <TableCell className="text-xs font-mono">{w.id}</TableCell>
                    <TableCell className="text-xs font-mono">{w.host}:{w.port}</TableCell>
                    <TableCell className="text-xs">
                      <Badge variant="outline" className="text-[10px]">
                        {w.type.replace("WORKER_TYPE_", "")}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <span className={`text-xs font-medium ${w.state === "RUNNING" ? "text-green-600" : "text-amber-500"}`}>
                        {w.state}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{fmtBytes(w.total_memory_bytes)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{w.total_cpu_cores || "—"}</TableCell>
                    <TableCell className="text-xs font-mono text-muted-foreground">{w.rw_version}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{fmtDate(w.started_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
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

      {/* ── Create Source ── */}
      <Dialog open={createSource} onOpenChange={setCreateSource}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Source</DialogTitle>
            <DialogDescription>Connect a streaming data source to RisingWave</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {[
              { label: "Name", field: "name", placeholder: "my_kafka_source" },
              { label: "Topic", field: "topic", placeholder: "my-topic" },
              { label: "Bootstrap Servers", field: "bootstrap_servers", placeholder: "kafka:9092" },
              { label: "Column Definitions", field: "columns_sql", placeholder: "user_id BIGINT, event VARCHAR, ts TIMESTAMPTZ" },
            ].map(({ label, field, placeholder }) => (
              <div key={field} className="space-y-1">
                <Label className="text-xs">{label}</Label>
                <Input value={(sourceForm as any)[field]} placeholder={placeholder}
                  onChange={e => setSourceForm(p => ({ ...p, [field]: e.target.value }))} />
              </div>
            ))}
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: "Connector", field: "connector", options: ["kafka", "kinesis", "pulsar", "nexmark"] },
                { label: "Format", field: "format", options: ["plain", "upsert", "debezium", "maxwell"] },
                { label: "Encode", field: "row_encode", options: ["json", "avro", "protobuf", "csv"] },
              ].map(({ label, field, options }) => (
                <div key={field} className="space-y-1">
                  <Label className="text-xs">{label}</Label>
                  <Select value={(sourceForm as any)[field]}
                    onValueChange={v => setSourceForm(p => ({ ...p, [field]: v }))}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>{options.map(o => <SelectItem key={o} value={o} className="text-xs">{o}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              ))}
            </div>
            {createError && <p className="text-xs text-destructive font-mono">{createError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateSource(false)}>Cancel</Button>
            <Button onClick={handleCreateSource} disabled={creating}>
              {creating ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Creating…</> : "Create Source"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Create MV ── */}
      <Dialog open={createMv} onOpenChange={setCreateMv}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Materialized View</DialogTitle>
            <DialogDescription>Define a streaming SQL transformation</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Name</Label>
              <Input value={mvForm.name} placeholder="event_counts"
                onChange={e => setMvForm(p => ({ ...p, name: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">SQL Definition (after AS)</Label>
              <textarea value={mvForm.definition}
                onChange={e => setMvForm(p => ({ ...p, definition: e.target.value }))}
                className="w-full h-36 p-2 font-mono text-xs rounded-md border bg-background resize-none focus:outline-none focus:ring-1 focus:ring-ring"
                placeholder="SELECT date_trunc('minute', ts), event, COUNT(*) FROM my_source GROUP BY 1, 2" />
            </div>
            {createError && <p className="text-xs text-destructive font-mono">{createError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateMv(false)}>Cancel</Button>
            <Button onClick={handleCreateMv} disabled={creating}>
              {creating ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Creating…</> : "Create View"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Create Sink (Iceberg pre-filled) ── */}
      <Dialog open={createSink} onOpenChange={setCreateSink}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Sink</DialogTitle>
            <DialogDescription>Route streaming data to Iceberg or other targets</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {[
              { label: "Sink Name", field: "name", placeholder: "my_iceberg_sink" },
              { label: "From (MV or Table)", field: "from_mv", placeholder: "event_counts" },
              { label: "Iceberg Schema", field: "iceberg_schema", placeholder: "default" },
              { label: "Iceberg Table Name", field: "iceberg_table", placeholder: "leave blank to use sink name" },
            ].map(({ label, field, placeholder }) => (
              <div key={field} className="space-y-1">
                <Label className="text-xs">{label}</Label>
                <Input value={(sinkForm as any)[field]} placeholder={placeholder}
                  onChange={e => setSinkForm(p => ({ ...p, [field]: e.target.value }))} />
              </div>
            ))}
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-xs">Connector</Label>
                <Select value={sinkForm.connector} onValueChange={v => setSinkForm(p => ({ ...p, connector: v ?? "iceberg" }))}>
                  <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {["iceberg", "kafka", "jdbc", "elasticsearch"].map(o =>
                      <SelectItem key={o} value={o} className="text-xs">{o}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Sink Type</Label>
                <Select value={sinkForm.sink_type} onValueChange={v => setSinkForm(p => ({ ...p, sink_type: v ?? "append-only" }))}>
                  <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {["append-only", "upsert"].map(o =>
                      <SelectItem key={o} value={o} className="text-xs">{o}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            {sinkForm.connector === "iceberg" && (
              <p className="text-xs text-muted-foreground bg-muted/40 rounded-md px-3 py-2">
                SeaweedFS S3 credentials auto-filled from environment.
                Data will be written to <code className="font-mono">iceberg.{sinkForm.iceberg_schema}.{sinkForm.iceberg_table || sinkForm.name || "…"}</code>
              </p>
            )}
            {createError && <p className="text-xs text-destructive font-mono">{createError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateSink(false)}>Cancel</Button>
            <Button onClick={handleCreateSink} disabled={creating}>
              {creating ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Creating…</> : "Create Sink"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
