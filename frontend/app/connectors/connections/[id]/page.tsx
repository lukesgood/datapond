"use client"

import { use, useEffect, useState, useRef } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { SyncHistory, SyncSession } from "@/components/connectors/sync-history"
import {
  ChevronLeft, RefreshCw, Database, Rows3, Trash2,
  AlertTriangle, Pencil, X, Check, Wifi, BarChart2,
} from "lucide-react"
import Link from "next/link"
import { ConnectionForm } from "@/components/connectors/connection-form"
import { getConnector } from "@/lib/connectors"

interface Connector {
  id: string; name: string; connector_type: string
  status: string; created_at: string; last_sync_at: string | null
}

export default function ConnectionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()

  const [connector, setConnector]         = useState<Connector | null>(null)
  const [tables, setTables]               = useState<string[]>([])
  const [configPreview, setConfigPreview] = useState<Record<string, any>>({})
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState<string | null>(null)
  const [syncing, setSyncing]             = useState(false)
  const [deleting, setDeleting]           = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  // History sessions (past + live)
  const [sessions, setSessions]           = useState<SyncSession[]>([])
  const [liveSession, setLiveSession]     = useState<SyncSession | null>(null)
  const elapsedRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Edit
  const [editing, setEditing]             = useState(false)
  const [editConfig, setEditConfig]       = useState<Record<string, any>>({})
  const [editName, setEditName]           = useState("")
  const [editConnectorType, setEditConnectorType] = useState("")
  const [saving, setSaving]               = useState(false)
  const [saveMessage, setSaveMessage]     = useState<string | null>(null)
  const [testing, setTesting]             = useState(false)
  const [testResult, setTestResult]       = useState<{ success: boolean; message: string } | null>(null)

  // ── Fetch ──────────────────────────────────────────────────────────────────

  const fetchHistory = async () => {
    const res = await fetch(`/api/connectors/${id}/history`)
    if (!res.ok) return
    const data: any[] = await res.json()
    setSessions(data.map(s => ({
      id: s.id,
      status: s.status,
      started_at: s.started_at,
      completed_at: s.completed_at,
      rows_processed: s.rows_processed,
      rows_failed: s.rows_failed,
      duration_ms: s.duration_ms,
      sync_mode: s.sync_mode,
      tables: (s.tables ?? []).map((t: any) => ({
        table: t.table,
        status: t.status,
        rows: t.rows,
        error: t.error,
      })),
      isLive: false,
    })))
  }

  const fetchConnector = async () => {
    setLoading(true); setError(null)
    try {
      const [connRes, tablesRes, cfgRes] = await Promise.all([
        fetch(`/api/connectors/${id}`),
        fetch(`/api/connectors/${id}/tables`),
        fetch(`/api/connectors/${id}/config`),
      ])
      if (!connRes.ok) throw new Error(`Failed to load connector (HTTP ${connRes.status})`)
      setConnector(await connRes.json())
      if (tablesRes.ok) {
        const t = await tablesRes.json()
        setTables(Array.isArray(t.tables) ? t.tables.map((tb: any) =>
          typeof tb === "string" ? tb : tb.name ?? String(tb)) : [])
      }
      if (cfgRes.ok) {
        const cfg = await cfgRes.json()
        setConfigPreview(cfg.config ?? {})
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchConnector()
    fetchHistory()
  }, [id])

  // ── Sync Now (SSE → live session in history) ───────────────────────────────

  const handleSyncNow = async () => {
    setSyncing(true)
    const startedAt = new Date().toISOString()

    // Create live session placeholder
    const live: SyncSession = {
      id: "live",
      status: "running",
      started_at: startedAt,
      rows_processed: 0,
      rows_failed: 0,
      sync_mode: "full",
      tables: [],
      isLive: true,
    }
    setLiveSession(live)

    // Elapsed timer
    const start = Date.now()
    elapsedRef.current = setInterval(() => {
      setLiveSession(prev => prev ? { ...prev, duration_ms: Date.now() - start } : prev)
    }, 1000)

    try {
      const es = new EventSource(`/api/connectors/${id}/sync/stream`)

      es.addEventListener("step", (e) => {
        const d = JSON.parse(e.data)
        if (d.step === "discover" && d.tables) {
          setLiveSession(prev => prev ? {
            ...prev,
            tables: d.tables.map((t: string) => ({ table: t, status: "pending" as const })),
          } : prev)
        }
      })

      es.addEventListener("table_start", (e) => {
        const d = JSON.parse(e.data)
        setLiveSession(prev => prev ? {
          ...prev,
          tables: prev.tables.map(s => s.table === d.table ? { ...s, status: "running" as const } : s),
        } : prev)
      })

      es.addEventListener("table_step", (e) => {
        const d = JSON.parse(e.data)
        setLiveSession(prev => {
          if (!prev) return prev
          return {
            ...prev,
            tables: prev.tables.map(t =>
              t.table === d.table
                ? { ...t, steps: [...(t.steps ?? []), { step: d.step, message: d.message, pct: d.pct, rows_done: d.rows_done, rows_total: d.rows_total, action: d.action }] }
                : t
            )
          }
        })
      })

      es.addEventListener("table_done", (e) => {
        const d = JSON.parse(e.data)
        setLiveSession(prev => {
          if (!prev) return prev
          const tables = prev.tables.map(s =>
            s.table === d.table
              ? { ...s, status: d.status as "success" | "failed", rows: d.rows, error: d.error }
              : s
          )
          const rows = tables.reduce((sum, t) => sum + (t.rows ?? 0), 0)
          const failed = tables.filter(t => t.status === "failed").length
          return { ...prev, tables, rows_processed: rows, rows_failed: failed }
        })
      })

      es.addEventListener("done", (e) => {
        const d = JSON.parse(e.data)
        if (elapsedRef.current) clearInterval(elapsedRef.current)
        es.close()
        setSyncing(false)

        // Mark live session as completed (not live anymore) — keep visible
        setLiveSession(prev => prev ? {
          ...prev,
          isLive: false,
          status: d.tables_failed > 0 ? "failed" : "success",
          duration_ms: d.duration_ms,
        } : prev)

        fetchConnector()

        // Load history, then remove live session (history row replaces it)
        fetchHistory().then(() => {
          setLiveSession(null)
        })
      })

      es.addEventListener("error", (e: any) => {
        if (elapsedRef.current) clearInterval(elapsedRef.current)
        const msg = e.data ? JSON.parse(e.data).message : "Sync failed"
        setLiveSession(prev => prev ? { ...prev, status: "failed", isLive: false } : prev)
        es.close()
        setSyncing(false)
      })

      es.onerror = () => {
        if (elapsedRef.current) clearInterval(elapsedRef.current)
        setLiveSession(prev => prev ? { ...prev, status: "failed", isLive: false } : prev)
        es.close()
        setSyncing(false)
      }
    } catch (err) {
      if (elapsedRef.current) clearInterval(elapsedRef.current)
      setLiveSession(null)
      setSyncing(false)
    }
  }

  // ── Edit ───────────────────────────────────────────────────────────────────

  const startEdit = async () => {
    try {
      const res = await fetch(`/api/connectors/${id}/config`)
      if (!res.ok) throw new Error("Failed to load config")
      const data = await res.json()
      setEditName(data.name); setEditConnectorType(data.connector_type)
      setEditConfig(data.config ?? {}); setEditing(true)
      setSaveMessage(null); setTestResult(null)
    } catch (err) { setSaveMessage(err instanceof Error ? err.message : "Failed") }
  }

  const handleTestEdit = async (): Promise<void> => {
    setTesting(true); setTestResult(null)
    try {
      const cfgRes = await fetch(`/api/connectors/${id}/config`)
      const original = cfgRes.ok ? (await cfgRes.json()).config ?? {} : {}
      const merged = { ...original }
      for (const [k, v] of Object.entries(editConfig)) {
        if (String(v) !== "••••••••" && String(v) !== "") merged[k] = v
      }
      const res = await fetch("/api/connectors/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connector_type: editConnectorType, config: merged }),
      })
      const data = await res.json()
      setTestResult({ success: data.success, message: data.message })
    } catch (err) {
      setTestResult({ success: false, message: err instanceof Error ? err.message : "Test failed" })
    } finally { setTesting(false) }
  }

  const handleSave = async () => {
    setSaving(true); setSaveMessage(null)
    try {
      const res = await fetch(`/api/connectors/${id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: editName, config: editConfig }),
      })
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail ?? "Save failed") }
      setSaveMessage("Saved successfully."); setEditing(false)
      await fetchConnector()
    } catch (err) { setSaveMessage(err instanceof Error ? err.message : "Save failed.") }
    finally { setSaving(false) }
  }

  const handleDelete = async () => {
    if (!confirmDelete) { setConfirmDelete(true); return }
    setDeleting(true)
    try {
      const res = await fetch(`/api/connectors/${id}`, { method: "DELETE" })
      if (!res.ok) throw new Error(`Delete failed (HTTP ${res.status})`)
      router.push("/connectors")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete.")
      setDeleting(false); setConfirmDelete(false)
    }
  }

  const formatDateTime = (s: string | null) => {
    if (!s) return "Never"
    return new Intl.DateTimeFormat("en-US", {
      month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit"
    }).format(new Date(s))
  }

  // ── Derived ────────────────────────────────────────────────────────────────

  // Latest job rows per table from history (most recent session)
  const latestTableRows = new Map<string, number>()
  if (sessions[0]?.tables) {
    for (const t of sessions[0].tables) {
      if (t.rows != null) latestTableRows.set(t.table, t.rows)
    }
  }

  const SENSITIVE = ["password", "secret", "key", "token"]
  const previewEntries = Object.entries(configPreview).filter(
    ([k]) => !SENSITIVE.some(s => k.toLowerCase().includes(s))
  )

  // Stats from history
  const lastSession = sessions[0]
  const lastRunRows = lastSession?.rows_processed ?? null
  const recentSessions = sessions.slice(0, 10)
  const successRate = recentSessions.length > 0
    ? Math.round(recentSessions.filter(s => s.status === "success").length / recentSessions.length * 100)
    : null
  const freshnessMs = connector?.last_sync_at
    ? Date.now() - new Date(connector.last_sync_at).getTime() : null
  const freshnessLabel = freshnessMs === null ? "Never synced"
    : freshnessMs < 60_000 ? "< 1 min ago"
    : freshnessMs < 3_600_000 ? `${Math.floor(freshnessMs / 60_000)}m ago`
    : freshnessMs < 86_400_000 ? `${Math.floor(freshnessMs / 3_600_000)}h ago`
    : `${Math.floor(freshnessMs / 86_400_000)}d ago`
  const freshnessStale = freshnessMs !== null && freshnessMs > 86_400_000

  // Combined sessions for history component: live first, then past
  const allSessions: SyncSession[] = [
    ...(liveSession ? [liveSession] : []),
    ...sessions,
  ]

  // ── Loading / Error states ─────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <div className="flex items-center gap-4">
          <Skeleton className="h-9 w-9 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-8 w-64" />
            <div className="flex gap-2"><Skeleton className="h-5 w-24" /><Skeleton className="h-5 w-16" /></div>
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Card key={i}><CardHeader className="pb-2"><Skeleton className="h-4 w-24 mb-2" /><Skeleton className="h-7 w-16" /></CardHeader></Card>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Link href="/connectors"><Button variant="ghost" size="icon"><ChevronLeft className="h-4 w-4" /></Button></Link>
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />Failed to load connector
            </CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
          <CardContent><Button onClick={fetchConnector} variant="outline"><RefreshCw className="h-4 w-4 mr-2" />Retry</Button></CardContent>
        </Card>
      </div>
    )
  }

  if (!connector) return null

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">

      {/* Header */}
      <div className="flex items-center gap-4">
        <Link href="/connectors"><Button variant="ghost" size="icon"><ChevronLeft className="h-4 w-4" /></Button></Link>
        <div className="flex-1">
          <h2 className="text-3xl font-bold tracking-tight">{connector.name}</h2>
          <div className="flex items-center gap-2 mt-1">
            <Badge variant="outline" className="capitalize">{connector.connector_type}</Badge>
            <Badge variant={connector.status === "active" ? "default" : "secondary"}>{connector.status}</Badge>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={startEdit} disabled={editing}>
            <Pencil className="h-4 w-4 mr-2" />Edit
          </Button>
          <Button variant="outline" onClick={handleSyncNow} disabled={syncing}>
            <RefreshCw className={`h-4 w-4 mr-2 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "Syncing…" : "Sync Now"}
          </Button>
          <Button variant={confirmDelete ? "destructive" : "outline"} onClick={handleDelete} disabled={deleting}>
            <Trash2 className="h-4 w-4 mr-2" />
            {deleting ? "Deleting…" : confirmDelete ? "Confirm Delete" : "Delete"}
          </Button>
        </div>
      </div>

      {/* Feedback */}
      {saveMessage && (
        <div className={`text-sm px-1 ${saveMessage.includes("success") ? "text-green-600" : "text-destructive"}`}>
          {saveMessage}
        </div>
      )}
      {confirmDelete && !deleting && (
        <div className="text-sm text-destructive px-1 flex items-center gap-1">
          <AlertTriangle className="h-4 w-4" />
          Click "Confirm Delete" to permanently remove this connector.
          <Button variant="ghost" size="sm" className="ml-2 h-6 px-2 text-xs" onClick={() => setConfirmDelete(false)}>Cancel</Button>
        </div>
      )}

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card className={freshnessStale ? "border-amber-500/40" : ""}>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5"><RefreshCw className="h-4 w-4" />Data Freshness</CardDescription>
            <CardTitle className={`text-xl ${freshnessStale ? "text-amber-500" : ""}`}>{freshnessLabel}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5"><Rows3 className="h-4 w-4" />Last Sync Rows</CardDescription>
            <CardTitle className="text-2xl">{lastRunRows != null ? lastRunRows.toLocaleString() : "—"}</CardTitle>
          </CardHeader>
        </Card>
        <Card className={successRate !== null && successRate < 80 ? "border-red-400/50" : ""}>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <BarChart2 className="h-4 w-4" />Success Rate
              {recentSessions.length > 0 && <span className="text-[10px] text-muted-foreground/60">last {recentSessions.length}</span>}
            </CardDescription>
            <CardTitle className={`text-2xl ${successRate !== null && successRate < 80 ? "text-destructive" : ""}`}>
              {successRate !== null ? `${successRate}%` : "—"}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5"><Database className="h-4 w-4" />Tables</CardDescription>
            <CardTitle className="text-2xl">{tables.length || "—"}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {/* Connection Details / Edit */}
        <Card>
          <CardHeader>
            <CardTitle>Connection Details</CardTitle>
            <CardDescription>
              {editing ? "Edit connection settings" : `Last synced ${formatDateTime(connector.last_sync_at)}`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {editing ? (
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="conn-name">Connection Name</Label>
                  <Input id="conn-name" value={editName} onChange={e => setEditName(e.target.value)} />
                </div>
                <Separator />
                <ConnectionForm
                  fields={(getConnector(editConnectorType)?.fields ?? []).map(f => ({
                    ...f,
                    placeholder: editConfig[f.name] && String(editConfig[f.name]).startsWith("••")
                      ? "Leave blank to keep existing" : f.placeholder,
                  }))}
                  values={editConfig}
                  onChange={(name, value) => setEditConfig(prev => ({ ...prev, [name]: value }))}
                  onTest={handleTestEdit}
                  testStatus={testing ? "testing" : testResult === null ? "idle" : testResult.success ? "success" : "error"}
                  testMessage={testResult?.message}
                />
                <div className="flex gap-2 pt-2">
                  <Button size="sm" onClick={handleSave} disabled={saving}>
                    <Check className="h-4 w-4 mr-1" />{saving ? "Saving…" : "Save Changes"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setSaveMessage(null); setTestResult(null) }}>
                    <X className="h-4 w-4 mr-1" />Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-2 text-sm">
                {previewEntries.map(([key, val], i) => (
                  <div key={key}>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground capitalize">{key.replace(/_/g, " ")}</span>
                      <span className="font-mono text-xs">{String(val)}</span>
                    </div>
                    {i < previewEntries.length - 1 && <Separator className="mt-2" />}
                  </div>
                ))}
                {previewEntries.length === 0 && (
                  <p className="text-muted-foreground text-xs">No configuration preview available.</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Synced Tables */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              Synced Tables
              {tables.length > 0 && <Badge variant="secondary" className="text-xs font-normal">{tables.length} tables</Badge>}
            </CardTitle>
            <CardDescription>Iceberg 테이블 현황 · Query Lab에서 바로 조회 가능</CardDescription>
          </CardHeader>
          <CardContent>
            {tables.length === 0 ? (
              <div className="flex flex-col items-center py-8 gap-2 text-muted-foreground">
                <Database className="h-8 w-8 opacity-30" />
                <p className="text-sm">No tables synced yet</p>
                <p className="text-xs opacity-60">Click Sync Now to ingest tables into Iceberg</p>
              </div>
            ) : (
              <div className="space-y-0 max-h-64 overflow-y-auto">
                <div className="grid grid-cols-[1fr_auto_auto] gap-2 px-2 pb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground border-b">
                  <span>Table</span>
                  <span className="text-right w-16">Last Rows</span>
                  <span className="w-14" />
                </div>
                {tables.map((table) => {
                  const rows = latestTableRows.get(table)
                  const queryUrl = `/query?sql=${encodeURIComponent(`SELECT * FROM iceberg.default.${table} LIMIT 100`)}`
                  return (
                    <div key={table} className="grid grid-cols-[1fr_auto_auto] gap-2 items-center px-2 py-1.5 rounded hover:bg-muted/40 group">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <Database className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        <span className="font-mono text-xs truncate">{table}</span>
                      </div>
                      <span className="text-xs text-right text-muted-foreground w-16 font-mono">
                        {rows != null ? rows.toLocaleString() : "—"}
                      </span>
                      <a href={queryUrl}
                        className="w-14 text-[10px] text-primary hover:text-primary/70 opacity-0 group-hover:opacity-100 transition-opacity text-right">
                        Query →
                      </a>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Sync History — unified: live progress + past sessions */}
      <SyncHistory sessions={allSessions} />
    </div>
  )
}
