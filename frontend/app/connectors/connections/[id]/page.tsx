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
  AlertTriangle, Pencil, X, Check, Wifi, BarChart2, Calendar,
  Clock, Zap, Power, PowerOff, Search,
} from "lucide-react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"

// ── Tables Card (full-width, searchable) ──────────────────────────────────────
function TablesCard({
  tables, latestTableRows, togglingTable, onToggle, connId,
}: {
  tables: { name: string; enabled: boolean; sync_mode?: string; incremental_column?: string | null }[]
  latestTableRows: Map<string, number>
  togglingTable: string | null
  onToggle: (name: string, enabled: boolean) => void
  connId: string
}) {
  const [search, setSearch]         = useState("")
  const [editingTable, setEditingTable] = useState<string | null>(null)
  const [editMode, setEditMode]     = useState("full")
  const [editIncCol, setEditIncCol] = useState("")
  const [saving, setSaving]         = useState(false)

  const filtered = tables.filter(t =>
    t.name.toLowerCase().includes(search.toLowerCase())
  )
  const enabledCount = tables.filter(t => t.enabled).length

  const startEdit = (t: typeof tables[0]) => {
    setEditingTable(t.name)
    setEditMode(t.sync_mode || "full")
    setEditIncCol(t.incremental_column || "")
  }

  const saveEdit = async () => {
    if (!editingTable) return
    setSaving(true)
    try {
      await fetch(`/api/connectors/${connId}/tables/${editingTable}/enabled`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: tables.find(t => t.name === editingTable)?.enabled ?? true,
          incremental_column: editIncCol || null,
        }),
      })
      await fetch(`/api/connectors/${connId}/sync-mode`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sync_mode: editMode, table_name: editingTable }),
      })
      // Reload page to reflect changes
      window.location.reload()
    } finally {
      setSaving(false)
      setEditingTable(null)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Database className="h-4 w-4" />Tables
              {tables.length > 0 && (
                <Badge variant="secondary" className="text-xs font-normal">
                  {enabledCount}/{tables.length} enabled
                </Badge>
              )}
            </CardTitle>
            <CardDescription className="mt-0.5">Toggle to include/exclude from sync · Query in Iceberg</CardDescription>
          </div>
          {tables.length > 5 && (
            <div className="relative shrink-0">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Filter tables…"
                className="pl-8 h-8 text-xs w-48"
              />
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {tables.length === 0 ? (
          <div className="flex flex-col items-center py-8 gap-2 text-muted-foreground">
            <Database className="h-8 w-8 opacity-30" />
            <p className="text-sm">No tables found</p>
            <p className="text-xs opacity-60">Click Sync Now to discover tables</p>
          </div>
        ) : (
          <div>
            {/* Header row */}
            <div className="grid grid-cols-[auto_1fr_auto_auto_auto] gap-2 px-2 pb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground border-b">
              <span className="w-8">Sync</span>
              <span>Table</span>
              <span className="text-right w-20">Last Rows</span>
              <span className="w-28">Mode</span>
              <span className="w-20" />
            </div>
            {/* Table rows */}
            <div className="divide-y">
              {filtered.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-4">No tables match "{search}"</p>
              ) : filtered.map(table => {
                const rows = latestTableRows.get(table.name)
                const queryUrl = `/query?sql=${encodeURIComponent(`SELECT * FROM iceberg.default.${table.name} LIMIT 100`)}`
                const mode = table.sync_mode || "full"
                const incCol = table.incremental_column
                const isEditing = editingTable === table.name

                return (
                  <div key={table.name} className={`${table.enabled ? "" : "opacity-50"}`}>
                    {/* Main row */}
                    <div className={`grid grid-cols-[auto_1fr_auto_auto_auto] gap-2 items-center px-2 py-2 group transition-colors ${
                      table.enabled ? "hover:bg-muted/30" : "hover:bg-muted/10"
                    }`}>
                      <div className="w-8 flex items-center justify-center">
                        <Switch
                          checked={table.enabled}
                          disabled={togglingTable === table.name}
                          onCheckedChange={v => onToggle(table.name, v)}
                          className="scale-75"
                        />
                      </div>
                      <div className="flex items-center gap-1.5 min-w-0">
                        <Database className={`h-3.5 w-3.5 shrink-0 ${table.enabled ? "text-muted-foreground" : "text-muted-foreground/40"}`} />
                        <div className="min-w-0">
                          <span className={`font-mono text-xs truncate block ${!table.enabled ? "line-through text-muted-foreground/50" : ""}`}>
                            {table.name}
                          </span>
                          {incCol && (
                            <span className="text-[10px] text-primary/70 font-mono block truncate">↑ {incCol}</span>
                          )}
                        </div>
                      </div>
                      <span className="text-xs text-right text-muted-foreground w-20 font-mono">
                        {rows != null ? rows.toLocaleString() : "—"}
                      </span>
                      {/* Mode badge — clickable to edit */}
                      <button
                        onClick={() => isEditing ? setEditingTable(null) : startEdit(table)}
                        className={`w-28 text-left`}
                      >
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium border ${
                          mode === "incremental" ? "bg-primary/10 text-primary border-primary/20" :
                          mode === "cdc"         ? "bg-purple-500/10 text-purple-600 border-purple-200" :
                          "bg-muted text-muted-foreground border-transparent"
                        }`}>
                          {mode}
                          {incCol ? ` · ${incCol}` : ""}
                        </span>
                      </button>
                      <div className="w-20 flex items-center justify-end gap-1">
                        {table.enabled && (
                          <>
                            <button
                              onClick={() => isEditing ? setEditingTable(null) : startEdit(table)}
                              className="text-[10px] text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity px-1">
                              {isEditing ? "✕" : "Edit"}
                            </button>
                            <button
                              onClick={() => window.open(queryUrl, "_blank")}
                              className="text-[10px] text-primary hover:text-primary/70 opacity-0 group-hover:opacity-100 transition-opacity">
                              Query ↗
                            </button>
                          </>
                        )}
                        {!table.enabled && (
                          <span className="text-[10px] text-muted-foreground/40">skipped</span>
                        )}
                      </div>
                    </div>

                    {/* Inline edit panel */}
                    {isEditing && (
                      <div className="px-10 pb-3 pt-1 bg-muted/20 border-t space-y-3">
                        <div className="grid grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <label className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Sync Mode</label>
                            <Select value={editMode} onValueChange={v => { setEditMode(v ?? "full"); if (v !== "incremental") setEditIncCol("") }}>
                              <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="full" className="text-xs">Full Refresh — replace all data</SelectItem>
                                <SelectItem value="incremental" className="text-xs">Incremental — append new rows</SelectItem>
                                <SelectItem value="cdc" className="text-xs">CDC — capture all changes</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="space-y-1">
                            <label className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                              Watermark Column
                              {editMode !== "incremental" && <span className="ml-1 font-normal normal-case">(incremental only)</span>}
                            </label>
                            <Input
                              value={editIncCol}
                              onChange={e => setEditIncCol(e.target.value)}
                              placeholder={editMode === "incremental" ? "e.g. updated_at" : "—"}
                              disabled={editMode !== "incremental"}
                              className="h-7 text-xs font-mono"
                            />
                          </div>
                        </div>
                        {editMode === "incremental" && !editIncCol && (
                          <p className="text-[10px] text-amber-600 flex items-center gap-1">
                            ⚠ No watermark column set — incremental will load all rows on first run
                          </p>
                        )}
                        <div className="flex items-center gap-2">
                          <Button size="sm" className="h-6 text-xs" onClick={saveEdit} disabled={saving}>
                            {saving ? "Saving…" : "Save"}
                          </Button>
                          <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setEditingTable(null)}>
                            Cancel
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

const SCHEDULE_PRESETS = [
  { label: "Every 15 minutes", value: "*/15 * * * *",  desc: "High-frequency" },
  { label: "Hourly",           value: "0 * * * *",     desc: "Every hour at :00" },
  { label: "Every 6 hours",    value: "0 */6 * * *",   desc: "4× per day" },
  { label: "Daily at 2am",     value: "0 2 * * *",     desc: "Recommended for batch" },
  { label: "Daily at 6am",     value: "0 6 * * *",     desc: "Morning refresh" },
  { label: "Weekly (Mon 2am)", value: "0 2 * * 1",     desc: "Weekly batch" },
  { label: "Monthly (1st 2am)",value: "0 2 1 * *",     desc: "Monthly snapshot" },
]

function parseCron(cron: string): string {
  const p = SCHEDULE_PRESETS.find(p => p.value === cron)
  if (p) return p.label
  // basic human-readable for common patterns
  const parts = cron.split(" ")
  if (parts.length !== 5) return cron
  const [min, hour, dom, , dow] = parts
  if (min === "*" && hour === "*") return `Every minute`
  if (min.startsWith("*/")) return `Every ${min.slice(2)} minutes`
  if (hour === "*") return `Every hour at :${min.padStart(2,"0")}`
  if (dow === "*" && dom === "*") return `Daily at ${hour.padStart(2,"0")}:${min.padStart(2,"0")}`
  if (dom === "*" && dow !== "*") return `Weekly at ${hour}:${min.padStart(2,"0")}`
  return cron
}

function nextRun(cron: string): string {
  // Approximate next run (rough calculation)
  try {
    const parts = cron.split(" ")
    if (parts.length !== 5) return ""
    const now = new Date()
    const next = new Date(now)
    next.setSeconds(0, 0)
    next.setMinutes(next.getMinutes() + 1)

    const [min, hour] = parts
    if (min !== "*" && !min.startsWith("*/")) {
      next.setMinutes(parseInt(min))
      if (!hour.startsWith("*/") && hour !== "*") {
        next.setHours(parseInt(hour))
        if (next <= now) next.setDate(next.getDate() + 1)
      } else {
        if (next <= now) next.setHours(next.getHours() + 1)
      }
    }
    const diff = next.getTime() - now.getTime()
    const mins = Math.floor(diff / 60_000)
    if (mins < 60) return `in ${mins}m`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `in ${hrs}h ${mins % 60}m`
    return `in ${Math.floor(hrs / 24)}d`
  } catch { return "" }
}
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
  const [tables, setTables]               = useState<{name: string; enabled: boolean; sync_mode?: string; incremental_column?: string | null}[]>([])
  const [togglingTable, setTogglingTable] = useState<string | null>(null)
  const [configPreview, setConfigPreview] = useState<Record<string, any>>({})
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState<string | null>(null)
  const [syncing, setSyncing]             = useState(false)
  const [deleting, setDeleting]           = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  // History sessions (past + live)
  const [sessions, setSessions]           = useState<SyncSession[]>([])
  const [liveSession, setLiveSession]     = useState<SyncSession | null>(null)
  const [jobsRows, setJobsRows]           = useState<number | null>(null)  // fallback for lastRunRows
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

  // Schedule
  const [schedule, setSchedule]           = useState<string | null>(null)
  const [scheduleInput, setScheduleInput] = useState("")
  const [savingSchedule, setSavingSchedule] = useState(false)
  const [scheduleMsg, setScheduleMsg]     = useState<string | null>(null)

  // ── Fetch ──────────────────────────────────────────────────────────────────

  const fetchHistory = async () => {
    // Fetch jobs for fallback row count
    const jobsRes = await fetch(`/api/connectors/${id}/status`)
    if (jobsRes.ok) {
      const j = await jobsRes.json()
      const total = (j.jobs ?? []).reduce((sum: number, r: any) => sum + (r.rows_synced ?? 0), 0)
      if (total > 0) setJobsRows(total)
    }

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
      const connData = await connRes.json()
      setConnector(connData)
      // Sync schedule state from connection data (single source of truth)
      if (connData.schedule !== undefined) {
        setSchedule(connData.schedule ?? null)
        setScheduleInput(connData.schedule ?? "")
      }
      if (tablesRes.ok) {
        const t = await tablesRes.json()
        const raw = Array.isArray(t.tables) ? t.tables : []
        setTables(raw.map((tb: any) =>
          typeof tb === "string"
            ? { name: tb, enabled: true }
            : {
                name: tb.name ?? String(tb),
                enabled: tb.enabled !== false,
                sync_mode: tb.sync_mode ?? "full",
                incremental_column: tb.incremental_column ?? null,
              }
        ))
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

  const fetchSchedule = async () => {
    const res = await fetch(`/api/connectors/${id}/schedule`)
    if (res.ok) {
      const d = await res.json()
      setSchedule(d.schedule ?? null)
      setScheduleInput(d.schedule ?? "")
    }
  }

  const handleSaveSchedule = async (overrideSchedule?: string | null) => {
    const value = overrideSchedule !== undefined ? overrideSchedule : (scheduleInput || null)
    setSavingSchedule(true); setScheduleMsg(null)
    try {
      const res = await fetch(`/api/connectors/${id}/schedule`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schedule: value }),
      })
      const d = await res.json()
      if (!res.ok) throw new Error(d.detail ?? "Failed")
      setSchedule(value)
      if (!value) setScheduleInput("")
      setScheduleMsg(d.message)
    } catch (e) {
      setScheduleMsg(e instanceof Error ? e.message : "Failed")
    } finally { setSavingSchedule(false) }
  }

  useEffect(() => {
    fetchConnector()
    fetchHistory()
    fetchSchedule()
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

  const handleTableToggle = async (tableName: string, enabled: boolean) => {
    setTogglingTable(tableName)
    try {
      await fetch(`/api/connectors/${id}/tables/${tableName}/enabled`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      })
      setTables(prev => prev.map(t => t.name === tableName ? { ...t, enabled } : t))
    } finally { setTogglingTable(null) }
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
    const utc = s.endsWith("Z") || s.includes("+") ? s : s + "Z"
    return new Intl.DateTimeFormat("en-US", {
      month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit"
    }).format(new Date(utc))
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

  // Stats from history (fallback to syncRuns from /status if no history yet)
  const lastSession = sessions[0]
  const lastRunRows = lastSession?.rows_processed ?? jobsRows
  const recentSessions = sessions.slice(0, 10)
  const successRate = recentSessions.length > 0
    ? Math.round(recentSessions.filter(s => s.status === "success").length / recentSessions.length * 100)
    : null
  // Ensure UTC parsing — add Z if no timezone info to prevent local-time misinterpretation
  const toUTC = (s: string) => s.endsWith("Z") || s.includes("+") ? s : s + "Z"
  const freshnessMs = connector?.last_sync_at
    ? Date.now() - new Date(toUTC(connector.last_sync_at)).getTime() : null
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

      {/* Stats — uniform height via items-stretch */}
      <div className="grid gap-3 md:grid-cols-4">
        {/* 1. Tables */}
        <Card className="flex flex-col">
          <CardHeader className="pb-2 flex-1">
            <CardDescription className="flex items-center gap-1.5"><Database className="h-3.5 w-3.5" />Tables</CardDescription>
            <CardTitle className="text-2xl">
              {tables.length > 0
                ? <>{tables.filter(t => t.enabled).length}<span className="text-sm font-normal text-muted-foreground">/{tables.length}</span></>
                : "—"}
            </CardTitle>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              {tables.length > 0 ? `${tables.filter(t => !t.enabled).length} excluded` : "Sync to discover"}
            </p>
          </CardHeader>
        </Card>
        {/* 2. Last Sync Rows */}
        <Card className="flex flex-col">
          <CardHeader className="pb-2 flex-1">
            <CardDescription className="flex items-center gap-1.5"><Rows3 className="h-3.5 w-3.5" />Last Sync Rows</CardDescription>
            <CardTitle className="text-2xl">{lastRunRows != null ? lastRunRows.toLocaleString() : "—"}</CardTitle>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              {lastRunRows != null ? "rows ingested" : "no data yet"}
            </p>
          </CardHeader>
        </Card>
        {/* 3. Success Rate */}
        <Card className={`flex flex-col ${successRate !== null && successRate < 80 ? "border-destructive/30" : ""}`}>
          <CardHeader className="pb-2 flex-1">
            <CardDescription className="flex items-center gap-1.5">
              <BarChart2 className="h-3.5 w-3.5" />Success Rate
            </CardDescription>
            <CardTitle className={`text-2xl ${successRate !== null && successRate < 80 ? "text-destructive" : ""}`}>
              {successRate !== null ? `${successRate}%` : "—"}
            </CardTitle>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              {recentSessions.length > 0 ? `last ${recentSessions.length} syncs` : "no history"}
            </p>
          </CardHeader>
        </Card>
        {/* 4. Data Freshness */}
        <Card className={`flex flex-col ${freshnessStale ? "border-amber-500/40" : ""}`}>
          <CardHeader className="pb-2 flex-1">
            <CardDescription className="flex items-center gap-1.5"><RefreshCw className="h-3.5 w-3.5" />Data Freshness</CardDescription>
            <CardTitle className={`text-xl ${freshnessStale ? "text-amber-500" : ""}`}>{freshnessLabel}</CardTitle>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              {connector.last_sync_at ? formatDateTime(connector.last_sync_at) : "never synced"}
            </p>
          </CardHeader>
        </Card>
      </div>

      {/* ── Main 2-column layout — direct card children, no wrapper divs ── */}
      <div className="grid gap-4 md:grid-cols-[1fr_300px]">

        {/* Connection Details — stretches to match Schedule card height */}
        <Card className="min-w-0">
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

        {/* Schedule — stretches to match Connection Details height */}
        <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Calendar className="h-4 w-4" />Schedule
            </CardTitle>
            {/* Toggle switch */}
            <div className="flex items-center gap-2">
              {schedule && (
                <span className="text-xs text-muted-foreground">
                  Next run: <span className="font-medium text-foreground">{nextRun(schedule)}</span>
                </span>
              )}
              <Switch
                checked={!!schedule}
                disabled={savingSchedule || (!schedule && !scheduleInput)}
                onCheckedChange={(checked) => {
                  if (!checked) handleSaveSchedule(null)
                  else if (scheduleInput) handleSaveSchedule()
                }}
              />
            </div>
          </div>
          <CardDescription>
            {schedule ? (
              <span className="flex items-center gap-1.5">
                <Zap className="h-3.5 w-3.5 text-green-600" />
                <span className="text-green-600 font-medium">{parseCron(schedule)}</span>
                <span className="text-muted-foreground font-mono text-[10px]">({schedule})</span>
              </span>
            ) : (
              "Automate sync on a schedule via Airflow DAG"
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Preset buttons — compact single column */}
          <div className="space-y-1">
            {SCHEDULE_PRESETS.map(p => (
              <button
                key={p.value}
                onClick={() => setScheduleInput(p.value)}
                className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-md border text-xs transition-colors ${
                  scheduleInput === p.value
                    ? "border-primary bg-primary/5 text-primary font-medium"
                    : "border-transparent hover:border-border hover:bg-muted/30"
                }`}
              >
                <span>{p.label}</span>
                <span className="font-mono text-[10px] text-muted-foreground">{p.value}</span>
              </button>
            ))}
          </div>

          {/* Custom cron input */}
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground uppercase tracking-wide">Custom Expression</Label>
            <div className="flex gap-2">
              <Input
                value={scheduleInput}
                onChange={e => setScheduleInput(e.target.value)}
                placeholder="e.g. 0 */4 * * *"
                className="font-mono text-sm flex-1"
              />
              <Button
                size="sm" onClick={() => handleSaveSchedule()}
                disabled={savingSchedule || !scheduleInput}
                className="shrink-0"
              >
                {savingSchedule
                  ? <RefreshCw className="h-4 w-4 animate-spin" />
                  : <Check className="h-4 w-4" />}
                {schedule ? "Update" : "Enable"}
              </Button>
            </div>
            {scheduleInput && (
              <p className="text-xs text-muted-foreground flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {parseCron(scheduleInput)}
              </p>
            )}
          </div>

          {scheduleMsg && (
            <p className={`text-xs flex items-center gap-1 ${
              scheduleMsg.includes("removed") || scheduleMsg.includes("set") || scheduleMsg.includes("Schedule")
                ? "text-green-600" : "text-destructive"
            }`}>
              {scheduleMsg.includes("removed") || scheduleMsg.includes("set") || scheduleMsg.includes("Schedule")
                ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
              {scheduleMsg}
            </p>
          )}
        </CardContent>
        </Card>
      </div>{/* end 2-col grid */}

      {/* ── Tables — full width, searchable ── */}
      <TablesCard
        tables={tables}
        latestTableRows={latestTableRows}
        togglingTable={togglingTable}
        onToggle={handleTableToggle}
        connId={id}
      />

      {/* Sync History — full width */}
      <SyncHistory sessions={allSessions} />
    </div>
  )
}
