"use client"

import { useState, use, useEffect } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Skeleton } from "@/components/ui/skeleton"
import { ConnectionForm } from "@/components/connectors/connection-form"
import { getConnector } from "@/lib/connectors"
import {
  ChevronLeft, ChevronRight, Loader2, CheckCircle2,
  Database, RefreshCw, Clock, Zap, AlertCircle, Search,
} from "lucide-react"
import Link from "next/link"

// ── Constants ──────────────────────────────────────────────────────────────────

const STEPS = [
  { id: 1, name: "Connection", description: "Configure and test source connection" },
  { id: 2, name: "Tables",     description: "Choose tables and incremental columns" },
  { id: 3, name: "Schedule",   description: "Set sync mode and frequency" },
]

const FREQUENCY_TO_CRON: Record<string, string> = {
  "15min":  "*/15 * * * *",
  hourly:   "0 * * * *",
  daily:    "0 2 * * *",
  weekly:   "0 2 * * 1",
}

// ── Types ──────────────────────────────────────────────────────────────────────

interface RemoteTable {
  name: string
  schema?: string
  row_count?: number
  columns?: { name: string; type: string; nullable: boolean }[]
}

interface TableConfig {
  enabled: boolean
  incremental_column: string   // "" = none
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function ConnectorSetupPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const connector = getConnector(id)

  // ── Step state ───────────────────────────────────────────────────────────────
  const [currentStep, setCurrentStep] = useState(1)

  // Step 1
  const [connectionName, setConnectionName] = useState(`${connector?.name || ""} Connection`)
  const [config, setConfig] = useState<Record<string, any>>(() => {
    const d: Record<string, any> = {}
    connector?.fields.forEach(f => { if (f.default !== undefined) d[f.name] = f.default })
    return d
  })
  const [testStatus, setTestStatus] = useState<"idle" | "testing" | "success" | "error">("idle")
  const [testMessage, setTestMessage] = useState("")
  const [createdId, setCreatedId] = useState<string | null>(null)

  // Step 2
  const [loadingTables, setLoadingTables] = useState(false)
  const [tables, setTables] = useState<RemoteTable[]>([])
  const [tableSearch, setTableSearch] = useState("")
  const [tableConfigs, setTableConfigs] = useState<Record<string, TableConfig>>({})

  // Step 3
  const [syncMode, setSyncMode] = useState<"full" | "incremental">("full")
  const [syncFrequency, setSyncFrequency] = useState("manual")
  const [syncImmediately, setSyncImmediately] = useState(true)  // Fix #6: opt-in
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // ── Derived ──────────────────────────────────────────────────────────────────

  const enabledTables = Object.entries(tableConfigs).filter(([, c]) => c.enabled).map(([name]) => name)
  const filteredTables = tables.filter(t => t.name.toLowerCase().includes(tableSearch.toLowerCase()))
  const hasIncrementalColumns = enabledTables.some(name => tableConfigs[name]?.incremental_column)

  // ── Handlers ──────────────────────────────────────────────────────────────────

  const handleTestConnection = async () => {
    setTestStatus("testing"); setTestMessage("")
    try {
      const res = await fetch("/api/connectors/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connector_type: id, config }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        setTestStatus("success")
        setTestMessage(data.message || "Connection successful!")
      } else {
        setTestStatus("error")
        setTestMessage(data.detail || data.message || "Connection failed")
      }
    } catch (e) {
      setTestStatus("error")
      setTestMessage(e instanceof Error ? e.message : "Connection failed")
    }
  }

  // When advancing from Step 1 → 2: create connection first, then fetch real tables
  const handleToStep2 = async () => {
    setCreating(true)
    setCreateError(null)
    try {
      // Create connection — store only pure DB connection config (no ingestion metadata)
      const { sync_frequency: _, sync_mode: __, selected_tables: ___, ...pureConfig } = config as any
      const res = await fetch("/api/connectors/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: connectionName, connector_type: id, config: pureConfig }),
      })
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || "Failed to create connection")
      }
      const created = await res.json()
      setCreatedId(created.id)

      // Fetch actual tables from the connection
      setLoadingTables(true)
      const tablesRes = await fetch(`/api/connectors/${created.id}/tables`)
      if (tablesRes.ok) {
        const data = await tablesRes.json()
        const rawTables: RemoteTable[] = (data.tables ?? []).map((t: any) =>
          typeof t === "string" ? { name: t } : { name: t.name }
        )
        setTables(rawTables)

        // Fetch schema for each table to get column info
        const schemaResults = await Promise.allSettled(
          rawTables.map(t =>
            fetch(`/api/connectors/${created.id}/schema/${t.name}`)
              .then(r => r.ok ? r.json() : null)
          )
        )
        const enriched = rawTables.map((t, i) => {
          const schema = schemaResults[i].status === "fulfilled" ? schemaResults[i].value : null
          return schema ? { ...t, columns: schema.columns } : t
        })
        setTables(enriched)

        // Default: all tables enabled, no incremental column
        const defaults: Record<string, TableConfig> = {}
        rawTables.forEach(t => { defaults[t.name] = { enabled: true, incremental_column: "" } })
        setTableConfigs(defaults)
      }
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Failed")
    } finally {
      setCreating(false)
      setLoadingTables(false)
    }
    setCurrentStep(2)
  }

  // Fix #3: Back from Step2 → discard orphan connection
  const handleBackFromStep2 = async () => {
    if (createdId) {
      try {
        await fetch(`/api/connectors/${createdId}/draft`, { method: "DELETE" })
      } catch {}
      setCreatedId(null)
      setTables([])
      setTableConfigs({})
    }
    setCurrentStep(1)
  }

  // Finalize: apply table config, schedule, sync mode
  const handleFinish = async () => {
    if (!createdId) return
    setCreating(true)
    setCreateError(null)
    try {
      // 1. Apply table enabled state + incremental columns in one pass
      await Promise.all(Object.entries(tableConfigs).map(([tbl, cfg]) =>
        fetch(`/api/connectors/${createdId}/tables/${tbl}/enabled`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enabled: cfg.enabled,
            incremental_column: cfg.incremental_column || null,
          }),
        })
      ))

      // 2. Set sync mode for all tables
      await fetch(`/api/connectors/${createdId}/sync-mode`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sync_mode: syncMode }),
      })

      // 3. Apply schedule
      const cron = FREQUENCY_TO_CRON[syncFrequency]
      if (cron) {
        await fetch(`/api/connectors/${createdId}/schedule`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ schedule: cron }),
        })
      }

      // 4. Fix #6: Trigger initial sync only if user opted in
      if (syncImmediately) {
        await fetch(`/api/connectors/${createdId}/sync`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sync_mode: syncMode }),
        })
      }

      router.push(`/connectors/connections/${createdId}`)
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Failed to finalize")
      setCreating(false)
    }
  }

  const canProceed = () => {
    if (currentStep === 1) return testStatus === "success"
    if (currentStep === 2) return enabledTables.length > 0
    return true
  }

  if (!connector) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center">
          <h2 className="text-2xl font-bold">Connector not found</h2>
          <Link href="/connectors"><Button className="mt-4">Back to Marketplace</Button></Link>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">

        {/* Header */}
        <div className="flex items-center gap-3">
          <Link href="/connectors">
            <Button variant="ghost" size="icon" className="shrink-0">
              <ChevronLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div className="min-w-0">
            <h2 className="text-xl font-bold truncate">Set up {connector.name}</h2>
            <p className="text-sm text-muted-foreground truncate">{connector.description}</p>
          </div>
        </div>

        {/* Progress Steps */}
        <div className="flex items-center">
          {STEPS.map((step, index) => (
            <div key={step.id} className="flex items-center flex-1 min-w-0">
              <div className="flex items-center gap-2 shrink-0">
                <div className={`flex h-8 w-8 items-center justify-center rounded-full border-2 text-sm font-medium shrink-0 ${
                  currentStep > step.id
                    ? "border-primary bg-primary text-primary-foreground"
                    : currentStep === step.id
                      ? "border-primary text-primary"
                      : "border-muted-foreground/30 text-muted-foreground"
                }`}>
                  {currentStep > step.id ? <CheckCircle2 className="h-4 w-4" /> : step.id}
                </div>
                <span className={`text-sm font-medium hidden sm:block ${
                  currentStep >= step.id ? "text-foreground" : "text-muted-foreground"
                }`}>{step.name}</span>
              </div>
              {index < STEPS.length - 1 && (
                <div className={`flex-1 h-0.5 mx-2 ${currentStep > step.id ? "bg-primary" : "bg-muted-foreground/20"}`} />
              )}
            </div>
          ))}
        </div>

        {/* Error banner */}
        {createError && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" />{createError}
          </div>
        )}

        {/* ── Step 1: Connection ── */}
        {currentStep === 1 && (
          <Card>
            <CardHeader className="pb-4">
              <CardTitle className="text-base">Connection Details</CardTitle>
              <CardDescription>Configure and test your data source connection</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="connection-name">Connection Name</Label>
                <Input
                  id="connection-name"
                  value={connectionName}
                  onChange={e => setConnectionName(e.target.value)}
                  placeholder="My Database Connection"
                />
              </div>
              <ConnectionForm
                fields={connector.fields}
                values={config}
                onChange={(name, value) => {
                  setConfig(prev => ({ ...prev, [name]: value }))
                  if (testStatus !== "idle") { setTestStatus("idle"); setTestMessage("") }
                }}
                onTest={handleTestConnection}
                testStatus={testStatus}
                testMessage={testMessage}
              />
            </CardContent>
          </Card>
        )}

        {/* ── Step 2: Tables ── */}
        {currentStep === 2 && (
          <Card>
            <CardHeader className="pb-4">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base">Select Tables</CardTitle>
                  <CardDescription className="mt-0.5">
                    Choose tables to sync. For Incremental mode, set the watermark column.
                  </CardDescription>
                </div>
                {tables.length > 5 && (
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                    <Input
                      value={tableSearch}
                      onChange={e => setTableSearch(e.target.value)}
                      placeholder="Filter…"
                      className="pl-8 h-8 text-xs w-36"
                    />
                  </div>
                )}
              </div>
              {tables.length > 0 && (
                <div className="flex items-center gap-3 mt-2">
                  <Badge variant="secondary" className="text-xs">
                    {enabledTables.length}/{tables.length} selected
                  </Badge>
                  <button
                    className="text-xs text-primary hover:underline"
                    onClick={() => {
                      const allEnabled = tables.every(t => tableConfigs[t.name]?.enabled)
                      setTableConfigs(prev => {
                        const next = { ...prev }
                        tables.forEach(t => { next[t.name] = { ...next[t.name], enabled: !allEnabled } })
                        return next
                      })
                    }}
                  >
                    {tables.every(t => tableConfigs[t.name]?.enabled) ? "Deselect all" : "Select all"}
                  </button>
                </div>
              )}
            </CardHeader>
            <CardContent>
              {loadingTables ? (
                <div className="space-y-2">
                  {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
                </div>
              ) : tables.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <Database className="h-8 w-8 mx-auto mb-2 opacity-30" />
                  <p className="text-sm">No tables found in this connection</p>
                </div>
              ) : (
                <div className="space-y-px">
                  {/* Header */}
                  <div className="grid grid-cols-[auto_1fr_1fr] gap-3 px-3 pb-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground border-b">
                    <span className="w-8">Sync</span>
                    <span>Table</span>
                    <span>Incremental Column <span className="normal-case font-normal">(optional)</span></span>
                  </div>

                  {filteredTables.map(table => {
                    const cfg = tableConfigs[table.name] ?? { enabled: true, incremental_column: "" }
                    const tsColumns = table.columns?.filter(c =>
                      c.type.toLowerCase().includes("timestamp") ||
                      c.type.toLowerCase().includes("date") ||
                      c.name.includes("updated_at") ||
                      c.name.includes("created_at") ||
                      c.name.includes("modified")
                    ) ?? []
                    const allColumns = table.columns ?? []

                    return (
                      <div key={table.name}
                        className={`grid grid-cols-[auto_1fr_1fr] gap-3 items-center px-3 py-2.5 rounded transition-colors ${
                          cfg.enabled ? "hover:bg-muted/30" : "opacity-40"
                        }`}>
                        {/* Toggle */}
                        <div className="w-8">
                          <Switch
                            checked={cfg.enabled}
                            onCheckedChange={v => setTableConfigs(prev => ({
                              ...prev, [table.name]: { ...prev[table.name], enabled: v }
                            }))}
                            className="scale-75"
                          />
                        </div>

                        {/* Table name + row count */}
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <Database className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                            <span className="font-mono text-xs font-medium truncate">{table.name}</span>
                          </div>
                          {table.columns && (
                            <p className="text-[10px] text-muted-foreground ml-5">
                              {table.columns.length} columns
                            </p>
                          )}
                        </div>

                        {/* Incremental column selector */}
                        {cfg.enabled ? (
                          <Select
                            value={cfg.incremental_column || "__none__"}
                            onValueChange={v => setTableConfigs(prev => ({
                              ...prev, [table.name]: { ...prev[table.name], incremental_column: (v === "__none__" ? "" : (v ?? "")) }
                            }))}
                          >
                            <SelectTrigger className="h-7 text-xs">
                              <SelectValue placeholder="None (full sync)" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="__none__" className="text-xs text-muted-foreground">
                                None (full sync)
                              </SelectItem>
                              {/* Recommended columns first */}
                              {tsColumns.length > 0 && (
                                <>
                                  <div className="px-2 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
                                    Recommended
                                  </div>
                                  {tsColumns.map(c => (
                                    <SelectItem key={c.name} value={c.name} className="text-xs">
                                      {c.name}
                                      <span className="ml-1 text-muted-foreground font-mono text-[10px]">{c.type}</span>
                                    </SelectItem>
                                  ))}
                                </>
                              )}
                              {/* All other columns */}
                              {allColumns.filter(c => !tsColumns.find(t => t.name === c.name)).length > 0 && (
                                <>
                                  <div className="px-2 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
                                    All columns
                                  </div>
                                  {allColumns.filter(c => !tsColumns.find(t => t.name === c.name)).map(c => (
                                    <SelectItem key={c.name} value={c.name} className="text-xs">
                                      {c.name}
                                      <span className="ml-1 text-muted-foreground font-mono text-[10px]">{c.type}</span>
                                    </SelectItem>
                                  ))}
                                </>
                              )}
                            </SelectContent>
                          </Select>
                        ) : (
                          <span className="text-[10px] text-muted-foreground/50">skipped</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* ── Step 3: Schedule ── */}
        {currentStep === 3 && (
          <Card>
            <CardHeader className="pb-4">
              <CardTitle className="text-base">Sync Configuration</CardTitle>
              <CardDescription>Set how and when data is synced to Iceberg</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* Sync Mode */}
              <div className="space-y-3">
                <Label className="text-xs text-muted-foreground uppercase tracking-wide">Sync Mode</Label>
                <div className="grid gap-2 sm:grid-cols-2">
                  {[
                    {
                      value: "full",
                      icon: RefreshCw,
                      label: "Full Refresh",
                      desc: "Replace all data on every sync. Simple and reliable.",
                      note: "",
                    },
                    {
                      value: "incremental",
                      icon: Zap,
                      label: "Incremental",
                      desc: "Only sync new or changed records since last run.",
                      note: hasIncrementalColumns
                        ? `${Object.values(tableConfigs).filter(c => c.enabled && c.incremental_column).length} tables configured`
                        : "No watermark columns set in Step 2",
                      noteColor: hasIncrementalColumns ? "text-green-600" : "text-amber-500",
                    },
                  ].map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => setSyncMode(opt.value as "full" | "incremental")}
                      className={`text-left p-4 rounded-lg border-2 transition-colors ${
                        syncMode === opt.value
                          ? "border-primary bg-primary/5"
                          : "border-border hover:border-muted-foreground/40"
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1.5">
                        <opt.icon className={`h-4 w-4 ${syncMode === opt.value ? "text-primary" : "text-muted-foreground"}`} />
                        <span className="text-sm font-medium">{opt.label}</span>
                        {syncMode === opt.value && <CheckCircle2 className="h-3.5 w-3.5 text-primary ml-auto" />}
                      </div>
                      <p className="text-xs text-muted-foreground">{opt.desc}</p>
                      {opt.note && <p className={`text-[10px] mt-1 font-medium ${opt.noteColor}`}>{opt.note}</p>}
                    </button>
                  ))}
                </div>
                {syncMode === "incremental" && !hasIncrementalColumns && (
                  <div className="flex items-start gap-2 rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700">
                    <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    No watermark columns were set in Step 2. Incremental sync will behave like Full Refresh until columns are configured.
                  </div>
                )}
              </div>

              <Separator />

              {/* Schedule */}
              <div className="space-y-3">
                <Label className="text-xs text-muted-foreground uppercase tracking-wide">Schedule</Label>
                <div className="grid gap-2 sm:grid-cols-2">
                  {[
                    { value: "manual",  icon: Clock,     label: "Manual",         cron: "",              desc: "Trigger syncs manually" },
                    { value: "15min",   icon: Zap,       label: "Every 15 min",   cron: "*/15 * * * *",  desc: "Near real-time updates" },
                    { value: "hourly",  icon: Clock,     label: "Hourly",         cron: "0 * * * *",     desc: "Fresh data every hour" },
                    { value: "daily",   icon: Clock,     label: "Daily at 2am",   cron: "0 2 * * *",     desc: "Recommended for batch" },
                    { value: "weekly",  icon: Clock,     label: "Weekly",         cron: "0 2 * * 1",     desc: "Low-frequency sources" },
                  ].map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => setSyncFrequency(opt.value)}
                      className={`text-left px-3 py-2.5 rounded-lg border transition-colors ${
                        syncFrequency === opt.value
                          ? "border-primary bg-primary/5 text-primary"
                          : "border-border hover:border-muted-foreground/40"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium">{opt.label}</span>
                        {opt.cron && <span className="font-mono text-[10px] text-muted-foreground">{opt.cron}</span>}
                      </div>
                      <p className="text-[11px] text-muted-foreground mt-0.5">{opt.desc}</p>
                    </button>
                  ))}
                </div>
                {syncFrequency !== "manual" && (
                  <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                    <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
                    Airflow DAG will be created automatically
                  </p>
                )}
              </div>

              <Separator />

              {/* Summary */}
              <div className="rounded-lg border bg-muted/30 p-4 space-y-2 text-sm">
                <p className="font-medium text-xs uppercase tracking-wide text-muted-foreground mb-3">Summary</p>
                {[
                  ["Connection",  connectionName],
                  ["Connector",   connector.name],
                  ["Tables",      `${enabledTables.length} of ${tables.length} selected`],
                  ["With watermark", `${Object.values(tableConfigs).filter(c => c.enabled && c.incremental_column).length} tables`],
                  ["Sync Mode",   syncMode === "full" ? "Full Refresh" : "Incremental"],
                  ["Schedule",    syncFrequency === "manual" ? "Manual" : `${syncFrequency} (${FREQUENCY_TO_CRON[syncFrequency]})`],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between">
                    <span className="text-muted-foreground">{label}</span>
                    <span className="font-medium">{value}</span>
                  </div>
                ))}
              </div>

              {/* Fix #6: Sync immediately option */}
              <div className="flex items-center gap-2 pt-1">
                <Switch
                  checked={syncImmediately}
                  onCheckedChange={setSyncImmediately}
                  id="sync-now"
                />
                <label htmlFor="sync-now" className="text-sm cursor-pointer">
                  Sync immediately after creation
                </label>
                <span className="text-xs text-muted-foreground">
                  {syncImmediately ? "First sync will run now" : "Sync manually or wait for schedule"}
                </span>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Navigation */}
        <div className="flex items-center justify-between">
          {/* Fix #3: Back from step2 discards orphan connection */}
          <Button
            variant="outline" size="sm"
            onClick={currentStep === 2 ? handleBackFromStep2 : () => setCurrentStep(p => p - 1)}
            disabled={currentStep === 1 || creating}
          >
            <ChevronLeft className="h-4 w-4 mr-1" />Back
          </Button>

          <span className="text-xs text-muted-foreground sm:hidden">{currentStep} / {STEPS.length}</span>

          {currentStep === 1 ? (
            <Button size="sm" onClick={handleToStep2} disabled={!canProceed() || creating}>
              {creating ? <><Loader2 className="h-4 w-4 mr-1.5 animate-spin" />Creating…</> : <>Next<ChevronRight className="h-4 w-4 ml-1" /></>}
            </Button>
          ) : currentStep === 2 ? (
            <Button size="sm" onClick={() => setCurrentStep(3)} disabled={!canProceed()}>
              Next<ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          ) : (
            <Button size="sm" onClick={handleFinish} disabled={creating}>
              {creating
                ? <><Loader2 className="h-4 w-4 mr-1.5 animate-spin" />Finishing…</>
                : <><CheckCircle2 className="h-4 w-4 mr-1.5" />Create & Start Sync</>}
            </Button>
          )}
        </div>

      </div>
    </div>
  )
}
