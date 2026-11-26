"use client"

import { use, useCallback, useEffect, useState, useRef } from "react"
import { useToast } from "@/lib/toast"
import { latestRowsByTable } from "@/lib/sync-table-rows"
import { useConfirm } from "@/lib/confirm"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { Diagnosis } from "@/lib/ops-status"
import { SyncHistory, SyncSession } from "@/components/connectors/sync-history"
import { SourceAccessPanel } from "@/components/connectors/access-panel"
import { TableSettingsPanel, type SourceTable } from "@/components/connectors/table-settings-panel"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { useHasPermission } from "@/lib/permissions"
import {
  ChevronLeft, RefreshCw, Database, Trash2,
  AlertTriangle, Pencil, X, Check, Calendar,
  Clock, Zap, Search, PlugZap, Pause, Play,
} from "lucide-react"
import { Switch } from "@/components/ui/switch"
import Link from "next/link"
import { ConnectionForm } from "@/components/connectors/connection-form"
import { configRows, getConnector, readsEverythingEachSync } from "@/lib/connectors"
import { describeCheck } from "@/lib/source-check"
import { parseCron, nextRun } from "@/lib/schedule"
import { SchedulePicker } from "@/components/ui/schedule-picker"
import { useCapability } from "@/lib/capabilities"
import { EngineRestartBanner } from "@/components/connectors/engine-restart-banner"
import { isTrinoEngine } from "@/lib/engine-restart"
import { lakeCatalogs, lakeLabel, landsIn } from "@/lib/data-catalogs"
import { runLabel, runStates, shortDate } from "@/lib/table-runs"

type OrphanJob = { source_table: string; enabled: boolean; last_run_at: string | null; last_run_status: string | null }
import { alsoSyncedLine } from "@/lib/sync-target"

type ConfigValue = string | number | boolean | null | undefined
type ConnectorTable = SourceTable
interface RawTableConfig extends Partial<ConnectorTable> { name: string }
interface JobsResponse { jobs?: Array<{ rows_synced?: number }> }
interface RawSyncSession {
  id: string
  status: SyncSession["status"]
  started_at: string
  completed_at?: string
  rows_processed: number
  rows_failed: number
  duration_ms?: number
  sync_mode?: string
  error_message?: string
  error?: string
  tables?: Array<{ table: string; status: "pending" | "running" | "success" | "failed"; rows?: number; error?: string; diagnosis?: Diagnosis | null }>
  diagnosis?: Diagnosis | null
}
interface QualityWarning { severity: string; message: string; type?: string; column?: string }
interface NullCheck { null_rate: number; status: string }
interface QualityCheck {
  source_table: string
  table_key?: string
  expected_null_columns?: string[]
  overall_status: string
  checked_at: string
  rows_current?: number
  row_change_pct?: number | null
  row_change_status?: string
  warnings?: QualityWarning[]
  null_checks?: Record<string, NullCheck>
}

type Lake = { name: string; engine_catalog: string; is_default: boolean; kind: string; enabled: boolean }

// ── Tables: the list; one table's settings open in the right column ──────────
function TablesCard({
  tables, latestTableRows, togglingTable, onToggle, selected, onSelect, canEdit, defaultLake, lakes = [],
  orphaned = [], onDeleteOrphan, refetch = false,
}: {
  refetch?: boolean
  tables: ConnectorTable[]
  latestTableRows: Map<string, number>
  togglingTable: string | null
  onToggle: (name: string, enabled: boolean) => void
  selected: string | null
  onSelect: (name: string | null) => void
  canEdit: boolean
  defaultLake?: string
  lakes?: Lake[]
  orphaned?: OrphanJob[]
  onDeleteOrphan?: (job: OrphanJob) => void
}) {
  const [search, setSearch] = useState("")
  const states = runStates(tables)
  const filtered = tables.filter(t => t.name.toLowerCase().includes(search.toLowerCase()))
  const enabledCount = tables.filter(t => t.enabled).length

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-base">
            Tables {tables.length > 0 && <span className="font-normal text-muted-foreground">· {enabledCount} synced of {tables.length}</span>}
          </CardTitle>
          {tables.length > 5 && (
            <div className="relative shrink-0">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Filter tables"
                     aria-label="Filter tables" className="h-8 w-48 pl-8 text-xs" />
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {tables.length === 0 ? (
          <div className="flex flex-col items-center gap-1 py-8 text-muted-foreground">
            <p className="text-sm">No tables yet</p>
            <p className="text-xs">Sync now to discover this source&apos;s tables.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th scope="col" className="w-12 py-2 font-medium">Sync</th>
                  <th scope="col" className="py-2 font-medium">Table</th>
                  <th scope="col" className="py-2 font-medium">Mode</th>
                  <th scope="col" className="py-2 font-medium">Last run</th>
                  <th scope="col" className="py-2 pr-6 text-right font-medium">Last rows</th>
                  <th scope="col" className="py-2 font-medium">Masked</th>
                  <th scope="col" className="py-2"><span className="sr-only">Settings</span></th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr><td colSpan={7} className="py-4 text-center text-xs text-muted-foreground">No tables match &quot;{search}&quot;</td></tr>
                )}
                {filtered.map(table => {
                  const rows = latestTableRows.get(table.name)
                  const mode = table.sync_mode || "full"
                  const noWatermark = !refetch && mode === "incremental" && !table.incremental_column
                  const on = selected === table.name
                  return (
                    <tr key={table.name} className={`border-b last:border-0 ${on ? "bg-primary/5" : ""} ${table.enabled ? "" : "text-muted-foreground"}`}>
                      <td className="py-2">
                        <Switch checked={table.enabled} disabled={!canEdit || togglingTable === table.name}
                                aria-label={`Sync ${table.name}`} onCheckedChange={v => onToggle(table.name, v)} className="scale-75" />
                      </td>
                      <td className="py-2">
                        <span className="font-mono text-xs">{table.name}</span>
                        {landsIn(table.target_catalog, defaultLake) && <span className="block text-xs text-muted-foreground">→ {lakeLabel(table.target_catalog, lakes)}</span>}
                        {alsoSyncedLine(table.also_synced_as) && (
                          <span className="block text-xs text-[var(--dp-warn-text)]" title="Two jobs land in the same lake table. Keep one: change the other job's target or turn it off.">
                            {alsoSyncedLine(table.also_synced_as)}</span>
                        )}
                        {noWatermark && <span className="block text-xs text-[var(--dp-warn-text)]">no changed-since column — reads the whole table</span>}
                        {table.is_new && <span className="block text-xs text-[var(--dp-warn-text)]">new in the source — not synced until you turn it on (check its masked columns first)</span>}
                      </td>
                      <td className="py-2 text-xs">
                        {refetch
                          ? (table.key_columns?.length ? <>Merge<span className="text-muted-foreground"> · {table.key_columns.join(", ")}</span></> : "Replace")
                          : mode === "incremental" ? <>Changed rows{table.incremental_column && <span className="text-muted-foreground"> · {table.incremental_column}</span>}</> : "Full refresh"}
                      </td>
                      <td className={`py-2 text-xs ${states[table.name] === "failed" || states[table.name] === "behind" ? "text-[var(--dp-warn-text)]" : ""}`}>
                        {runLabel(states[table.name], table.last_run_at)}
                      </td>
                      <td className="py-2 pr-6 text-right font-mono text-xs">{rows != null ? rows.toLocaleString() : "—"}</td>
                      <td className="py-2 font-mono text-xs">{table.pii_columns?.length ? table.pii_columns.join(", ") : <span className="text-muted-foreground">—</span>}</td>
                      <td className="py-2 text-right">
                        <Button size="sm" variant={on ? "secondary" : "outline"} className="h-7 text-xs"
                                onClick={() => onSelect(on ? null : table.name)}>
                          {on ? "Close" : canEdit ? "Edit" : "View"}
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {orphaned.length > 0 && (
          <section aria-label="Jobs for tables the source no longer has" className="mt-4 space-y-2 border-t pt-3">
            <h3 className="text-sm font-semibold">Not in the source any more</h3>
            <p className="text-xs text-muted-foreground">These jobs name tables the source no longer lists (dropped, renamed, or system tables picked before they were hidden). They never run. Deleting a job keeps the lake table it wrote.</p>
            <ul className="space-y-1">
              {orphaned.map(j => (
                <li key={j.source_table} className="flex items-center justify-between gap-2 text-xs">
                  <span><span className="font-mono">{j.source_table}</span>
                    <span className="text-muted-foreground"> · {j.last_run_at ? `last ${j.last_run_status ?? "run"} ${shortDate(j.last_run_at)}` : "never run"}</span></span>
                  {canEdit && onDeleteOrphan && <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => onDeleteOrphan(j)}>Delete job</Button>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </CardContent>
    </Card>
  )
}

// ── Schedule Card ─────────────────────────────────────────────────────────────
type ScheduleInfo = {
  timezone?: string; next_run_at?: string | null; last_run_at?: string | null; last_status?: string | null
}

/** A scheduler time in the viewer's clock, e.g. "Thu 08:00". */
function scheduleWhen(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })
}
function ScheduleCard({
  schedule, info, savingSchedule, scheduleMsg, onSave, schedulerEnabled, canEdit,
}: {
  schedule: string | null
  /** Zone, next run and last run, as the backend scheduler reports them. */
  info: ScheduleInfo | null
  savingSchedule: boolean
  scheduleMsg: string | null
  onSave: (val: string | null) => void
  schedulerEnabled: boolean
  /** connector:write; without it the card shows the schedule and changes nothing. */
  canEdit: boolean
}) {
  // The choice being edited; the card is re-keyed on the saved schedule.
  const [draft, setDraft] = useState<string>(schedule ?? "0 2 * * *")
  const builtCron = draft
  const isDirty = builtCron !== schedule

  // Schedules run in the backend (app/sync_scheduler.py); a deployment can turn that
  // off, and then the card says so instead of promising runs that never happen.
  if (!schedulerEnabled) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Calendar className="h-4 w-4" />Schedule
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded-lg bg-muted/30 border border-dashed px-3 py-2.5 text-xs text-muted-foreground text-center">
            Scheduled syncs are turned off on this deployment. Sync with <strong>Sync Now</strong>.
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <Calendar className="h-4 w-4" />Schedule
          </CardTitle>
          <Switch
            checked={!!schedule}
            disabled={savingSchedule || !canEdit}
            aria-label={schedule ? "Turn the schedule off" : "Turn the schedule on"}
            onCheckedChange={checked => onSave(checked ? builtCron : null)}
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* Status */}
        {schedule ? (
          <div className="flex items-center gap-2 rounded-lg bg-[var(--dp-good)]/10 border border-[var(--dp-good)]/20 px-3 py-2">
            <Zap className="h-4 w-4 text-[var(--dp-good-text)] shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-[var(--dp-good-text)]">
                {parseCron(schedule)}{info?.timezone ? <span className="font-normal"> ({info.timezone})</span> : null}
              </p>
              {(info?.next_run_at || nextRun(schedule)) && (
                <p className="text-xs text-[var(--dp-good-text)]/70 flex items-center gap-1 mt-0.5">
                  <Clock className="h-3 w-3" />Next run {info?.next_run_at ? scheduleWhen(info.next_run_at) : nextRun(schedule)}
                </p>
              )}
            </div>
          </div>
        ) : (
          <div className="rounded-lg bg-muted/30 border border-dashed px-3 py-2.5 text-xs text-muted-foreground text-center">
            Off — sync manually with <strong>Sync Now</strong>
          </div>
        )}

        {schedule && info?.last_status && (
          <p className={`text-xs ${info.last_status.startsWith("success") ? "text-muted-foreground" : "text-[var(--dp-warn-text)]"}`}>
            Last scheduled run{info.last_run_at ? ` ${scheduleWhen(info.last_run_at)}` : ""}: {info.last_status}
          </p>
        )}
        {schedule && (
          <p className="text-2xs text-muted-foreground">
            Runs as whoever saved the schedule. A run due while the node is stopped runs once when it starts.
          </p>
        )}

        {canEdit ? (
          <SchedulePicker id="conn-schedule" value={draft} allowManual={false} disabled={savingSchedule}
                          onChange={c => { if (c) setDraft(c) }} />
        ) : (
          <p className="text-xs text-muted-foreground">Changing the schedule needs connector:write.</p>
        )}

        {/* Apply button */}
        {canEdit && (
        <Button
          className="w-full"
          size="sm"
          disabled={savingSchedule || !isDirty}
          onClick={() => onSave(builtCron)}
        >
          {savingSchedule
            ? <><RefreshCw className="h-4 w-4 animate-spin mr-2" />Saving…</>
            : schedule
              ? <><Check className="h-4 w-4 mr-2" />Apply Changes</>
              : <><Zap className="h-4 w-4 mr-2" />Enable Schedule</>}
        </Button>
        )}

        {scheduleMsg && (
          <p className={`text-xs flex items-center gap-1 ${
            scheduleMsg.toLowerCase().includes("error") || scheduleMsg.toLowerCase().includes("fail")
              ? "text-destructive" : "text-[var(--dp-good-text)]"
          }`}>
            {scheduleMsg.toLowerCase().includes("error") || scheduleMsg.toLowerCase().includes("fail")
              ? <X className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
            {scheduleMsg}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

interface Connector {
  id: string; name: string; connector_type: string
  status: string; created_at: string; last_sync_at: string | null
  last_checked_at?: string | null; last_check_message?: string | null
  catalog?: string | null
}

export default function ConnectionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const schedulerEnabled = useCapability("scheduled_sync")
  const catalogEnabled = useCapability("catalog")
  // The routes that change a source (sync, pause, edit, tables, delete) need
  // connector:write; only "check connection" is open to every reader.
  const canWrite = useHasPermission("connector:write")
  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const [lakes, setLakes] = useState<Lake[]>([])
  useEffect(() => {
    fetch("/api/catalogs").then(r => (r.ok ? r.json() : { catalogs: [] }))
      .then(d => setLakes(lakeCatalogs<Lake>(d.catalogs ?? [])))
      .catch(() => setLakes([]))
  }, [])
  const defaultLake = lakes.find(c => c.is_default)?.name

  const [connector, setConnector]         = useState<Connector | null>(null)
  // The engine restarts when a Trino-backed source is created or re-configured; the
  // wizard says so in the URL, and the banner polls until it is back.
  const [engineRestarting, setEngineRestarting] = useState(false)
  const [tables, setTables]               = useState<ConnectorTable[]>([])
  const [orphaned, setOrphaned]           = useState<OrphanJob[]>([])
  const [togglingTable, setTogglingTable] = useState<string | null>(null)
  const [configPreview, setConfigPreview] = useState<Record<string, ConfigValue>>({})
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState<string | null>(null)
  const [syncing, setSyncing]             = useState(false)
  const [checking, setChecking]           = useState(false)
  const [deleting, setDeleting]           = useState(false)
  // The sync-complete toast points at Catalog but auto-dismisses; keep a
  // persistent CTA so the ingest → explore journey isn't a dead end.
  const [syncedOk, setSyncedOk]           = useState(false)

  // History sessions (past + live)
  const [sessions, setSessions]           = useState<SyncSession[]>([])
  const { toast } = useToast()
  const confirmDialog = useConfirm()
  const [liveSession, setLiveSession]     = useState<SyncSession | null>(null)
  const [jobsRows, setJobsRows]           = useState<number | null>(null)  // fallback for lastRunRows
  const elapsedRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Edit
  const [editing, setEditing]             = useState(false)
  const [editConfig, setEditConfig]       = useState<Record<string, ConfigValue>>({})
  const [editName, setEditName]           = useState("")
  const [editConnectorType, setEditConnectorType] = useState("")
  const [saving, setSaving]               = useState(false)
  // Typed outcome: the colour used to depend on whether the text contained "success".
  const [saveMessage, setSaveMessage]     = useState<{ ok: boolean; text: string } | null>(null)
  const [testing, setTesting]             = useState(false)
  const [testResult, setTestResult]       = useState<{ success: boolean; message: string } | null>(null)

  // Schedule
  const [schedule, setSchedule]           = useState<string | null>(null)
  const [scheduleInfo, setScheduleInfo]   = useState<ScheduleInfo | null>(null)
  const [scheduleInput, setScheduleInput] = useState("")
  const [savingSchedule, setSavingSchedule] = useState(false)
  const [scheduleMsg, setScheduleMsg]     = useState<string | null>(null)

  // Quality
  const [qualityChecks, setQualityChecks] = useState<QualityCheck[]>([])

  // ── Fetch ──────────────────────────────────────────────────────────────────

  const fetchHistory = useCallback(async () => {
    // Fetch jobs for fallback row count
    const jobsRes = await fetch(`/api/connectors/${id}/status`)
    if (jobsRes.ok) {
      const jobs: JobsResponse = await jobsRes.json()
      const total = (jobs.jobs ?? []).reduce((sum, job) => sum + (job.rows_synced ?? 0), 0)
      if (total > 0) setJobsRows(total)
    }

    const res = await fetch(`/api/connectors/${id}/history`)
    if (!res.ok) return
    const data: RawSyncSession[] = await res.json()
    setSessions(data.map(s => ({
      id: s.id,
      status: s.status,
      started_at: s.started_at,
      completed_at: s.completed_at,
      rows_processed: s.rows_processed,
      rows_failed: s.rows_failed,
      duration_ms: s.duration_ms,
      sync_mode: s.sync_mode,
      error: s.error_message ?? s.error,
      tables: (s.tables ?? []).map((table) => ({
        table: table.table,
        status: table.status,
        rows: table.rows,
        error: table.error,
        diagnosis: table.diagnosis,
      })),
      isLive: false,
    })))
  }, [id])

  // "Now" for the freshness labels, taken when the source was last loaded (render must
  // not read the clock).
  const [loadedAt, setLoadedAt] = useState(() => Date.now())
  const fetchConnector = useCallback(async () => {
    setLoading(true); setError(null); setLoadedAt(Date.now())
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
        setTables((raw as Array<string | RawTableConfig>).map((table) =>
          typeof table === "string"
            ? { name: table, enabled: true }
            : {
                name: table.name,
                enabled: table.enabled !== false,
                sync_mode: table.sync_mode ?? "full",
                incremental_column: table.incremental_column ?? null,
                last_value: table.last_value ?? null,
                effective_mode: table.effective_mode ?? table.sync_mode ?? "full",
                partition_spec: table.partition_spec ?? null,
                key_columns: table.key_columns ?? null,
                pii_columns: table.pii_columns ?? null,
                target_catalog: table.target_catalog ?? null,
                also_synced_as: table.also_synced_as ?? [],
                is_new: table.is_new ?? false,
                last_run_at: table.last_run_at ?? null,
                last_run_status: table.last_run_status ?? null,
              }
        ))
        setOrphaned(Array.isArray(t.orphaned) ? t.orphaned : [])
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
  }, [id])

  const fetchSchedule = useCallback(async () => {
    const res = await fetch(`/api/connectors/${id}/schedule`)
    if (res.ok) {
      const d = await res.json()
      setSchedule(d.schedule ?? null)
      setScheduleInfo(d)
      setScheduleInput(d.schedule ?? "")
    }
  }, [id])

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
      setScheduleInfo(d)
      if (!value) setScheduleInput("")
      setScheduleMsg(d.message)
    } catch (e) {
      setScheduleMsg(e instanceof Error ? e.message : "Failed")
    } finally { setSavingSchedule(false) }
  }

  const fetchQuality = useCallback(async () => {
    try {
      const res = await fetch(`/api/connectors/${id}/quality?limit=200`)
      if (res.ok) {
        const data: { checks?: QualityCheck[] } = await res.json()
        setQualityChecks(data.checks ?? [])
      }
    } catch { /* non-critical */ }
  }, [id])

  useEffect(() => {
    // The wizard lands here with ?engine=restarting right after creating a Trino-backed
    // source; hold Sync until the banner's first poll says otherwise.
    if (new URLSearchParams(window.location.search).get("engine") !== "restarting") return
    const t = window.setTimeout(() => setEngineRestarting(true), 0)
    return () => window.clearTimeout(t)
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => {
      void fetchConnector()
      void fetchHistory()
      void fetchSchedule()
      void fetchQuality()
    }, 0)
    return () => window.clearTimeout(initial)
  }, [fetchConnector, fetchHistory, fetchQuality, fetchSchedule])

  // ── Sync Now (SSE → live session in history) ───────────────────────────────

  // Tests the saved connection now and records the result as the status — the one
  // way to refresh a status without running a sync.
  const handleCheck = async () => {
    setChecking(true)
    try {
      const res = await fetch(`/api/connectors/${id}/check`, { method: "POST" })
      const d = await res.json()
      if (!res.ok) throw new Error(d.detail ?? `Check failed (HTTP ${res.status})`)
      toast(d.success ? "Source reachable" : `Source unreachable: ${d.message}`,
            d.success ? "success" : "error")
      await fetchConnector()
    } catch (err) {
      toast(err instanceof Error ? err.message : "Check failed", "error")
    } finally {
      setChecking(false)
    }
  }

  // Not in use: a paused source is not reported as stale and skips the background check.
  const [pausing, setPausing] = useState(false)
  const handlePauseToggle = async () => {
    if (!connector) return
    const resume = connector.status === "paused"
    if (!resume) {
      const ok = await confirmDialog({
        title: `Pause ${connector.name}?`,
        message: "Pause a source you are not using: it is no longer reported as stale on Overview and skips the background connection check until you resume it. Its lake tables stay as they are, and Sync Now still works.",
        confirmText: "Pause source",
      })
      if (!ok) return
    }
    setPausing(true)
    try {
      const res = await fetch(`/api/connectors/${id}/${resume ? "resume" : "pause"}`, { method: "POST" })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail ?? `HTTP ${res.status}`)
      toast(resume ? `Resumed ${connector.name}` : `Paused ${connector.name}`, "success")
      await fetchConnector()
    } catch (err) {
      toast(`${resume ? "Resume" : "Pause"} failed: ${err instanceof Error ? err.message : String(err)}`, "error")
    } finally {
      setPausing(false)
    }
  }

  const handleSyncNow = async () => {
    setSyncing(true)
    setSyncedOk(false)
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
    const start = new Date(startedAt).getTime()
    elapsedRef.current = setInterval(() => {
      setLiveSession(prev => prev ? { ...prev, duration_ms: new Date().getTime() - start } : prev)
    }, 1000)

    try {
      const res = await fetch(`/api/connectors/${id}/sync/stream`, {
        credentials: "include",
      })
      if (!res.ok || !res.body) {
        const msg = `Sync failed (HTTP ${res.status})`
        setLiveSession(prev => prev ? { ...prev, status: "failed", isLive: false, error: msg } : prev)
        setSyncing(false)
        if (elapsedRef.current) clearInterval(elapsedRef.current)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      // Set by a "done" or "error" event. A stream that closes without either (proxy
      // timeout, pod restart, network drop) must not leave the page on "Syncing…".
      let finished = false
      const handleEvent = (eventType: string, dataStr: string) => {
        if (eventType === "done" || eventType === "error") finished = true
        try {
          const d = JSON.parse(dataStr)
          if (eventType === "step") {
            if (d.step === "discover" && d.tables) {
              setLiveSession(prev => prev ? {
                ...prev,
                tables: d.tables.map((t: string) => ({ table: t, status: "pending" as const })),
              } : prev)
            }
          } else if (eventType === "table_start") {
            setLiveSession(prev => prev ? {
              ...prev,
              tables: prev.tables.map(s => s.table === d.table ? { ...s, status: "running" as const } : s),
            } : prev)
          } else if (eventType === "table_step") {
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
          } else if (eventType === "table_done") {
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
          } else if (eventType === "done") {
            if (elapsedRef.current) clearInterval(elapsedRef.current)
            setSyncing(false)
            if (d.tables_failed > 0) toast(`Sync complete — ${d.tables_failed} table(s) failed (see history)`, "error")
            else { toast("Sync complete — check Catalog for the ingested results", "success"); setSyncedOk(true) }
            setLiveSession(prev => prev ? {
              ...prev, isLive: false,
              status: d.tables_failed > 0 ? "failed" : "success",
              duration_ms: d.duration_ms,
            } : prev)
            fetchConnector()
            fetchHistory().then(() => setLiveSession(null))
            setTimeout(fetchQuality, 5000) // quality checks run async after sync
          } else if (eventType === "error") {
            if (elapsedRef.current) clearInterval(elapsedRef.current)
            setSyncing(false)
            setLiveSession(prev => prev ? { ...prev, status: "failed", isLive: false, error: d.message } : prev)
            fetchHistory().then(() => setLiveSession(null))
          }
        } catch {}
      }

      // Parse SSE stream manually. Event type and data persist across reads: one event
      // can arrive split over two chunks.
      let eventType = "message"
      let dataLines: string[] = []
      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          buffer += decoder.decode()
          if (buffer.startsWith("data:")) dataLines.push(buffer.slice(5).trim())
          if (dataLines.length > 0) handleEvent(eventType, dataLines.join("\n"))
          break
        }
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() ?? ""
        for (const line of lines) {
          if (line.startsWith("event:")) {
            eventType = line.slice(6).trim()
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).trim())
          } else if (line === "") {
            if (dataLines.length > 0) {
              handleEvent(eventType, dataLines.join("\n"))
              eventType = "message"
              dataLines = []
            }
          }
        }
      }
      if (!finished) streamLost()
    } catch (err) {
      streamLost(err instanceof Error ? err.message : String(err))
    }
  }

  // The page lost the stream before the sync said it was done. The sync may still be
  // running on the server, so this does not say it failed: it says what is known and
  // reloads the run history, which is the record of what actually happened.
  const streamLost = (detail?: string) => {
    if (elapsedRef.current) clearInterval(elapsedRef.current)
    setSyncing(false)
    const msg = "Lost the connection before the sync finished" + (detail ? ` (${detail})` : "")
      + ". It keeps running on the server — the run history below shows the result."
    setLiveSession(prev => prev ? { ...prev, status: "failed", isLive: false, error: msg } : prev)
    toast(msg, "error")
    fetchConnector()
    fetchHistory().then(() => setLiveSession(null))
  }

  // The wizard lands here with ?sync=1 after "Create and sync": the first sync runs
  // from this page, so its progress and any failure show here (the wizard used to fire
  // the request and never read the answer). Once, then the flag leaves the URL.
  const autoSynced = useRef(false)
  useEffect(() => {
    if (autoSynced.current || !connector || engineRestarting || !canWrite) return
    if (new URLSearchParams(window.location.search).get("sync") !== "1") return
    autoSynced.current = true
    window.history.replaceState(null, "", window.location.pathname)
    const t = window.setTimeout(() => { void handleSyncNow() }, 0)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connector, engineRestarting, canWrite])

  // One check per lake table, the newest: `orders` (before 2.5) and `public.orders`
  // are the same table, and an old check under the old name is not current.
  const latestQuality: QualityCheck[] = []
  {
    const seen = new Set<string>()
    for (const c of qualityChecks) {
      const key = c.table_key ?? c.source_table
      if (!seen.has(key)) { seen.add(key); latestQuality.push(c) }
    }
  }

  const markExpectedNulls = async (table: string, column: string, expected: boolean) => {
    try {
      const res = await fetch(`/api/connectors/${id}/tables/${encodeURIComponent(table)}/expected-nulls`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ column, expected }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        toast(typeof d?.detail === "string" ? d.detail : `Could not update ${column} (HTTP ${res.status})`, "error")
        return
      }
      toast(expected ? `${column}: no more null warnings` : `${column}: warns again`, "success")
      void fetchQuality()
    } catch (e) {
      toast(e instanceof Error ? e.message : `Could not update ${column}`, "error")
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
    } catch (err) { setSaveMessage({ ok: false, text: err instanceof Error ? err.message : "Failed" }) }
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
        body: JSON.stringify({ connector_type: editConnectorType, config: merged, connection_id: id }),
      })
      const data = await res.json().catch(() => ({}))
      // A refused or failed request has no success/message: say what the server said.
      setTestResult(res.ok
        ? { success: Boolean(data.success), message: data.message ?? "" }
        : { success: false, message: typeof data.detail === "string" ? data.detail : `Test could not run (HTTP ${res.status})` })
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
      setSaveMessage({ ok: true, text: "Connection saved." }); setEditing(false)
      await fetchConnector()
    } catch (err) { setSaveMessage({ ok: false, text: err instanceof Error ? err.message : "Save failed." }) }
    finally { setSaving(false) }
  }

  const handleDeleteOrphan = async (job: OrphanJob) => {
    if (!(await confirmDialog({
      title: `Delete the job for ${job.source_table}?`,
      message: "The source no longer lists this table, so the job never runs. The lake table it wrote stays.",
      confirmText: "Delete job", destructive: true,
    }))) return
    try {
      const res = await fetch(`/api/connectors/${id}/jobs/${encodeURIComponent(job.source_table)}`, { method: "DELETE" })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { toast(typeof data.detail === "string" ? data.detail : `Could not delete (HTTP ${res.status})`, "error"); return }
      setOrphaned(prev => prev.filter(j => j.source_table !== job.source_table))
      toast(`Job for ${job.source_table} deleted`, "success")
    } catch (e) { toast(e instanceof Error ? e.message : "Could not delete", "error") }
  }

  const handleTableToggle = async (tableName: string, enabled: boolean) => {
    setTogglingTable(tableName)
    try {
      const r = await fetch(`/api/connectors/${id}/tables/${encodeURIComponent(tableName)}/enabled`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      })
      if (!r.ok) { toast(`Could not ${enabled ? "include" : "exclude"} ${tableName} (HTTP ${r.status})`, "error"); return }
      setTables(prev => prev.map(t => t.name === tableName ? { ...t, enabled } : t))
    } finally { setTogglingTable(null) }
  }

  const handleDelete = async () => {
    if (!(await confirmDialog({
      title: "Delete connector",
      message: "Permanently remove this connector and its sync configuration? This can't be undone.",
      confirmText: "Delete",
      destructive: true,
    }))) return
    setDeleting(true)
    try {
      const res = await fetch(`/api/connectors/${id}`, { method: "DELETE" })
      if (!res.ok) throw new Error(`Delete failed (HTTP ${res.status})`)
      router.push("/connectors")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete.")
      setDeleting(false)
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

  // Rows per table from the newest session that synced it (lib/sync-table-rows.ts)
  const latestTableRows = latestRowsByTable(sessions)

  // Ingestion metadata the old wizard stored in config is not a connection setting.
  // Secrets arrive masked from /config and show as "Stored encrypted" (configRows).
  const INGESTION_META = ["sync_frequency", "sync_mode", "selected_tables", "schedule"]
  const previewEntries = Object.entries(configPreview).filter(([k]) => !INGESTION_META.includes(k))

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
    ? loadedAt - new Date(toUTC(connector.last_sync_at)).getTime() : null
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
        <Button variant="ghost" size="icon" aria-label="Back to connectors" render={<Link href="/connectors" />}><ChevronLeft className="h-4 w-4" /></Button>
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
    <div className="mx-auto max-w-7xl space-y-4 px-6 py-6">

      <Link href="/connectors" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ChevronLeft className="h-3.5 w-3.5" />Sources
      </Link>
      {/* Header: name and state on the left; one primary action, the rest in a menu.
          It was seven equal-weight buttons in a row, Delete among them. */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-2xl font-bold tracking-tight">{connector.name}</h2>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
            <span className="capitalize">{connector.connector_type.replace(/_/g, " ")}</span>
            {connector.catalog && <><span>·</span><span>queryable as <code className="font-mono text-xs">{connector.catalog}</code></span></>}
            <span>·</span>
            <span className={connector.status === "error" ? "text-destructive" : connector.status === "paused" ? "" : "text-[var(--dp-good-text)]"}>{({ active: "Active", paused: "Paused", error: "Error", pending: "Pending" } as Record<string, string>)[connector.status] ?? connector.status}</span>
            {(() => {
              const check = describeCheck(connector.last_checked_at, loadedAt)
              return <span className={check.stale ? "text-[var(--dp-warn-text)]" : ""}>· {check.text}</span>
            })()}
          </p>
          {connector.last_check_message && (
            <p className={`mt-1 break-words text-xs ${connector.status === "error" ? "text-destructive" : "text-muted-foreground"}`}>
              {connector.last_check_message}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {connector.catalog ? (
            <Button variant="outline" size="sm" render={<Link href={`/query?catalog=${encodeURIComponent(connector.catalog)}`} />}>Query in Analytics</Button>
          ) : catalogEnabled && (
            <Button variant="outline" size="sm" render={<Link href="/catalog" />}>Open Catalog</Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="outline" size="sm" aria-label="More actions for this source" />}>
              More ▾
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={handleCheck} disabled={checking}>
                <PlugZap className="mr-2 h-3.5 w-3.5" />{checking ? "Checking…" : "Check connection"}
              </DropdownMenuItem>
              {canWrite && (
                <>
                  <DropdownMenuItem onClick={startEdit} disabled={editing}><Pencil className="mr-2 h-3.5 w-3.5" />Edit connection</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => void handlePauseToggle()} disabled={pausing}>
                    {connector.status === "paused"
                      ? <><Play className="mr-2 h-3.5 w-3.5" />Resume</>
                      : <><Pause className="mr-2 h-3.5 w-3.5" />Pause (not in use)</>}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem className="text-destructive" onClick={handleDelete} disabled={deleting}>
                    <Trash2 className="mr-2 h-3.5 w-3.5" />{deleting ? "Deleting…" : "Delete source"}
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
          {canWrite && (
            <Button size="sm" onClick={handleSyncNow} disabled={syncing || engineRestarting}
              title={engineRestarting ? "The query engine is restarting; Sync is available when it is back." : undefined}>
              <RefreshCw className={`mr-1.5 h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
              {syncing ? "Syncing…" : "Sync now"}
            </Button>
          )}
        </div>
      </div>

      {/* The query engine, for a Trino-backed source: restarting (after create/edit) or
          not ready. Polls once on load, and on while a restart is reported. */}
      <EngineRestartBanner
        active={!!connector && isTrinoEngine(connector.connector_type)}
        onStatus={(s) => setEngineRestarting(!!s?.restarting)}
      />

      {/* Feedback */}
      {syncedOk && catalogEnabled && (
        <div className="flex items-center gap-2 rounded-md bg-[var(--dp-good)]/10 border border-[var(--dp-good)]/20 px-3 py-2 text-sm text-[var(--dp-good-text)]">
          <Check className="h-4 w-4 shrink-0" />
          <span className="flex-1">Sync complete — your data is ready to explore.</span>
          <Button size="sm" variant="outline" className="h-7" render={<Link href="/catalog" />}>
            <Database className="h-3.5 w-3.5 mr-1.5" />View in Catalog
          </Button>
          <button
            aria-label="Dismiss"
            onClick={() => setSyncedOk(false)}
            className="text-[var(--dp-good-text)]/70 hover:text-[var(--dp-good-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
      {saveMessage && (
        <div role={saveMessage.ok ? "status" : "alert"} className={`text-sm px-1 ${saveMessage.ok ? "text-[var(--dp-good-text)]" : "text-destructive"}`}>
          {saveMessage.text}
        </div>
      )}

      <div className="flex flex-wrap items-start gap-5">
      <div className="min-w-0 flex-[3_1_560px] space-y-4">
      {/* ── Tables first: they are what this source is for ── */}
      <TablesCard
        refetch={readsEverythingEachSync(connector.connector_type)}
        tables={tables}
        latestTableRows={latestTableRows}
        togglingTable={togglingTable}
        onToggle={handleTableToggle}
        selected={selectedTable}
        onSelect={setSelectedTable}
        canEdit={canWrite}
        defaultLake={defaultLake}
        lakes={lakes}
        orphaned={orphaned}
        onDeleteOrphan={handleDeleteOrphan}
      />

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
              <div className="space-y-1">
                {/* By the form's own labels and order (it showed raw keys, "Auth value"
                    style, and a whole Python program on one truncated line). */}
                {configRows(connector.connector_type, Object.fromEntries(previewEntries)).map(row => (
                  <div key={row.key} className="flex items-baseline justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-muted/30">
                    <span className="min-w-0 text-xs text-muted-foreground">{row.label}</span>
                    <span className={`max-w-[60%] truncate text-right text-xs ${row.mono ? "font-mono" : ""} ${row.muted ? "text-muted-foreground" : "text-foreground"}`}
                          title={row.value}>
                      {row.value}
                    </span>
                  </div>
                ))}
                {previewEntries.length === 0 && (
                  <p className="text-muted-foreground text-xs text-center py-4">No configuration preview available.</p>
                )}
                {canWrite && (
                <div className="pt-2 border-t mt-2">
                  <button
                    type="button"
                    onClick={startEdit}
                    className="w-full text-xs text-muted-foreground hover:text-foreground flex items-center justify-center gap-1.5 py-1.5 rounded-md hover:bg-muted/30 transition-colors"
                  >
                    <Pencil className="h-3 w-3" />Edit connection settings
                  </button>
                </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Schedule */}
        <ScheduleCard
          key={schedule ?? "off"}
          schedule={schedule}
          info={scheduleInfo}
          savingSchedule={savingSchedule}
          scheduleMsg={scheduleMsg}
          onSave={handleSaveSchedule}
          schedulerEnabled={schedulerEnabled}
          canEdit={canWrite}
        />
      </div>{/* end 2-col grid */}

      {/* ── Access: who can reach this source (D2/D3) ──
           Above Tables deliberately: "whose source is this, and who else can touch
           it" is a question about the connector itself, not about one sync run. */}
      <SourceAccessPanel kind="connectors" id={id} />

      {/* ── Sync History: run results (effect) ── */}
      {(liveSession || sessions.length > 0) && (
        <SyncHistory sessions={allSessions} connectionId={id} onChanged={() => { fetchHistory(); fetchConnector() }} />
      )}

      {/* ── Data Quality ── */}
      {qualityChecks.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold">Data Quality</h3>
                {latestQuality.some(c => c.overall_status === "alert") && (
                  <span className="text-2xs px-1.5 py-0.5 rounded bg-destructive/10 text-destructive font-medium">Alert</span>
                )}
                {!latestQuality.some(c => c.overall_status === "alert") &&
                  latestQuality.some(c => c.overall_status === "warning") && (
                  <span className="text-2xs px-1.5 py-0.5 rounded bg-[var(--dp-warn)]/10 text-[var(--dp-warn-text)] font-medium">Warning</span>
                )}
              </div>
              <button onClick={fetchQuality} aria-label="Refresh data quality checks" className="text-2xs text-muted-foreground hover:text-foreground focus-visible:text-foreground focus-visible:outline-none focus-visible:underline">Refresh</button>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {/* Group by table, show latest check per table */}
            {(() => {
              // One row per lake table: checks written as `orders` (before 2.5) and
              // `public.orders` are the same table, and only the newest one counts.
              return latestQuality.map(check => [check.source_table, check] as const).map(([table, check]) => (
                <div key={table} className="border-t px-4 py-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-xs font-medium">{table}</span>
                    <div className="flex items-center gap-2">
                      <span className={`text-2xs px-1.5 py-0.5 rounded font-medium ${
                        check.overall_status === "ok" ? "bg-[var(--dp-good)]/10 text-[var(--dp-good-text)]" :
                        check.overall_status === "alert" ? "bg-destructive/10 text-destructive" :
                        "bg-[var(--dp-warn)]/10 text-[var(--dp-warn-text)]"
                      }`}>{check.overall_status}</span>
                      <span className="text-2xs text-muted-foreground">
                        {new Date(check.checked_at).toLocaleString()}
                      </span>
                    </div>
                  </div>

                  {/* Row count */}
                  <div className="flex items-center gap-4 text-xs mb-2">
                    <span className="text-muted-foreground">Rows:</span>
                    <span className="font-mono font-medium">{check.rows_current?.toLocaleString()}</span>
                    {check.row_change_pct != null && (
                      <span className={`font-mono text-2xs ${
                        check.row_change_status === "alert" ? "text-destructive" :
                        check.row_change_status === "warning" ? "text-[var(--dp-warn-text)]" :
                        "text-muted-foreground"
                      }`}>
                        {check.row_change_pct > 0 ? "+" : ""}{check.row_change_pct.toFixed(1)}% vs prev
                      </span>
                    )}
                  </div>

                  {/* Warnings */}
                  {(check.warnings ?? []).length > 0 && (
                    <div className="space-y-1 mb-2">
                      {(check.warnings ?? []).map((warning, i) => (
                        <div key={i} className={`text-2xs px-2 py-1 rounded flex items-start gap-1.5 ${
                          warning.severity === "alert" ? "bg-destructive/10 text-destructive" : "bg-[var(--dp-warn)]/10 text-[var(--dp-warn-text)]"
                        }`}>
                          <span>{warning.severity === "alert" ? "⚠" : "○"}</span>
                          <span className="flex-1">{warning.message}</span>
                          {canWrite && warning.type === "high_null_rate" && warning.column && (
                            <button type="button" className="shrink-0 underline-offset-2 hover:underline focus-visible:underline focus-visible:outline-none"
                              title="This column is often empty by design (for example a date set later). Its null rate is still recorded."
                              onClick={() => markExpectedNulls(table, warning.column!, true)}>
                              Expected — stop warning
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Null rates — only show problematic columns, capped but honest */}
                  {(() => {
                    const nullCols = Object.entries(check.null_checks || {})
                      .filter(([, value]) => value.null_rate > 0)
                      .sort(([, left], [, right]) => right.null_rate - left.null_rate)
                    const shown = nullCols.slice(0, 5)
                    const hidden = nullCols.length - shown.length
                    return (
                      <>
                        {shown.map(([col, value]) => (
                          <div key={col} className="flex items-center gap-2 mt-1">
                            <span className="font-mono text-2xs text-muted-foreground w-32 truncate">{col}</span>
                            <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full ${
                                  value.status === "alert" ? "bg-destructive" :
                                  value.status === "warning" ? "bg-[var(--dp-warn)]" :
                                  "bg-primary/40"
                                }`}
                                style={{ width: `${Math.min(value.null_rate, 100)}%` }}
                              />
                            </div>
                            <span className={`text-2xs font-mono w-10 text-right ${
                              value.status === "alert" ? "text-destructive" :
                              value.status === "warning" ? "text-[var(--dp-warn-text)]" :
                              "text-muted-foreground"
                            }`}>{value.null_rate}%</span>
                          </div>
                        ))}
                        {hidden > 0 && (
                          <p className="text-2xs text-muted-foreground mt-1.5">
                            +{hidden} more column{hidden > 1 ? "s" : ""} with nulls
                          </p>
                        )}
                        {(check.expected_null_columns ?? []).length > 0 && (
                          <p className="text-2xs text-muted-foreground mt-1.5">
                            Expected to be mostly empty:{" "}
                            {(check.expected_null_columns ?? []).map((col, i) => (
                              <span key={col}>
                                {i > 0 && ", "}
                                <span className="font-mono">{col}</span>
                                {canWrite && (
                                  <button type="button" className="ml-1 underline underline-offset-2 hover:text-foreground"
                                    onClick={() => markExpectedNulls(table, col, false)}
                                    aria-label={`Warn about ${col} again`}>warn again</button>
                                )}
                              </span>
                            ))}
                          </p>
                        )}
                      </>
                    )
                  })()}
                </div>
              ))
            })()}
          </CardContent>
        </Card>
      )}
      </div>{/* end left column */}

      {selectedTable && tables.find(t => t.name === selectedTable) ? (
        <TableSettingsPanel
          key={selectedTable}
          connId={id}
          table={tables.find(t => t.name === selectedTable) as ConnectorTable}
          lakes={lakes}
          defaultLake={defaultLake}
          canEdit={canWrite}
          refetch={readsEverythingEachSync(connector.connector_type)}
          onSaved={async () => { await fetchConnector(); setSelectedTable(null) }}
          onClose={() => setSelectedTable(null)}
        />
      ) : (
        <ExplainRail label="This source at a glance">
          <RailSection title="Last syncs">
            {recentSessions.length > 0 ? (
              <>
                <div className="mt-1 flex gap-0.5" role="img" aria-label={`Last ${recentSessions.length} syncs: ${recentSessions.filter(x => x.status === "success").length} succeeded`}>
                  {[...recentSessions].reverse().map((x, i) => (
                    <span key={i} title={x.status} className={`h-3 flex-1 rounded-sm ${x.status === "success" ? "bg-[var(--dp-good)]" : x.status === "failed" ? "bg-destructive" : "bg-muted-foreground/30"}`} />
                  ))}
                </div>
                <p className="mt-1">{successRate}% succeeded · {lastRunRows != null ? `${lastRunRows.toLocaleString()} rows last time` : "no rows yet"}</p>
              </>
            ) : "Never synced."}
          </RailSection>
          <RailSection title="Freshness">
            <span className={freshnessStale ? "text-[var(--dp-warn-text)]" : ""}>{freshnessLabel}</span>
            {connector.last_sync_at && <> · {formatDateTime(connector.last_sync_at)}</>}
          </RailSection>
          <RailSection title="Tables">
            {tables.length > 0
              ? `${tables.filter(t => t.enabled).length} of ${tables.length} synced · ${tables.filter(t => t.pii_columns?.length).length} with masked columns`
              : "None discovered yet."}
          </RailSection>
          {!readsEverythingEachSync(connector.connector_type) && tables.some(t => t.enabled && (t.sync_mode || "full") === "incremental" && !t.incremental_column) && (
            <RailAttention title="Changed-rows sync without a column">
              {tables.filter(t => t.enabled && (t.sync_mode || "full") === "incremental" && !t.incremental_column).map(t => t.name).join(", ")} read the whole table on every run.
            </RailAttention>
          )}
          {tables.length > 0 && !tables.some(t => t.pii_columns?.length) && (
            <RailAttention title="No columns masked">
              If these tables hold personal data, choose the columns to mask before loading (Edit a table).
            </RailAttention>
          )}
        </ExplainRail>
      )}
      </div>{/* end two columns */}
    </div>
  )
}
