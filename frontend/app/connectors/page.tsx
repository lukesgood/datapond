"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ConnectorCard } from "@/components/connectors/connector-card"
import { availableConnectors } from "@/lib/connectors"
import {
  Plus, RefreshCw, Database, Search, MoreHorizontal,
  Trash2, HardDrive, Radio, Cloud, AlertCircle, Plug,
  Rows3, ShieldAlert, TrendingUp, TableProperties,
  ArrowRight, ArrowDownToLine, Layers, BarChart2, Zap, Loader2,
} from "lucide-react"
import Link from "next/link"

interface Connection {
  id: string
  name: string
  connector_type: string
  status: "active" | "paused" | "error" | "pending"
  created_at: string
  last_sync_at: string | null
}

interface ConnStats {
  tables: number
  lastRows: number | null
  successRate: number | null
}

// ── Ingestion flow empty state ────────────────────────────────────────────────

const FLOW_STEPS = [
  {
    icon: Database,
    label: "Source",
    desc: "PostgreSQL, MySQL, REST API, S3, Custom Python",
    color: "bg-blue-500/10 text-primary border-primary/20",
    dot: "bg-primary",
  },
  {
    icon: ArrowDownToLine,
    label: "Ingest",
    desc: "Batch sync with full or incremental mode",
    color: "bg-purple-500/10 text-purple-600 border-purple-200",
    dot: "bg-purple-500",
  },
  {
    icon: Layers,
    label: "Iceberg",
    desc: "ACID tables in SeaweedFS S3 via Apache Polaris",
    color: "bg-amber-500/10 text-amber-600 border-amber-200",
    dot: "bg-amber-500",
  },
  {
    icon: BarChart2,
    label: "Query",
    desc: "Trino SQL Lab, DuckDB in Notebooks, BI tools",
    color: "bg-green-500/10 text-green-600 border-green-200",
    dot: "bg-green-500",
  },
]

const SOURCE_TYPES = [
  { name: "PostgreSQL",  icon: "🐘" },
  { name: "MySQL",       icon: "🐬" },
  { name: "REST API",    icon: "🌐" },
  { name: "S3 Storage",  icon: "🪣" },
  { name: "Universal DB",icon: "🔗" },
  { name: "Custom Python", icon: "🐍" },
]

function IngestionEmptyState({ onAddSource, hideTitle, onSampleCreated }: {
  onAddSource: () => void
  hideTitle?: boolean
  onSampleCreated?: (id: string) => void
}) {
  const [creating, setCreating] = useState(false)
  const [sampleMsg, setSampleMsg] = useState<string | null>(null)
  const router = useRouter()

  const handleTrySample = async () => {
    setCreating(true)
    setSampleMsg(null)
    try {
      const res = await fetch("/api/connectors/sample-db", { method: "POST" })
      const d = await res.json()
      if (!res.ok) throw new Error(d.detail ?? "Failed")
      setSampleMsg(d.already_existed ? "Sample DB already exists — opening…" : "Sample DB created! Opening…")
      setTimeout(() => {
        if (onSampleCreated) onSampleCreated(d.id)
        router.push(`/connectors/connections/${d.id}`)
      }, 800)
    } catch (e) {
      setSampleMsg(e instanceof Error ? e.message : "Failed to create sample DB")
      setCreating(false)
    }
  }

  return (
    <div className="px-8 py-10 space-y-8">
      {/* Title — hidden when used as collapsible panel */}
      {!hideTitle && (
        <div className="text-center space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary/10 text-primary text-xs font-medium mb-2">
            <Zap className="h-3.5 w-3.5" />
            Get started with Ingestion
          </div>
          <h3 className="text-xl font-bold">Connect your data sources to the Lakehouse</h3>
          <p className="text-sm text-muted-foreground max-w-lg mx-auto">
            DataPond pulls data from any source into Iceberg tables — queryable instantly via Trino, DuckDB, or any SQL tool.
          </p>
        </div>
      )}

      {/* Flow diagram */}
      <div className="flex items-stretch justify-center gap-2">
        {FLOW_STEPS.map((step, i) => (
          <div key={step.label} className="flex items-center gap-2">
            {/* Step card */}
            <div className={`flex flex-col items-center gap-3 px-5 py-5 rounded-xl border-2 w-44 ${step.color}`}>
              <div className={`h-10 w-10 rounded-full flex items-center justify-center border-2 ${step.color}`}>
                <step.icon className="h-5 w-5" />
              </div>
              <div className="text-center space-y-1">
                <div className="text-sm font-bold">{step.label}</div>
                <div className="text-[11px] leading-relaxed opacity-75">{step.desc}</div>
              </div>
            </div>
            {/* Arrow */}
            {i < FLOW_STEPS.length - 1 && (
              <ArrowRight className="h-5 w-5 text-muted-foreground/30 shrink-0" />
            )}
          </div>
        ))}
      </div>

      {/* Supported sources */}
      <div className="space-y-3">
        <p className="text-center text-xs text-muted-foreground font-medium uppercase tracking-wide">
          Supported sources
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          {SOURCE_TYPES.map(s => (
            <span key={s.name}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border bg-muted/30 text-xs font-medium text-muted-foreground hover:bg-muted/60 transition-colors">
              <span>{s.icon}</span>
              {s.name}
            </span>
          ))}
        </div>
      </div>

      {/* CTA */}
      <div className="flex flex-col items-center gap-3">
        {/* Primary: Try Sample DB */}
        <button
          onClick={handleTrySample}
          disabled={creating}
          className="flex items-center gap-2 px-6 py-3 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors shadow-sm disabled:opacity-60 min-w-56 justify-center"
        >
          {creating
            ? <><Loader2 className="h-4 w-4 animate-spin" />Setting up…</>
            : <><Database className="h-4 w-4" />Try with Sample DB</>}
        </button>

        {/* Sample DB description */}
        {!creating && !sampleMsg && (
          <p className="text-xs text-muted-foreground text-center max-w-xs">
            Auto-creates an e-commerce PostgreSQL DB with customers, orders, products &amp; events — ready to sync in seconds.
          </p>
        )}

        {/* Status message */}
        {sampleMsg && (
          <p className={`text-xs text-center ${sampleMsg.includes("Failed") ? "text-destructive" : "text-green-600"}`}>
            {sampleMsg}
          </p>
        )}

        {/* Divider */}
        <div className="flex items-center gap-3 w-full max-w-xs">
          <div className="flex-1 h-px bg-border" />
          <span className="text-xs text-muted-foreground">or</span>
          <div className="flex-1 h-px bg-border" />
        </div>

        {/* Secondary: connect own source */}
        <button
          onClick={onAddSource}
          className="flex items-center gap-2 px-6 py-2.5 rounded-lg border text-sm font-medium hover:bg-muted/50 transition-colors min-w-56 justify-center"
        >
          <Plus className="h-4 w-4" />
          Connect Your Own Source
        </button>
      </div>
    </div>
  )
}

export default function ConnectorsPage() {
  // ── Connections state ──────────────────────────────────────────────────────
  const [connections, setConnections] = useState<Connection[]>([])
  const [connStats, setConnStats] = useState<Map<string, ConnStats>>(new Map())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [activeTab, setActiveTab] = useState("connections")

  const fetchConnections = async () => {
    try {
      setError(null)
      const res = await fetch("/api/connectors/connections")
      if (!res.ok) throw new Error(`Failed to load (${res.status})`)
      const data: Connection[] = await res.json()
      const list = Array.isArray(data) ? data : []
      setConnections(list)

      // Fetch per-connection stats in parallel
      const statsEntries = await Promise.all(list.map(async (conn) => {
        try {
          const [tablesRes, statusRes] = await Promise.all([
            fetch(`/api/connectors/${conn.id}/tables`),
            fetch(`/api/connectors/${conn.id}/status`),
          ])
          const tables = tablesRes.ok ? (await tablesRes.json()).tables?.length ?? 0 : 0
          let lastRows: number | null = null
          let successRate: number | null = null
          if (statusRes.ok) {
            const s = await statusRes.json()
            const jobs = s.jobs ?? []
            if (jobs.length > 0) {
              // last sync total rows = sum of most recent run per table
              const byTable = new Map<string, any>()
              for (const j of jobs) {
                if (!byTable.has(j.source_table)) byTable.set(j.source_table, j)
              }
              lastRows = Array.from(byTable.values()).reduce((sum, j) => sum + (j.rows_synced ?? 0), 0)
              const recent = jobs.slice(0, 20)
              successRate = Math.round(recent.filter((j: any) => j.status === "success").length / recent.length * 100)
            }
          }
          return [conn.id, { tables, lastRows, successRate }] as [string, ConnStats]
        } catch {
          return [conn.id, { tables: 0, lastRows: null, successRate: null }] as [string, ConnStats]
        }
      }))
      setConnStats(new Map(statsEntries))
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load connections")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchConnections() }, [])

  const handleSync = async (id: string) => {
    setActionLoading(id)
    try {
      await fetch(`/api/connectors/${id}/sync`, { method: "POST" })
      await fetchConnections()
    } finally {
      setActionLoading(null)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this connection?")) return
    setActionLoading(id)
    try {
      await fetch(`/api/connectors/${id}`, { method: "DELETE" })
      setConnections(prev => prev.filter(c => c.id !== id))
    } finally {
      setActionLoading(null)
    }
  }

  // ── Marketplace state ──────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState("")
  const [marketCat, setMarketCat] = useState("all")

  const filteredConnectors = availableConnectors.filter(c =>
    c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    c.description.toLowerCase().includes(searchQuery.toLowerCase())
  ).filter(c => marketCat === "all" || c.category === marketCat)

  // ── Helpers ────────────────────────────────────────────────────────────────
  const formatDate = (s: string | null) => {
    if (!s) return "Never"
    const utc = s.endsWith("Z") || s.includes("+") ? s : s + "Z"
    return new Intl.DateTimeFormat("en-US", {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    }).format(new Date(utc))
  }

  const statusBadge = (status: string) => {
    if (status === "active")
      return <Badge className="bg-green-500/10 text-green-700 border-green-200 text-[10px] h-5">Active</Badge>
    if (status === "error")
      return <Badge variant="destructive" className="text-[10px] h-5">Error</Badge>
    return <Badge variant="secondary" className="text-[10px] h-5 capitalize">{status}</Badge>
  }

  const activeCount = connections.filter(c => c.status === "active").length
  const errorCount  = connections.filter(c => c.status === "error").length

  // ── Platform-level metrics ────────────────────────────────────────────────
  const totalTables  = Array.from(connStats.values()).reduce((s, c) => s + c.tables, 0)
  const totalLastRows = Array.from(connStats.values()).reduce((s, c) => s + (c.lastRows ?? 0), 0)
  const rates = Array.from(connStats.values()).map(c => c.successRate).filter((r): r is number => r !== null)
  const avgSuccessRate = rates.length > 0 ? Math.round(rates.reduce((a, b) => a + b, 0) / rates.length) : null
  const now = Date.now()
  const staleSources = connections.filter(c => {
    if (!c.last_sync_at) return true
    return now - new Date(c.last_sync_at).getTime() > 86_400_000 // > 24h
  }).length

  return (
    <div className="flex-1 space-y-5 px-6 py-5">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Ingestion</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            배치 수집 — 외부 소스에서 Iceberg로
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5"
            onClick={fetchConnections} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Platform metrics */}
      {!loading && connections.length > 0 && (
        <div className="grid grid-cols-4 gap-3">
          {[
            {
              label: "Managed Tables",
              value: totalTables || "—",
              sub: `across ${connections.length} source${connections.length !== 1 ? "s" : ""}`,
              icon: TableProperties,
              color: "",
            },
            {
              label: "Last Sync Rows",
              value: totalLastRows > 0 ? totalLastRows.toLocaleString() : "—",
              sub: "total rows — most recent sync",
              icon: Rows3,
              color: "",
            },
            {
              label: "Avg Success Rate",
              value: avgSuccessRate !== null ? `${avgSuccessRate}%` : "—",
              sub: "across all sources",
              icon: TrendingUp,
              color: avgSuccessRate !== null && avgSuccessRate < 80 ? "text-destructive" : avgSuccessRate !== null && avgSuccessRate >= 95 ? "text-green-600" : "",
            },
            {
              label: "Stale Sources",
              value: staleSources,
              sub: staleSources === 0 ? "all sources up to date" : "last sync > 24h ago",
              icon: ShieldAlert,
              color: staleSources > 0 ? "text-amber-500" : "text-green-600",
              highlight: staleSources > 0,
            },
          ].map(({ label, value, sub, icon: Icon, color, highlight }) => (
            <div key={label} className={`rounded-lg border px-4 py-3 ${highlight ? "border-amber-400/50 bg-amber-50/30" : "bg-card"}`}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-muted-foreground">{label}</span>
                <Icon className={`h-3.5 w-3.5 ${color || "text-muted-foreground"}`} />
              </div>
              <div className={`text-2xl font-bold ${color}`}>{value}</div>
              <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>
            </div>
          ))}
        </div>
      )}

      {/* Tabs: Connections (default) + Marketplace */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <div className="flex items-center justify-between">
          <TabsList className="h-8">
            <TabsTrigger value="connections" className="text-xs h-7 gap-1.5">
              <Plug className="h-3.5 w-3.5" />
              Active Sources
              {connections.length > 0 && (
                <Badge variant="secondary" className="text-[9px] h-4 px-1 ml-0.5">
                  {connections.length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="marketplace" className="text-xs h-7 gap-1.5">
              <Plus className="h-3.5 w-3.5" />
              Add Source
            </TabsTrigger>
          </TabsList>
        </div>

        {/* ── Active Connections tab ─────────────────────────────────────── */}
        <TabsContent value="connections" className="space-y-4">

          {/* Stats + How it works toggle */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4 text-sm">
              <span className="text-muted-foreground">
                <span className="font-semibold text-foreground">{connections.length}</span> total
              </span>
              <span className="text-green-600">
                <span className="font-semibold">{activeCount}</span> active
              </span>
              {errorCount > 0 && (
                <span className="text-destructive flex items-center gap-1">
                  <AlertCircle className="h-3.5 w-3.5" />
                  <span className="font-semibold">{errorCount}</span> error
                </span>
              )}
            </div>
            {connections.length > 0 && (
              <button
                onClick={() => setShowOnboarding(v => !v)}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <Zap className="h-3.5 w-3.5" />
                {showOnboarding ? "Hide" : "How it works"}
              </button>
            )}
          </div>

          {/* Onboarding panel — collapsible */}
          {showOnboarding && (
            <div className="rounded-xl border bg-card">
              <IngestionEmptyState onAddSource={() => {
                setShowOnboarding(false)
                setActiveTab("marketplace")
              }} hideTitle />
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="flex items-center gap-2 rounded-lg border border-destructive/30
                            bg-destructive/5 px-4 py-3 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}

          {/* Empty state — outside table to avoid border/cell conflicts */}
          {!loading && connections.length === 0 && (
            <div className="rounded-xl border bg-card">
              <IngestionEmptyState onAddSource={() => {
                setActiveTab("marketplace")
              }} />
            </div>
          )}

          {/* Table */}
          {(loading || connections.length > 0) && (
          <div className="rounded-lg border overflow-hidden">
            <Table>
              <TableHeader className="bg-muted/40">
                <TableRow>
                  <TableHead className="text-xs">Name</TableHead>
                  <TableHead className="text-xs">Type</TableHead>
                  <TableHead className="text-xs">Status</TableHead>
                  <TableHead className="text-xs">Last Sync</TableHead>
                  <TableHead className="text-xs text-right">Tables</TableHead>
                  <TableHead className="text-xs text-right">Last Rows</TableHead>
                  <TableHead className="text-xs text-right">Success Rate</TableHead>
                  <TableHead className="text-xs w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  Array(3).fill(0).map((_, i) => (
                    <TableRow key={i}>
                      {Array(8).fill(0).map((_, j) => (
                        <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  connections.map(conn => (
                    <TableRow
                      key={conn.id}
                      className={actionLoading === conn.id ? "opacity-50" : ""}
                    >
                      <TableCell className="font-medium text-sm">
                        <Link href={`/connectors/connections/${conn.id}`}
                          className="hover:underline underline-offset-2">
                          {conn.name}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <span className="flex items-center gap-1.5 text-sm">
                          <Database className="h-3.5 w-3.5 text-muted-foreground" />
                          <span className="capitalize">{conn.connector_type}</span>
                        </span>
                      </TableCell>
                      <TableCell>{statusBadge(conn.status)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDate(conn.last_sync_at)}
                      </TableCell>
                      <TableCell className="text-xs text-right text-muted-foreground">
                        {connStats.get(conn.id)?.tables ?? "—"}
                      </TableCell>
                      <TableCell className="text-xs text-right text-muted-foreground">
                        {connStats.get(conn.id)?.lastRows != null
                          ? connStats.get(conn.id)!.lastRows!.toLocaleString()
                          : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-right">
                        {(() => {
                          const rate = connStats.get(conn.id)?.successRate
                          if (rate == null) return <span className="text-muted-foreground">—</span>
                          return (
                            <span className={rate >= 80 ? "text-green-600 font-medium" : rate >= 50 ? "text-amber-500 font-medium" : "text-red-500 font-medium"}>
                              {rate}%
                            </span>
                          )
                        })()}
                      </TableCell>
                      <TableCell>
                        <DropdownMenu>
                          <DropdownMenuTrigger>
                            <Button variant="ghost" size="icon"
                              className="h-7 w-7" disabled={actionLoading === conn.id}>
                              <MoreHorizontal className="h-3.5 w-3.5" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => handleSync(conn.id)}>
                              <RefreshCw className="h-3.5 w-3.5 mr-2" />Sync Now
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              className="text-destructive"
                              onClick={() => handleDelete(conn.id)}>
                              <Trash2 className="h-3.5 w-3.5 mr-2" />Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
          )}
        </TabsContent>

        {/* ── Marketplace tab ────────────────────────────────────────────── */}
        <TabsContent value="marketplace" className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Search connectors..."
                className="pl-8 h-8 text-sm"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </div>
            <div className="flex gap-1">
              {[
                { id: "all", label: "All", icon: Cloud },
                { id: "database", label: "Databases", icon: Database },
                { id: "storage", label: "Storage", icon: HardDrive },
                { id: "streaming", label: "Streaming", icon: Radio },
              ].map(({ id, label, icon: Icon }) => (
                <Button
                  key={id}
                  variant={marketCat === id ? "secondary" : "ghost"}
                  size="sm"
                  className="h-8 text-xs gap-1.5"
                  onClick={() => setMarketCat(id)}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </Button>
              ))}
            </div>
          </div>

          {filteredConnectors.length === 0 ? (
            <div className="py-16 text-center text-sm text-muted-foreground">
              No connectors found
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {filteredConnectors.map(connector => (
                <ConnectorCard key={connector.id} connector={connector} />
              ))}
            </div>
          )}

          <div className="border-t pt-3 flex justify-between text-xs text-muted-foreground">
            <span>{availableConnectors.filter(c => c.supported).length} available</span>
            <span>{availableConnectors.filter(c => !c.supported).length} coming soon</span>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
