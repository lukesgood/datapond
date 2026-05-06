"use client"

import { use, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { SyncHistory } from "@/components/connectors/sync-history"
import { ChevronLeft, RefreshCw, Database, Rows3, Trash2, AlertTriangle, Pencil, X, Check, Wifi, BarChart2 } from "lucide-react"
import Link from "next/link"
import { ConnectionForm } from "@/components/connectors/connection-form"
import { getConnector } from "@/lib/connectors"

interface Connector {
  id: string
  name: string
  connector_type: string
  status: string
  created_at: string
  last_sync_at: string | null
}

export default function ConnectionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()

  const [connector, setConnector] = useState<Connector | null>(null)
  const [tables, setTables] = useState<string[]>([])
  const [syncRuns, setSyncRuns] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncMessage, setSyncMessage] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  // Edit state
  const [editing, setEditing] = useState(false)
  const [editConfig, setEditConfig] = useState<Record<string, any>>({})
  const [editName, setEditName] = useState("")
  const [editConnectorType, setEditConnectorType] = useState("")
  const [configPreview, setConfigPreview] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const fetchConnector = async () => {
    setLoading(true)
    setError(null)
    try {
      const [connRes, tablesRes, statusRes] = await Promise.all([
        fetch(`/api/connectors/${id}`),
        fetch(`/api/connectors/${id}/tables`),
        fetch(`/api/connectors/${id}/status`),
      ])
      if (!connRes.ok) throw new Error(`Failed to load connector (HTTP ${connRes.status})`)
      const data: Connector = await connRes.json()
      setConnector(data)
      if (tablesRes.ok) {
        const t = await tablesRes.json()
        setTables(Array.isArray(t.tables) ? t.tables.map((tb: any) =>
          typeof tb === "string" ? tb : tb.name ?? String(tb)
        ) : [])
      }
      if (statusRes.ok) {
        const s = await statusRes.json()
        const runs = (s.jobs ?? []).map((j: any) => ({
          id: j.job_id,
          status: j.status === "success" ? "success" : j.status === "failed" ? "failed" : "running",
          started_at: j.last_run_at ?? new Date().toISOString(),
          rows_synced: j.rows_synced ?? 0,
          source_table: j.source_table,
        }))
        setSyncRuns(runs)
      }
      // Load config preview for read-only display
      const cfgRes = await fetch(`/api/connectors/${id}/config`)
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

  const startEdit = async () => {
    try {
      const res = await fetch(`/api/connectors/${id}/config`)
      if (!res.ok) throw new Error("Failed to load config")
      const data = await res.json()
      setEditName(data.name)
      setEditConnectorType(data.connector_type)
      setEditConfig(data.config ?? {})
      setEditing(true)
      setSaveMessage(null)
      setTestResult(null)
    } catch (err) {
      setSaveMessage(err instanceof Error ? err.message : "Failed to load config")
    }
  }

  const handleTestEdit = async (): Promise<void> => {
    setTesting(true)
    setTestResult(null)
    try {
      const configRes = await fetch(`/api/connectors/${id}/config`)
      const original = configRes.ok ? (await configRes.json()).config ?? {} : {}
      const merged: Record<string, any> = { ...original }
      for (const [k, v] of Object.entries(editConfig)) {
        if (String(v) !== "••••••••" && String(v) !== "") merged[k] = v
      }
      const res = await fetch("/api/connectors/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connector_type: editConnectorType, config: merged }),
      })
      const data = await res.json()
      setTestResult({ success: data.success, message: data.message })
    } catch (err) {
      setTestResult({ success: false, message: err instanceof Error ? err.message : "Test failed" })
    } finally {
      setTesting(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveMessage(null)
    try {
      const res = await fetch(`/api/connectors/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: editName, config: editConfig }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail ?? `Save failed (HTTP ${res.status})`)
      }
      setSaveMessage("Saved successfully.")
      setEditing(false)
      await fetchConnector()
    } catch (err) {
      setSaveMessage(err instanceof Error ? err.message : "Save failed.")
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => { fetchConnector() }, [id])

  const handleSyncNow = async () => {
    setSyncing(true)
    setSyncMessage(null)
    try {
      const res = await fetch(`/api/connectors/${id}/sync`, { method: "POST" })
      if (!res.ok) throw new Error(`Sync request failed (HTTP ${res.status})`)
      setSyncMessage("Sync completed successfully.")
      const statusRes = await fetch(`/api/connectors/${id}/status`)
      if (statusRes.ok) {
        const s = await statusRes.json()
        setSyncRuns((s.jobs ?? []).map((j: any) => ({
          id: j.job_id,
          status: j.status === "success" ? "success" : j.status === "failed" ? "failed" : "running",
          started_at: j.last_run_at ?? new Date().toISOString(),
          rows_synced: j.rows_synced ?? 0,
          source_table: j.source_table,
        })))
      }
    } catch (err) {
      setSyncMessage(err instanceof Error ? err.message : "Failed to trigger sync.")
    } finally {
      setSyncing(false)
    }
  }

  const handleDelete = async () => {
    if (!confirmDelete) { setConfirmDelete(true); return }
    setDeleting(true)
    try {
      const res = await fetch(`/api/connectors/${id}`, { method: "DELETE" })
      if (!res.ok) throw new Error(`Delete failed (HTTP ${res.status})`)
      router.push("/connectors")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete connector.")
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  const formatDateTime = (dateString: string | null) => {
    if (!dateString) return "Never"
    return new Intl.DateTimeFormat("en-US", {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit"
    }).format(new Date(dateString))
  }

  // Config preview: show non-sensitive fields only
  const SENSITIVE = ["password", "secret", "key", "token"]
  const previewEntries = Object.entries(configPreview).filter(
    ([k]) => !SENSITIVE.some(s => k.toLowerCase().includes(s))
  )

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <div className="flex items-center gap-4">
          <Skeleton className="h-9 w-9 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-8 w-64" />
            <div className="flex gap-2"><Skeleton className="h-5 w-24" /><Skeleton className="h-5 w-16" /></div>
          </div>
          <Skeleton className="h-9 w-28" /><Skeleton className="h-9 w-28" />
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
        <div className="flex items-center gap-4">
          <Link href="/connectors"><Button variant="ghost" size="icon"><ChevronLeft className="h-4 w-4" /></Button></Link>
        </div>
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-destructive"><AlertTriangle className="h-5 w-5" />Failed to load connector</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
          <CardContent><Button onClick={fetchConnector} variant="outline"><RefreshCw className="h-4 w-4 mr-2" />Retry</Button></CardContent>
        </Card>
      </div>
    )
  }

  if (!connector) return null

  // Data engineering meaningful stats (after null check)
  const lastRun = syncRuns[0] ?? null
  const lastRunRows = lastRun?.rows_synced ?? null
  const recentRuns = syncRuns.slice(0, 10)
  const successRate = recentRuns.length > 0
    ? Math.round((recentRuns.filter(r => r.status === "success").length / recentRuns.length) * 100)
    : null
  const freshnessMs = connector.last_sync_at ? Date.now() - new Date(connector.last_sync_at).getTime() : null
  const freshnessLabel = freshnessMs === null ? "Never synced"
    : freshnessMs < 60_000 ? "< 1 min ago"
    : freshnessMs < 3_600_000 ? `${Math.floor(freshnessMs / 60_000)}m ago`
    : freshnessMs < 86_400_000 ? `${Math.floor(freshnessMs / 3_600_000)}h ago`
    : `${Math.floor(freshnessMs / 86_400_000)}d ago`
  const freshnessStale = freshnessMs !== null && freshnessMs > 86_400_000

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
            {syncing ? "Syncing..." : "Sync Now"}
          </Button>
          <Button variant={confirmDelete ? "destructive" : "outline"} onClick={handleDelete} disabled={deleting}>
            <Trash2 className="h-4 w-4 mr-2" />
            {deleting ? "Deleting..." : confirmDelete ? "Confirm Delete" : "Delete"}
          </Button>
        </div>
      </div>

      {/* Inline feedback */}
      {syncMessage && (
        <div className={`text-sm px-1 ${syncMessage.includes("success") ? "text-green-600" : "text-destructive"}`}>
          {syncMessage}
        </div>
      )}
      {saveMessage && (
        <div className={`text-sm px-1 ${saveMessage.includes("success") ? "text-green-600" : "text-destructive"}`}>
          {saveMessage}
        </div>
      )}
      {confirmDelete && !deleting && (
        <div className="text-sm text-destructive px-1 flex items-center gap-1">
          <AlertTriangle className="h-4 w-4" />
          Click "Confirm Delete" again to permanently remove this connector.
          <Button variant="ghost" size="sm" className="ml-2 h-6 px-2 text-xs" onClick={() => setConfirmDelete(false)}>Cancel</Button>
        </div>
      )}

      {/* Stats: data engineering meaningful metrics */}
      <div className="grid gap-4 md:grid-cols-4">
        {/* Data Freshness — most critical: how stale is the data? */}
        <Card className={freshnessStale ? "border-amber-400/50" : ""}>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <RefreshCw className="h-4 w-4" />Data Freshness
            </CardDescription>
            <CardTitle className={`text-xl ${freshnessStale ? "text-amber-500" : ""}`}>
              {freshnessLabel}
            </CardTitle>
          </CardHeader>
        </Card>

        {/* Last Sync Rows — anomaly detection: did today's sync look normal? */}
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <Rows3 className="h-4 w-4" />Last Sync Rows
            </CardDescription>
            <CardTitle className="text-2xl">
              {lastRunRows !== null ? lastRunRows.toLocaleString() : "—"}
            </CardTitle>
          </CardHeader>
        </Card>

        {/* Success Rate — pipeline reliability over last 10 runs */}
        <Card className={successRate !== null && successRate < 80 ? "border-red-400/50" : ""}>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <BarChart2 className="h-4 w-4" />Success Rate
              {recentRuns.length > 0 && (
                <span className="text-[10px] text-muted-foreground/60">last {recentRuns.length}</span>
              )}
            </CardDescription>
            <CardTitle className={`text-2xl ${successRate !== null && successRate < 80 ? "text-red-500" : ""}`}>
              {successRate !== null ? `${successRate}%` : "—"}
            </CardTitle>
          </CardHeader>
        </Card>

        {/* Tables — sync scope */}
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <Database className="h-4 w-4" />Tables
            </CardDescription>
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
              {editing ? "Edit connection settings below" : "Last synced " + formatDateTime(connector.last_sync_at)}
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
                      ? "Leave blank to keep existing"
                      : f.placeholder,
                  }))}
                  values={editConfig}
                  onChange={(name, value) => setEditConfig(prev => ({ ...prev, [name]: value }))}
                  onTest={handleTestEdit}
                  testStatus={testing ? "testing" : testResult === null ? "idle" : testResult.success ? "success" : "error"}
                  testMessage={testResult?.message}
                />
                <div className="flex gap-2 pt-2">
                  <Button size="sm" onClick={handleSave} disabled={saving}>
                    <Check className="h-4 w-4 mr-1" />
                    {saving ? "Saving..." : "Save Changes"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setSaveMessage(null); setTestResult(null) }}>
                    <X className="h-4 w-4 mr-1" />Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-2 text-sm">
                {/* Non-sensitive config fields */}
                {previewEntries.length > 0 && previewEntries.map(([key, val], i) => (
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

        {/* Available Tables */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              Available Tables
              {tables.length > 0 && (
                <Badge variant="secondary" className="text-xs font-normal">{tables.length} tables</Badge>
              )}
            </CardTitle>
            <CardDescription>Tables accessible via this connection</CardDescription>
          </CardHeader>
          <CardContent>
            {tables.length === 0 ? (
              <div className="flex flex-col items-center py-8 gap-2 text-muted-foreground">
                <Database className="h-8 w-8 opacity-30" />
                <p className="text-sm">No tables found</p>
                <p className="text-xs opacity-60">Click Sync Now to discover tables</p>
              </div>
            ) : (
              <div className="space-y-1 max-h-64 overflow-y-auto">
                {tables.map((table) => (
                  <div key={table} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted/50">
                    <Database className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                    <span className="font-mono text-xs">{table}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Sync History */}
      <SyncHistory runs={syncRuns} />
    </div>
  )
}
