"use client"

import { useState, use } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { ChevronLeft, Loader2, Search } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { ChoiceGroup } from "@/components/ui/choice-group"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { PageHeader } from "@/components/ui/page-header"
import { ConnectionForm } from "@/components/connectors/connection-form"
import { getConnector } from "@/lib/connectors"
import { useCapability } from "@/lib/capabilities"
import { isTrinoEngine } from "@/lib/engine-restart"
import { useToast } from "@/lib/toast"
import { FREQ_OPTIONS, HOUR_OPTIONS, parseCron } from "@/lib/schedule"

interface RemoteTable { name: string; row_count?: number; columns?: { name: string; type: string; nullable: boolean }[] }
interface TableConfig { enabled: boolean; incremental_column: string }   // "" = whole table each time
type ConfigValue = string | number | boolean | null | undefined
interface TablesResponse { tables?: Array<string | RemoteTable> }
interface CreatedConnection { id: string; engine_restarting?: boolean; catalog?: string | null }

const MANUAL = "manual"

/** The catalog name the backend will give this source (connectors/trino_source.py
 *  source_slug): NFKD-folded ASCII, lowercase, runs of other characters → "_", at most
 *  32 characters. A name with no ASCII letters or digits gets a hash there instead. */
function sourceSlug(name: string): string | null {
  const folded = name.normalize("NFKD").replace(/[^\x00-\x7f]/g, "")
  const body = folded.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "")
  if (!body) return null
  return `src_${body}`.slice(0, 32).replace(/_+$/, "")
}
const isTimeLike = (c: { name: string; type: string }) =>
  /timestamp|date/i.test(c.type) || /updated_at|created_at|modified/.test(c.name)

/** Add a source on one page: connect, pick tables, choose how they stay fresh. It was
 *  a three-step wizard in a 672 px column; the steps now sit one under the other, and
 *  the right column says what will be created as the choices change. Nothing is
 *  persisted until Create, so leaving the page leaves nothing behind. */
export default function ConnectorSetupPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const connector = getConnector(id)
  const pipelinesEnabled = useCapability("pipelines")
  const { toast } = useToast()

  const [name, setName] = useState(`${connector?.name || ""} source`)
  const [config, setConfig] = useState<Record<string, ConfigValue>>(() => {
    const d: Record<string, ConfigValue> = {}
    connector?.fields.forEach(f => { if (f.default !== undefined) d[f.name] = f.default })
    return d
  })
  const [testStatus, setTestStatus] = useState<"idle" | "testing" | "success" | "error">("idle")
  const [testMessage, setTestMessage] = useState("")

  const [loadingTables, setLoadingTables] = useState(false)
  const [tablesError, setTablesError] = useState<string | null>(null)
  const [tables, setTables] = useState<RemoteTable[]>([])
  const [tableSearch, setTableSearch] = useState("")
  const [tableConfigs, setTableConfigs] = useState<Record<string, TableConfig>>({})

  const [freq, setFreq] = useState<string>(MANUAL)
  const [hour, setHour] = useState(2)
  const [syncNow, setSyncNow] = useState(true)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const pureConfig = () => Object.fromEntries(
    Object.entries(config).filter(([k]) => !["sync_frequency", "sync_mode", "selected_tables"].includes(k)))

  const loadTables = async () => {
    setLoadingTables(true); setTablesError(null)
    try {
      const res = await fetch("/api/connectors/introspect", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connector_type: id, config: pureConfig(), include_schema: true }),
      })
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || `HTTP ${res.status}`) }
      const data: TablesResponse = await res.json()
      const list: RemoteTable[] = (data.tables ?? []).map(t => (typeof t === "string" ? { name: t } : t))
      setTables(list)
      // Default: every table, fetching changed rows by its most likely column when one exists.
      const defaults: Record<string, TableConfig> = {}
      list.forEach(t => {
        const guess = (t.columns ?? []).find(c => /updated_at|modified/.test(c.name)) ?? null
        defaults[t.name] = { enabled: true, incremental_column: guess?.name ?? "" }
      })
      setTableConfigs(defaults)
    } catch (e) {
      setTablesError(e instanceof Error ? e.message : "Could not list tables")
      setTables([]); setTableConfigs({})
    } finally { setLoadingTables(false) }
  }

  const test = async () => {
    setTestStatus("testing"); setTestMessage("")
    try {
      const res = await fetch("/api/connectors/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connector_type: id, config }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.success) {
        setTestStatus("success"); setTestMessage(data.message || "Connected")
        void loadTables()
      } else {
        setTestStatus("error"); setTestMessage(data.detail || data.message || "Connection failed")
      }
    } catch (e) {
      setTestStatus("error"); setTestMessage(e instanceof Error ? e.message : "Connection failed")
    }
  }

  const setTable = (t: string, patch: Partial<TableConfig>) =>
    setTableConfigs(prev => ({ ...prev, [t]: { ...prev[t], ...patch } }))

  const enabled = Object.entries(tableConfigs).filter(([, c]) => c.enabled)
  const incremental = enabled.filter(([, c]) => c.incremental_column)
  const effectiveFreq = pipelinesEnabled ? freq : MANUAL
  const freqOpt = FREQ_OPTIONS.find(f => f.id === effectiveFreq)
  const cron = freqOpt ? freqOpt.buildCron(hour) : null
  const trino = isTrinoEngine(id)
  const slug = sourceSlug(name)
  const ready = testStatus === "success" && name.trim().length > 0 && enabled.length > 0
  const filtered = tables.filter(t => t.name.toLowerCase().includes(tableSearch.toLowerCase()))

  const create = async () => {
    if (!ready || creating) return
    setCreating(true); setCreateError(null)
    const step = async (url: string, method: string, body: unknown, what: string) => {
      const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(`${what}: ${typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`}`)
      }
      return r
    }
    let createdId: string | null = null
    try {
      const res = await step("/api/connectors/create", "POST", { name: name.trim(), connector_type: id, config: pureConfig() }, "Could not create the source")
      const created: CreatedConnection = await res.json()
      createdId = created.id
      for (const [t, c] of Object.entries(tableConfigs)) {
        await step(`/api/connectors/${createdId}/tables/${encodeURIComponent(t)}/enabled`, "PATCH",
          { enabled: c.enabled, incremental_column: c.incremental_column || null }, `Could not save ${t}`)
        if (c.enabled) {
          await step(`/api/connectors/${createdId}/sync-mode`, "PATCH",
            { sync_mode: c.incremental_column ? "incremental" : "full", table_name: t }, `Could not set the sync mode of ${t}`)
        }
      }
      if (cron) await step(`/api/connectors/${createdId}/schedule`, "PATCH", { schedule: cron }, "Could not set the schedule")
      // The first sync runs on the server for as long as it takes; the source page shows
      // it live. Waiting for it here held "Finishing…" for the whole sync.
      if (syncNow && !created.engine_restarting) {
        void fetch(`/api/connectors/${createdId}/sync`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
      }
      // From the response, not from state set during this same click (it was always false).
      router.push(`/connectors/connections/${createdId}${created.engine_restarting ? "?engine=restarting" : ""}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Setup failed"
      if (createdId) {
        // The source exists; say what did not apply and finish on its page.
        toast(`${msg}. The source was created — finish its setup here.`, "error")
        router.push(`/connectors/connections/${createdId}`)
        return
      }
      setCreateError(msg)
      setCreating(false)
    }
  }

  if (!connector) {
    return (
      <div className="mx-auto max-w-xl space-y-3 px-6 py-16 text-center">
        <h2 className="text-xl font-bold">Unknown source type</h2>
        <Button render={<Link href="/connectors?tab=marketplace" />}>Choose a source type</Button>
      </div>
    )
  }

  const createLabel = syncNow && !trino ? "Create and sync" : "Create source"

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        <Link href="/connectors?tab=marketplace" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ChevronLeft className="h-3.5 w-3.5" />Sources
        </Link>
        <PageHeader title={`Add a ${connector.name} source`}
                    description="Connect, pick tables, choose how they stay fresh. Nothing is created until you press Create." />

        <div className="flex flex-wrap items-start gap-6">
          <div className="min-w-0 flex-[3_1_560px] space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-base">Connection</CardTitle>
                  {testStatus === "success" && <span className="text-xs font-semibold text-[var(--dp-good-text)]">Connected{tables.length ? ` · ${tables.length} tables` : ""}</span>}
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="src-name">Name</Label>
                  <Input id="src-name" value={name} onChange={e => setName(e.target.value)} maxLength={100} />
                  {trino && slug && <p className="text-xs text-muted-foreground">Queryable as <code className="font-mono">{slug}</code> (with a <code className="font-mono">_2</code> suffix if that name is taken)</p>}
                </div>
                <ConnectionForm
                  fields={connector.fields}
                  values={config}
                  onChange={(n, v) => { setConfig(prev => ({ ...prev, [n]: v })); if (testStatus !== "idle") setTestStatus("idle") }}
                  onTest={test}
                  testStatus={testStatus}
                  testMessage={testMessage}
                />
              </CardContent>
            </Card>

            <Card className={testStatus === "success" ? "" : "opacity-60"}>
              <CardHeader className="pb-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle className="text-base">
                    Tables {tables.length > 0 && <span className="font-normal text-muted-foreground">· {enabled.length} of {tables.length} selected</span>}
                  </CardTitle>
                  {tables.length > 0 && (
                    <div className="flex items-center gap-3 text-xs">
                      <button type="button" className="text-primary hover:underline"
                              onClick={() => { const all = enabled.length < tables.length; tables.forEach(t => setTable(t.name, { enabled: all })) }}>
                        {enabled.length < tables.length ? "Select all" : "Select none"}
                      </button>
                      {tables.length > 5 && (
                        <span className="relative">
                          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                          <Input value={tableSearch} onChange={e => setTableSearch(e.target.value)} placeholder="Filter" aria-label="Filter tables" className="h-8 w-36 pl-7 text-xs" />
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                {testStatus !== "success" ? (
                  <p className="text-sm text-muted-foreground">Test the connection to list its tables.</p>
                ) : loadingTables ? (
                  <div className="space-y-2">{[0, 1, 2].map(i => <Skeleton key={i} className="h-8" />)}</div>
                ) : tablesError ? (
                  <div className="space-y-2 text-sm">
                    <p className="text-destructive">Could not list tables: {tablesError}</p>
                    <Button size="sm" variant="outline" onClick={() => void loadTables()}>Retry</Button>
                  </div>
                ) : tables.length === 0 ? (
                  <p className="text-sm text-muted-foreground">The source is reachable but exposes no tables to sync.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[480px] text-sm">
                      <thead><tr className="border-b text-left text-xs text-muted-foreground">
                        <th scope="col" className="w-12 py-2 font-medium">Sync</th>
                        <th scope="col" className="py-2 font-medium">Table</th>
                        <th scope="col" className="py-2 font-medium">Fetch changed rows by</th>
                      </tr></thead>
                      <tbody>
                        {filtered.map(t => {
                          const cfg = tableConfigs[t.name] ?? { enabled: false, incremental_column: "" }
                          const cols = t.columns ?? []
                          const time = cols.filter(isTimeLike), rest = cols.filter(c => !isTimeLike(c))
                          return (
                            <tr key={t.name} className={`border-b last:border-0 ${cfg.enabled ? "" : "text-muted-foreground"}`}>
                              <td className="py-1.5"><input type="checkbox" checked={cfg.enabled} aria-label={`Sync ${t.name}`}
                                                           onChange={e => setTable(t.name, { enabled: e.target.checked })} /></td>
                              <td className="py-1.5"><span className="font-mono text-xs">{t.name}</span>{cols.length > 0 && <span className="text-xs text-muted-foreground"> · {cols.length} columns</span>}</td>
                              <td className="py-1.5">
                                <select value={cfg.incremental_column} disabled={!cfg.enabled} aria-label={`Changed-rows column for ${t.name}`}
                                        onChange={e => setTable(t.name, { incremental_column: e.target.value })}
                                        className="h-8 max-w-[240px] rounded-md border bg-background px-2 text-xs disabled:opacity-50">
                                  <option value="">Whole table each time</option>
                                  {time.length > 0 && <optgroup label="Recommended">{time.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}</optgroup>}
                                  {rest.length > 0 && <optgroup label="All columns">{rest.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}</optgroup>}
                                </select>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3"><CardTitle className="text-base">Keep it fresh</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                {pipelinesEnabled ? (
                  <div className="flex flex-wrap items-end gap-4">
                    <ChoiceGroup label="How often" value={freq} onChange={setFreq}
                      options={[{ label: "Manual", value: MANUAL }, ...FREQ_OPTIONS.map(f => ({ label: f.label, value: f.id as string }))]} />
                    {freqOpt?.hasTime && (
                      <div className="space-y-1.5">
                        <Label htmlFor="src-hour">At</Label>
                        <select id="src-hour" value={hour} onChange={e => setHour(Number(e.target.value))}
                                className="h-8 rounded-md border bg-background px-2 text-sm">
                          {HOUR_OPTIONS.map(h => <option key={h.value} value={h.value}>{h.label}</option>)}
                        </select>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Syncs run when you press Sync now. Recurring schedules need the pipelines component, which this deployment does not run.
                  </p>
                )}
                {trino ? (
                  <p className="border-t pt-3 text-sm text-muted-foreground">
                    The first sync waits for the query engine to load the new catalog (~1 min); run it from the source page.
                  </p>
                ) : (
                  <label className="flex items-center gap-2 border-t pt-3 text-sm font-medium">
                    <input type="checkbox" checked={syncNow} onChange={e => setSyncNow(e.target.checked)} />
                    Run the first sync right after creating
                  </label>
                )}
              </CardContent>
            </Card>

            {createError && <p role="alert" className="text-sm text-destructive">{createError}</p>}
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={create} disabled={!ready || creating}>
                {creating && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}{createLabel}
              </Button>
              <Button variant="ghost" render={<Link href="/connectors" />}>Cancel</Button>
              {!ready && (
                <span className="text-xs text-muted-foreground">
                  {!name.trim() ? "Name the source." : testStatus !== "success" ? "Test the connection first." : "Select at least one table."}
                </span>
              )}
            </div>
          </div>

          <ExplainRail label="What this source will do">
            <div>
              <p className="text-xs text-muted-foreground">This source will</p>
              <h3 className="mt-0.5 text-lg font-bold">
                {enabled.length > 0 ? `Copy ${enabled.length} table${enabled.length === 1 ? "" : "s"} into the lake` : `Connect ${connector.name}`}
                {cron ? `, ${parseCron(cron).toLowerCase()}` : enabled.length > 0 ? ", when you sync" : ""}
              </h3>
            </div>
            <ul className="space-y-1.5 text-sm">
              {trino && <li>✓ Live queries through {slug ? <code className="font-mono text-xs">{slug}</code> : "its own catalog"} in Analytics</li>}
              {enabled.length > 0 && <li>✓ {incremental.length} fetch only changed rows; {enabled.length - incremental.length} read the whole table each time</li>}
              {connector.fields.some(f => f.type === "password") && <li>✓ Credentials stored encrypted; never shown again</li>}
              {syncNow && !trino && <li>✓ First sync starts right away; you watch it on the source page</li>}
            </ul>
            {trino && (
              <RailAttention title="The query engine restarts (~1 min)">
                To add the new catalog. Analytics is unavailable meanwhile; sync from the source page once it is back.
              </RailAttention>
            )}
            <RailSection title="Not set yet">
              Columns to mask before loading — set them per table on the source page before the first sync if these tables hold personal data.
            </RailSection>
            {connector.fields.filter(f => f.type === "boolean" && f.help).map(f => (
              <RailSection key={f.name} title={f.label}>{f.help}</RailSection>
            ))}
          </ExplainRail>
        </div>
      </div>
    </div>
  )
}
