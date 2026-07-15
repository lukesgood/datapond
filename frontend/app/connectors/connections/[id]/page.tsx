"use client"

import { use, useEffect, useState, useRef } from "react"
import { useToast } from "@/lib/toast"
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
import Link from "next/link"
import { ConnectionForm } from "@/components/connectors/connection-form"
import { getConnector } from "@/lib/connectors"
import { FREQ_OPTIONS, HOUR_OPTIONS, parseCron, cronToFreqHour, nextRun } from "@/lib/schedule"
import { useCapability } from "@/lib/capabilities"

// ── Tables Card (full-width, searchable) ──────────────────────────────────────
function TablesCard({
  tables, latestTableRows, togglingTable, onToggle, connId, onSaved, streamingEnabled,
}: {
  tables: { name: string; enabled: boolean; sync_mode?: string; incremental_column?: string | null; last_value?: string | null; effective_mode?: string; partition_spec?: {column:string;transform:string}[] | null; key_columns?: string[] | null; pii_columns?: string[] | null }[]
  latestTableRows: Map<string, number>
  togglingTable: string | null
  onToggle: (name: string, enabled: boolean) => void
  connId: string
  onSaved?: () => void | Promise<void>
  streamingEnabled: boolean
}) {
  const [search, setSearch]             = useState("")
  const [editingTable, setEditingTable] = useState<string | null>(null)
  const [editMode, setEditMode]         = useState("full")
  const [editIncCol, setEditIncCol]     = useState("")
  const [editKeyCols, setEditKeyCols]   = useState("")   // comma-separated PK (incremental upsert)
  const [editPiiCols, setEditPiiCols]   = useState("")   // comma-separated masking columns (* = all)
  // Partition: editPartCol "" = Auto (inferred), "__none__" = unpartitioned, other = column name
  const [editPartCol, setEditPartCol]   = useState("")
  const [editPartTransform, setEditPartTransform] = useState("day")
  const [saving, setSaving]             = useState(false)
  const [schemaColumns, setSchemaColumns] = useState<{name:string;type:string}[]>([])
  const [loadingSchema, setLoadingSchema] = useState(false)

  const filtered = tables.filter(t =>
    t.name.toLowerCase().includes(search.toLowerCase())
  )
  const enabledCount = tables.filter(t => t.enabled).length

  const startEdit = async (t: typeof tables[0]) => {
    setEditingTable(t.name)
    setEditMode(t.sync_mode || "full")
    setEditIncCol(t.incremental_column || "")
    setEditKeyCols((t.key_columns || []).join(", "))
    setEditPiiCols((t.pii_columns || []).join(", "))
    // Partition init: null/undefined = Auto, [] = None, [{...}] = first field
    const ps = t.partition_spec
    if (ps == null)            { setEditPartCol(""); setEditPartTransform("day") }
    else if (ps.length === 0)  { setEditPartCol("__none__"); setEditPartTransform("day") }
    else                       { setEditPartCol(ps[0].column); setEditPartTransform(ps[0].transform || "day") }
    setSchemaColumns([])
    // Load column list for watermark dropdown
    setLoadingSchema(true)
    try {
      const res = await fetch(`/api/connectors/${connId}/schema/${t.name}`)
      if (res.ok) {
        const d = await res.json()
        setSchemaColumns((d.columns || []).map((c: any) => ({ name: c.name, type: c.type })))
      }
    } catch {}
    finally { setLoadingSchema(false) }
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
          key_columns: editKeyCols.split(",").map(s => s.trim()).filter(Boolean),
          pii_columns: editPiiCols.split(",").map(s => s.trim()).filter(Boolean),
        }),
      })
      await fetch(`/api/connectors/${connId}/sync-mode`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sync_mode: editMode, table_name: editingTable }),
      })
      // Save partition spec: Auto→null, None→[], Column→[{column,transform}]
      const partitionSpec =
        editPartCol === ""        ? null :
        editPartCol === "__none__" ? [] :
        [{ column: editPartCol, transform: editPartTransform }]
      await fetch(`/api/connectors/${connId}/tables/${editingTable}/partition`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ partition_spec: partitionSpec }),
      })
      // Refetch in place instead of a full page reload (no flash / state loss)
      await onSaved?.()
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
                const mode = table.sync_mode || "full"
                const incCol = table.incremental_column
                const lastVal = (table as any).last_value
                const effectiveMode = (table as any).effective_mode || mode
                const isEditing = editingTable === table.name
                // Fix #1: incremental set but no column → warn
                const incMisconfigured = mode === "incremental" && !incCol

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
                            <span className="text-[10px] text-primary/70 font-mono block truncate">
                              ↑ {incCol}{lastVal ? ` · last: ${String(lastVal).slice(0,16)}` : " · no watermark yet"}
                            </span>
                          )}
                          {incMisconfigured && (
                            <span className="text-[10px] text-[var(--dp-warn)] block">⚠ no watermark column</span>
                          )}
                          {table.partition_spec && table.partition_spec.length > 0 && (
                            <span className="text-[10px] text-muted-foreground/70 font-mono block truncate">
                              ⊞ {table.partition_spec.map(p => `${p.transform}(${p.column})`).join(", ")}
                            </span>
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
                          incMisconfigured       ? "bg-[var(--dp-warn)]/10 text-[var(--dp-warn)] border-[var(--dp-warn)]/20" :
                          mode === "incremental" ? "bg-primary/10 text-primary border-primary/20" :
                          "bg-muted text-muted-foreground border-transparent"
                        }`}>
                          {incMisconfigured ? "⚠ incremental" : mode}
                          {incCol && !incMisconfigured ? ` · ${incCol}` : ""}
                        </span>
                      </button>
                      <div className="w-20 flex items-center justify-end gap-1">
                        {table.enabled ? (
                          <button
                            onClick={() => isEditing ? setEditingTable(null) : startEdit(table)}
                            className="text-[10px] text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity">
                            {isEditing ? "Cancel" : "Edit"}
                          </button>
                        ) : (
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
                                <SelectItem value="full" className="text-xs">Full Refresh</SelectItem>
                                <SelectItem value="incremental" className="text-xs">Incremental</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="space-y-1">
                            <label className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                              Watermark Column
                              {editMode !== "incremental" && <span className="ml-1 font-normal normal-case">(incremental only)</span>}
                            </label>
                            {schemaColumns.length > 0 && editMode === "incremental" ? (
                              <Select
                                value={editIncCol || "__none__"}
                                onValueChange={v => setEditIncCol(v === "__none__" ? "" : (v ?? ""))}
                              >
                                <SelectTrigger className="h-7 text-xs">
                                  <SelectValue placeholder="Select column…" />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="__none__" className="text-xs text-muted-foreground">None</SelectItem>
                                  {/* Recommended: timestamp/date columns first */}
                                  {schemaColumns.filter(c =>
                                    c.type.toLowerCase().includes("timestamp") ||
                                    c.type.toLowerCase().includes("date") ||
                                    c.name.includes("updated_at") || c.name.includes("created_at") || c.name.includes("modified")
                                  ).length > 0 && (
                                    <>
                                      <div className="px-2 py-1 text-[10px] text-muted-foreground uppercase tracking-wide font-medium">Recommended</div>
                                      {schemaColumns.filter(c =>
                                        c.type.toLowerCase().includes("timestamp") || c.type.toLowerCase().includes("date") ||
                                        c.name.includes("updated_at") || c.name.includes("created_at") || c.name.includes("modified")
                                      ).map(c => (
                                        <SelectItem key={c.name} value={c.name} className="text-xs">
                                          {c.name} <span className="text-muted-foreground font-mono ml-1">{c.type}</span>
                                        </SelectItem>
                                      ))}
                                      <div className="px-2 py-1 text-[10px] text-muted-foreground uppercase tracking-wide font-medium">All Columns</div>
                                    </>
                                  )}
                                  {schemaColumns.filter(c =>
                                    !c.type.toLowerCase().includes("timestamp") && !c.type.toLowerCase().includes("date") &&
                                    !c.name.includes("updated_at") && !c.name.includes("created_at") && !c.name.includes("modified")
                                  ).map(c => (
                                    <SelectItem key={c.name} value={c.name} className="text-xs">
                                      {c.name} <span className="text-muted-foreground font-mono ml-1">{c.type}</span>
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            ) : (
                              <Input
                                value={editIncCol}
                                onChange={e => setEditIncCol(e.target.value)}
                                placeholder={
                                  editMode !== "incremental" ? "—" :
                                  loadingSchema ? "Loading columns…" : "e.g. updated_at"
                                }
                                disabled={editMode !== "incremental" || loadingSchema}
                                className="h-7 text-xs font-mono"
                              />
                            )}
                          </div>
                        </div>
                        {editMode === "incremental" && !editIncCol && (
                          <p className="text-[10px] text-[var(--dp-warn)] flex items-center gap-1">
                            ⚠ No watermark column set — incremental will load all rows on first run
                          </p>
                        )}
                        {/* Incremental upsert PK — when set, merges instead of appending (updates changed rows, prevents duplicates) */}
                        <div className="space-y-1 pt-1">
                          <label className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                            Key Columns (upsert PK)
                            {editMode !== "incremental" && <span className="ml-1 font-normal normal-case">(incremental only)</span>}
                          </label>
                          <Input
                            value={editKeyCols}
                            onChange={e => setEditKeyCols(e.target.value)}
                            placeholder={editMode !== "incremental" ? "—" : "e.g. id  (leave blank to append)"}
                            disabled={editMode !== "incremental"}
                            className="h-7 text-xs font-mono"
                          />
                          {editMode === "incremental" && editKeyCols.trim() && (
                            <p className="text-[10px] text-[var(--dp-good)]">merge by [{editKeyCols.split(",").map(s=>s.trim()).filter(Boolean).join(", ")}] — updates changed rows, prevents duplicates</p>
                          )}
                        </div>
                        {/* PII masking — masks sensitive columns before load (sovereignty/compliance). Applies to all sync modes */}
                        <div className="space-y-1 pt-1 border-t">
                          <label className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                            PII Masking Columns
                          </label>
                          <Input
                            value={editPiiCols}
                            onChange={e => setEditPiiCols(e.target.value)}
                            placeholder="e.g. email, phone  ·  * = all string columns  (leave blank to disable)"
                            className="h-7 text-xs font-mono"
                          />
                          {editPiiCols.trim() && (
                            <p className="text-[10px] text-[var(--dp-good)]">
                              Masked before load: {editPiiCols.trim() === "*" ? "all string columns" : `[${editPiiCols.split(",").map(s=>s.trim()).filter(Boolean).join(", ")}]`} (SSN/phone/card/email, etc.)
                            </p>
                          )}
                        </div>
                        {/* Partitioning (Iceberg) */}
                        <div className="grid grid-cols-2 gap-3 pt-1 border-t">
                          <div className="space-y-1">
                            <label className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Partition Column</label>
                            <Select value={editPartCol || "__auto__"} onValueChange={v => setEditPartCol(v === "__auto__" ? "" : (v ?? ""))}>
                              <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="__auto__" className="text-xs">Auto (day, on timestamp column)</SelectItem>
                                <SelectItem value="__none__" className="text-xs text-muted-foreground">None (unpartitioned)</SelectItem>
                                {schemaColumns.map(c => (
                                  <SelectItem key={c.name} value={c.name} className="text-xs">
                                    {c.name} <span className="text-muted-foreground font-mono ml-1">{c.type}</span>
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="space-y-1">
                            <label className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                              Transform {(editPartCol === "" || editPartCol === "__none__") && <span className="font-normal normal-case">(when a column is selected)</span>}
                            </label>
                            <Select value={editPartTransform} onValueChange={v => setEditPartTransform(v ?? "day")}>
                              <SelectTrigger className="h-7 text-xs" disabled={editPartCol === "" || editPartCol === "__none__"}><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="day" className="text-xs">day (daily)</SelectItem>
                                <SelectItem value="month" className="text-xs">month (monthly)</SelectItem>
                                <SelectItem value="year" className="text-xs">year (yearly)</SelectItem>
                                <SelectItem value="identity" className="text-xs">identity (value as-is)</SelectItem>
                                <SelectItem value="bucket" className="text-xs">bucket (16-way hash)</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                        </div>
                        <p className="text-[10px] text-muted-foreground">
                          Partitioning applies when a new table is created. Existing tables pick it up on the next full sync (recreate).
                        </p>
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

        {/* CDC callout — only when the Streaming/RisingWave component is enabled on this profile */}
        {streamingEnabled && (
          <div className="mt-3 flex items-start gap-2 rounded-md bg-muted/40 border px-3 py-2 text-xs text-muted-foreground">
            <Zap className="h-3.5 w-3.5 shrink-0 mt-0.5 text-primary/60" />
            <span>
              Real-time CDC (Change Data Capture) is available via{" "}
              <Link href="/streaming" className="text-primary underline underline-offset-2">Streaming</Link>
              {" "}— captures every INSERT/UPDATE/DELETE with sub-second latency.
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// Schedule frequency options (user-facing)
// ── Schedule Card ─────────────────────────────────────────────────────────────
function ScheduleCard({
  schedule, savingSchedule, scheduleMsg, onSave, pipelinesEnabled,
}: {
  schedule: string | null
  savingSchedule: boolean
  scheduleMsg: string | null
  onSave: (val: string | null) => void
  pipelinesEnabled: boolean
}) {
  const { freqId: initFreq, hour: initHour } = schedule ? cronToFreqHour(schedule) : { freqId: "daily", hour: 2 }
  const [freqId, setFreqId] = useState(initFreq)
  const [hour, setHour]     = useState(initHour)

  const freq = FREQ_OPTIONS.find(f => f.id === freqId) ?? FREQ_OPTIONS[4]
  const builtCron = freq.buildCron(hour)
  const isDirty = builtCron !== schedule

  // Sync local state when schedule changes externally
  useEffect(() => {
    if (schedule) {
      const { freqId: f, hour: h } = cronToFreqHour(schedule)
      setFreqId(f); setHour(h)
    }
  }, [schedule])

  // Foundation profile: no in-process/Airflow executor runs schedules, so the
  // schedule UI would promise recurring syncs that never happen. Gate it off
  // and point users at manual "Sync Now" instead of showing a false "Next run".
  if (!pipelinesEnabled) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Calendar className="h-4 w-4" />Schedule
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded-lg bg-muted/30 border border-dashed px-3 py-2.5 text-xs text-muted-foreground text-center">
            Scheduled sync requires the Airflow pipelines component (not enabled
            on this profile). Trigger syncs manually with <strong>Sync Now</strong>.
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
            disabled={savingSchedule}
            onCheckedChange={checked => onSave(checked ? builtCron : null)}
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* Status */}
        {schedule ? (
          <div className="flex items-center gap-2 rounded-lg bg-[var(--dp-good)]/10 border border-[var(--dp-good)]/20 px-3 py-2">
            <Zap className="h-4 w-4 text-[var(--dp-good)] shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-[var(--dp-good)]">{parseCron(schedule)}</p>
              {nextRun(schedule) && (
                <p className="text-xs text-[var(--dp-good)]/70 flex items-center gap-1 mt-0.5">
                  <Clock className="h-3 w-3" />Next run {nextRun(schedule)}
                </p>
              )}
            </div>
          </div>
        ) : (
          <div className="rounded-lg bg-muted/30 border border-dashed px-3 py-2.5 text-xs text-muted-foreground text-center">
            Off — sync manually with <strong>Sync Now</strong>
          </div>
        )}

        {/* Frequency selector */}
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">How often</Label>
          <Select value={freqId} onValueChange={v => v && setFreqId(v)}>
            <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
            <SelectContent>
              {FREQ_OPTIONS.map(f => (
                <SelectItem key={f.id} value={f.id}>{f.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Time selector — only shown for daily/weekly/monthly */}
        {freq.hasTime && (
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Start time</Label>
            <Select value={String(hour)} onValueChange={v => v && setHour(parseInt(v))}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent>
                {HOUR_OPTIONS.map(o => (
                  <SelectItem key={o.value} value={String(o.value)}>{o.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Apply button */}
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

        {scheduleMsg && (
          <p className={`text-xs flex items-center gap-1 ${
            scheduleMsg.toLowerCase().includes("error") || scheduleMsg.toLowerCase().includes("fail")
              ? "text-destructive" : "text-[var(--dp-good)]"
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
}

export default function ConnectionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const pipelinesEnabled = useCapability("pipelines")
  const streamingEnabled = useCapability("streaming")

  const [connector, setConnector]         = useState<Connector | null>(null)
  const [tables, setTables]               = useState<{name: string; enabled: boolean; sync_mode?: string; incremental_column?: string | null; last_value?: string | null; effective_mode?: string; partition_spec?: {column:string;transform:string}[] | null; key_columns?: string[] | null; pii_columns?: string[] | null}[]>([])
  const [togglingTable, setTogglingTable] = useState<string | null>(null)
  const [configPreview, setConfigPreview] = useState<Record<string, any>>({})
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState<string | null>(null)
  const [syncing, setSyncing]             = useState(false)
  const [deleting, setDeleting]           = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  // History sessions (past + live)
  const [sessions, setSessions]           = useState<SyncSession[]>([])
  const { toast } = useToast()
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

  // Quality
  const [qualityChecks, setQualityChecks] = useState<any[]>([])

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
      error: s.error_message ?? s.error,
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
                last_value: tb.last_value ?? null,
                effective_mode: tb.effective_mode ?? tb.sync_mode ?? "full",
                partition_spec: tb.partition_spec ?? null,
                key_columns: tb.key_columns ?? null,
                pii_columns: tb.pii_columns ?? null,
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

  const fetchQuality = async () => {
    try {
      const res = await fetch(`/api/connectors/${id}/quality?limit=30`)
      if (res.ok) {
        const data = await res.json()
        setQualityChecks(data.checks || [])
      }
    } catch { /* non-critical */ }
  }

  useEffect(() => {
    fetchConnector()
    fetchHistory()
    fetchSchedule()
    fetchQuality()
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

      const handleEvent = (eventType: string, dataStr: string) => {
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
            else toast("Sync complete — check Catalog for the ingested results", "success")
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

      // Parse SSE stream manually
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() ?? ""
        let eventType = "message"
        let dataLines: string[] = []
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
    } catch (err) {
      if (elapsedRef.current) clearInterval(elapsedRef.current)
      setLiveSession(prev => prev ? { ...prev, status: "failed", isLive: false, error: String(err) } : prev)
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
        body: JSON.stringify({ connector_type: editConnectorType, config: merged, connection_id: id }),
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

  // Filter: hide sensitive values AND ingestion metadata stored in config by old wizard
  const SENSITIVE = ["password", "secret", "key", "token"]
  const INGESTION_META = ["sync_frequency", "sync_mode", "selected_tables", "schedule"]
  const previewEntries = Object.entries(configPreview).filter(
    ([k]) =>
      !SENSITIVE.some(s => k.toLowerCase().includes(s)) &&
      !INGESTION_META.includes(k)
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
    <div className="flex-1 space-y-4 p-8 pt-6">

      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" aria-label="Back to connectors" render={<Link href="/connectors" />}><ChevronLeft className="h-4 w-4" /></Button>
        <div className="flex-1">
          <h2 className="text-3xl font-bold tracking-tight">{connector.name}</h2>
          <div className="flex items-center gap-2 mt-1">
            <Badge variant="outline" className="capitalize">{connector.connector_type}</Badge>
            <Badge variant={connector.status === "active" ? "default" : "secondary"}>{connector.status}</Badge>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" render={<Link href="/catalog" />}>
            <Database className="h-4 w-4 mr-2" />Catalog
          </Button>
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
        <div className={`text-sm px-1 ${saveMessage.includes("success") ? "text-[var(--dp-good)]" : "text-destructive"}`}>
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
        <Card className={`flex flex-col ${freshnessStale ? "border-[var(--dp-warn)]/40" : ""}`}>
          <CardHeader className="pb-2 flex-1">
            <CardDescription className="flex items-center gap-1.5"><RefreshCw className="h-3.5 w-3.5" />Data Freshness</CardDescription>
            <CardTitle className={`text-xl ${freshnessStale ? "text-[var(--dp-warn)]" : ""}`}>{freshnessLabel}</CardTitle>
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
              <div className="space-y-1">
                {previewEntries.map(([key, val]) => {
                  const isSensitive = SENSITIVE.some(s => key.toLowerCase().includes(s))
                  const displayVal = isSensitive ? "••••••••" : String(val)
                  return (
                    <div key={key} className="flex items-center justify-between py-1.5 px-2 rounded-md hover:bg-muted/30 group">
                      <span className="text-xs text-muted-foreground capitalize min-w-0 mr-3">
                        {key.replace(/_/g, " ")}
                      </span>
                      <span className={`font-mono text-xs text-right truncate max-w-[60%] ${isSensitive ? "text-muted-foreground/50" : "text-foreground"}`}>
                        {displayVal}
                      </span>
                    </div>
                  )
                })}
                {previewEntries.length === 0 && (
                  <p className="text-muted-foreground text-xs text-center py-4">No configuration preview available.</p>
                )}
                <div className="pt-2 border-t mt-2">
                  <button
                    onClick={startEdit}
                    className="w-full text-xs text-muted-foreground hover:text-foreground flex items-center justify-center gap-1.5 py-1.5 rounded-md hover:bg-muted/30 transition-colors"
                  >
                    <Pencil className="h-3 w-3" />Edit connection settings
                  </button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Schedule */}
        <ScheduleCard
          schedule={schedule}
          savingSchedule={savingSchedule}
          scheduleMsg={scheduleMsg}
          onSave={handleSaveSchedule}
          pipelinesEnabled={pipelinesEnabled}
        />
      </div>{/* end 2-col grid */}

      {/* ── Tables: defines sync scope (cause) ── */}
      <TablesCard
        tables={tables}
        latestTableRows={latestTableRows}
        togglingTable={togglingTable}
        onToggle={handleTableToggle}
        connId={id}
        onSaved={fetchConnector}
        streamingEnabled={streamingEnabled}
      />

      {/* ── Sync History: run results (effect) ── */}
      {(liveSession || sessions.length > 0) && (
        <SyncHistory sessions={allSessions} />
      )}

      {/* ── Data Quality ── */}
      {qualityChecks.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold">Data Quality</h3>
                {qualityChecks.some(c => c.overall_status === "alert") && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-destructive/10 text-destructive font-medium">Alert</span>
                )}
                {!qualityChecks.some(c => c.overall_status === "alert") &&
                  qualityChecks.some(c => c.overall_status === "warning") && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--dp-warn)]/10 text-[var(--dp-warn)] font-medium">Warning</span>
                )}
              </div>
              <button onClick={fetchQuality} className="text-[10px] text-muted-foreground hover:text-foreground">Refresh</button>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {/* Group by table, show latest check per table */}
            {(() => {
              const byTable: Record<string, any> = {}
              for (const c of qualityChecks) {
                if (!byTable[c.source_table]) byTable[c.source_table] = c
              }
              return Object.entries(byTable).map(([table, check]) => (
                <div key={table} className="border-t px-4 py-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-xs font-medium">{table}</span>
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                        check.overall_status === "ok" ? "bg-[var(--dp-good)]/10 text-[var(--dp-good)]" :
                        check.overall_status === "alert" ? "bg-destructive/10 text-destructive" :
                        "bg-[var(--dp-warn)]/10 text-[var(--dp-warn)]"
                      }`}>{check.overall_status}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {new Date(check.checked_at).toLocaleString()}
                      </span>
                    </div>
                  </div>

                  {/* Row count */}
                  <div className="flex items-center gap-4 text-xs mb-2">
                    <span className="text-muted-foreground">Rows:</span>
                    <span className="font-mono font-medium">{check.rows_current?.toLocaleString()}</span>
                    {check.row_change_pct != null && (
                      <span className={`font-mono text-[10px] ${
                        check.row_change_status === "alert" ? "text-destructive" :
                        check.row_change_status === "warning" ? "text-[var(--dp-warn)]" :
                        "text-muted-foreground"
                      }`}>
                        {check.row_change_pct > 0 ? "+" : ""}{check.row_change_pct.toFixed(1)}% vs prev
                      </span>
                    )}
                  </div>

                  {/* Warnings */}
                  {check.warnings?.length > 0 && (
                    <div className="space-y-1 mb-2">
                      {check.warnings.map((w: any, i: number) => (
                        <div key={i} className={`text-[10px] px-2 py-1 rounded flex items-start gap-1.5 ${
                          w.severity === "alert" ? "bg-destructive/10 text-destructive" : "bg-[var(--dp-warn)]/10 text-[var(--dp-warn)]"
                        }`}>
                          <span>{w.severity === "alert" ? "⚠" : "○"}</span>
                          <span>{w.message}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Null rates — only show problematic columns */}
                  {Object.entries(check.null_checks || {})
                    .filter(([, v]: [string, any]) => v.null_rate > 0)
                    .sort(([, a]: [string, any], [, b]: [string, any]) => b.null_rate - a.null_rate)
                    .slice(0, 5)
                    .map(([col, v]: [string, any]) => (
                      <div key={col} className="flex items-center gap-2 mt-1">
                        <span className="font-mono text-[10px] text-muted-foreground w-32 truncate">{col}</span>
                        <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              v.status === "alert" ? "bg-destructive" :
                              v.status === "warning" ? "bg-[var(--dp-warn)]" :
                              "bg-primary/40"
                            }`}
                            style={{ width: `${Math.min(v.null_rate, 100)}%` }}
                          />
                        </div>
                        <span className={`text-[10px] font-mono w-10 text-right ${
                          v.status === "alert" ? "text-destructive" :
                          v.status === "warning" ? "text-[var(--dp-warn)]" :
                          "text-muted-foreground"
                        }`}>{v.null_rate}%</span>
                      </div>
                    ))}
                </div>
              ))
            })()}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
