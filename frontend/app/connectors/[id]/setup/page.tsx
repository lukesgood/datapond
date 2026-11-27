"use client"

import { Fragment, useState, use } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { ChevronLeft, Loader2, Search } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { SchedulePicker } from "@/components/ui/schedule-picker"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { PageHeader } from "@/components/ui/page-header"
import { ConnectionForm } from "@/components/connectors/connection-form"
import { getConnector, previewRows, readsEverythingEachSync, S3_NEW_FILES_COLUMN } from "@/lib/connectors"
import { useCapability } from "@/lib/capabilities"
import { isTrinoEngine } from "@/lib/engine-restart"
import { useToast } from "@/lib/toast"
import { parseCron } from "@/lib/schedule"
import { suggestedMasks } from "@/lib/pii-columns"

interface RemoteTable {
  name: string; row_count?: number; columns?: { name: string; type: string; nullable: boolean }[]
  sample?: Record<string, unknown>[]; sample_error?: string   // file, REST and Python sources
}
interface TableConfig { enabled: boolean; incremental_column: string; mask: string }   // "" = whole table each time; mask = comma-separated columns
type ConfigValue = string | number | boolean | null | undefined
interface TablesResponse { tables?: Array<string | RemoteTable> }
interface CreatedConnection { id: string; engine_restarting?: boolean; catalog?: string | null }

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
  const schedulerEnabled = useCapability("scheduled_sync")
  const { toast } = useToast()

  const refetch = readsEverythingEachSync(id)
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
  const [previewing, setPreviewing] = useState<string | null>(null)
  const [tableConfigs, setTableConfigs] = useState<Record<string, TableConfig>>({})

  const [schedule, setSchedule] = useState<string | null>(null)
  const [syncNow, setSyncNow] = useState(true)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // A cleared optional box ("") is not sent: the backend's default applies, and a number
  // field would otherwise fail validation on "".
  const pureConfig = () => Object.fromEntries(
    Object.entries(config).filter(([k, v]) => v !== "" && !["sync_frequency", "sync_mode", "selected_tables"].includes(k)))

  const loadTables = async () => {
    setLoadingTables(true); setTablesError(null)
    try {
      const res = await fetch("/api/connectors/introspect", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connector_type: id, config: pureConfig(), include_schema: true, include_sample: refetch }),
      })
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || `HTTP ${res.status}`) }
      const data: TablesResponse = await res.json()
      const list: RemoteTable[] = (data.tables ?? []).map(t => (typeof t === "string" ? { name: t } : t))
      setTables(list)
      // Default: every table, fetching changed rows by its most likely column when one
      // exists and the source type can (S3/REST/Python read everything each time).
      const defaults: Record<string, TableConfig> = {}
      list.forEach(t => {
        const guess = refetch ? null : (t.columns ?? []).find(c => /updated_at|modified/.test(c.name)) ?? null
        // Columns named like personal data are masked unless the person clears them.
        defaults[t.name] = { enabled: true, incremental_column: guess?.name ?? "", mask: suggestedMasks(t.columns ?? []).join(", ") }
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
        body: JSON.stringify({ connector_type: id, config: pureConfig() }),
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
  const masked = enabled.filter(([, c]) => c.mask.trim())
  const cron = schedulerEnabled ? schedule : null
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
        const detail = typeof d.detail === "string" ? d.detail : typeof d.detail?.message === "string" ? d.detail.message : `HTTP ${r.status}`
        throw new Error(`${what}: ${detail}`)
      }
      return r
    }
    let createdId: string | null = null
    try {
      const res = await step("/api/connectors/create", "POST", { name: name.trim(), connector_type: id, config: pureConfig() }, "Could not create the source")
      const created: CreatedConnection = await res.json()
      createdId = created.id
      // One request for every table (it was two per table: 400 for a 200-table database).
      await step(`/api/connectors/${createdId}/tables`, "PUT", {
        tables: Object.entries(tableConfigs).map(([t, c]) => ({
          table: t, enabled: c.enabled, incremental_column: c.incremental_column || null,
          pii_columns: c.mask.split(",").map(x => x.trim()).filter(Boolean) })),
      }, "Could not save the table choices")
      if (cron) await step(`/api/connectors/${createdId}/schedule`, "PATCH", { schedule: cron }, "Could not set the schedule")
      // The source page runs the first sync (?sync=1), so its progress and any failure
      // show there; this page used to send it and never read the answer.
      const firstSync = syncNow && !created.engine_restarting
      // From the response, not from state set during this same click (it was always false).
      router.push(`/connectors/connections/${createdId}${created.engine_restarting ? "?engine=restarting" : firstSync ? "?sync=1" : ""}`)
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
                    {refetch && (
                      <p className="mb-2 text-xs text-muted-foreground">
                        {id === "s3"
                          ? "Every file: each sync reads the whole folder again and replaces the table. New files only: each sync adds the files that arrived since the last one (the first reads them all)."
                          : "Each sync reads every record again and replaces the table. To keep rows that left the source, set key columns per table on the source page; the sync then merges by them."}
                      </p>
                    )}
                    <table className={`w-full text-sm ${refetch ? "min-w-[420px]" : "min-w-[640px]"}`}>
                      <thead><tr className="border-b text-left text-xs text-muted-foreground">
                        <th scope="col" className="w-12 py-2 font-medium">Sync</th>
                        <th scope="col" className="py-2 font-medium">Table</th>
                        {!refetch && <th scope="col" className="py-2 font-medium">Fetch changed rows by</th>}
                        {id === "s3" && <th scope="col" className="py-2 font-medium">Each sync reads</th>}
                        <th scope="col" className="py-2 font-medium">Mask before loading</th>
                      </tr></thead>
                      <tbody>
                        {filtered.map(t => {
                          const cfg = tableConfigs[t.name] ?? { enabled: false, incremental_column: "", mask: "" }
                          const cols = t.columns ?? []
                          const time = cols.filter(isTimeLike), rest = cols.filter(c => !isTimeLike(c))
                          const open = previewing === t.name
                          const span = 3 + (refetch ? 0 : 1) + (id === "s3" ? 1 : 0)
                          return (
                            <Fragment key={t.name}>
                            <tr className={`${open ? "" : "border-b last:border-0"} ${cfg.enabled ? "" : "text-muted-foreground"}`}>
                              <td className="py-1.5"><input type="checkbox" checked={cfg.enabled} aria-label={`Sync ${t.name}`}
                                                           onChange={e => setTable(t.name, { enabled: e.target.checked })} /></td>
                              <td className="py-1.5">
                                <span className="font-mono text-xs">{t.name}</span>
                                {t.row_count != null && <span className="text-xs text-muted-foreground"> · {t.row_count.toLocaleString("en-US")} rows</span>}
                                {/* The columns the lake table will get: for a Python or REST source
                                    this is the only look at what the code or API returns. */}
                                {cols.length > 0 && (
                                  <span className="block max-w-[320px] truncate font-mono text-2xs text-muted-foreground" title={cols.map(c => `${c.name} ${c.type}`).join("\n")}>
                                    {cols.slice(0, 6).map(c => c.name).join(", ")}{cols.length > 6 ? ` +${cols.length - 6}` : ""}
                                  </span>
                                )}
                                {t.sample && t.sample.length > 0 && (
                                  <button type="button" onClick={() => setPreviewing(open ? null : t.name)} aria-expanded={open}
                                          className="text-2xs text-primary underline-offset-2 hover:underline">
                                    {open ? "Hide rows" : `Show first ${t.sample.length} rows`}
                                  </button>
                                )}
                                {t.sample_error && <span className="block text-2xs text-[var(--dp-warn-text)]" title={t.sample_error}>Could not read rows to preview</span>}
                              </td>
                              {!refetch && <td className="py-1.5">
                                <select value={cfg.incremental_column} disabled={!cfg.enabled} aria-label={`Changed-rows column for ${t.name}`}
                                        onChange={e => setTable(t.name, { incremental_column: e.target.value })}
                                        className="h-8 max-w-[240px] rounded-md border bg-background px-2 text-xs disabled:opacity-50">
                                  <option value="">Whole table each time</option>
                                  {time.length > 0 && <optgroup label="Recommended">{time.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}</optgroup>}
                                  {rest.length > 0 && <optgroup label="All columns">{rest.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}</optgroup>}
                                </select>
                              </td>}
                              {id === "s3" && <td className="py-1.5">
                                <select value={cfg.incremental_column} disabled={!cfg.enabled} aria-label={`What each sync of ${t.name} reads`}
                                        onChange={e => setTable(t.name, { incremental_column: e.target.value })}
                                        className="h-8 rounded-md border bg-background px-2 text-xs disabled:opacity-50">
                                  <option value="">Every file (replace)</option>
                                  <option value={S3_NEW_FILES_COLUMN}>New files only</option>
                                </select>
                              </td>}
                              <td className="py-1.5">
                                <Input value={cfg.mask} disabled={!cfg.enabled} placeholder="none" list={`mask-${t.name}`}
                                       aria-label={`Columns to mask in ${t.name}`}
                                       onChange={e => setTable(t.name, { mask: e.target.value })}
                                       className="h-8 max-w-[240px] font-mono text-xs" />
                                {cols.length > 0 && <datalist id={`mask-${t.name}`}>{cols.map(c => <option key={c.name} value={c.name} />)}</datalist>}
                              </td>
                            </tr>
                            {open && t.sample && (() => {
                              const p = previewRows(t.sample, cfg.mask)
                              return (
                                <tr className="border-b last:border-0">
                                  <td colSpan={span} className="pb-3 pl-12">
                                    <div className="overflow-x-auto rounded-md border">
                                      <table className="w-full text-2xs" aria-label={`First rows of ${t.name}`}>
                                        <thead className="bg-muted/50"><tr>
                                          {p.headers.map(h => <th key={h} scope="col" className="whitespace-nowrap px-2 py-1 text-left font-mono font-medium">{h}</th>)}
                                        </tr></thead>
                                        <tbody>{p.rows.map((r, i) => (
                                          <tr key={i} className="border-t">
                                            {r.map((v, j) => p.masked.has(p.headers[j])
                                              ? <td key={j} className="px-2 py-1 italic text-muted-foreground">masked</td>
                                              : <td key={j} className="max-w-[220px] truncate whitespace-nowrap px-2 py-1 font-mono" title={v}>{v}</td>)}
                                          </tr>
                                        ))}</tbody>
                                      </table>
                                    </div>
                                    <p className="mt-1 text-2xs text-muted-foreground">Read from the source now, not saved. Columns under Mask before loading show as masked.</p>
                                  </td>
                                </tr>
                              )
                            })()}
                            </Fragment>
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
                {schedulerEnabled ? (
                  <SchedulePicker id="src-schedule" value={schedule} onChange={setSchedule} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Syncs run when you press Sync now. Scheduled syncs are turned off on this deployment.
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
              {enabled.length > 0 && (refetch
                ? <li>✓ {incremental.length > 0 ? `${incremental.length} add only new files; ${enabled.length - incremental.length} replace the table each sync` : "Each sync reads everything again and replaces the table"}</li>
                : <li>✓ {incremental.length} fetch only changed rows; {enabled.length - incremental.length} read the whole table each time</li>)}
              {connector.fields.some(f => f.type === "password") && <li>✓ Credentials stored encrypted; never shown again</li>}
              {syncNow && !trino && <li>✓ First sync starts right away; you watch it on the source page</li>}
            </ul>
            {trino && (
              <RailAttention title="The query engine restarts (~1 min)">
                To add the new catalog. Analytics is unavailable meanwhile; sync from the source page once it is back.
              </RailAttention>
            )}
            {enabled.length > 0 && (masked.length > 0 ? (
              <RailSection title="Masked before loading">
                {masked.length} of {enabled.length} tables mask columns from the first sync on. Columns named like
                personal data are filled in for you; check them, and add any the names do not give away.
              </RailSection>
            ) : (
              <RailAttention title="No columns masked">
                Nothing in these tables looks personal by its name. If any column holds personal data, name it under Mask before loading; the first sync loads what is not masked.
              </RailAttention>
            ))}
            {connector.fields.filter(f => f.type === "boolean" && f.help).map(f => (
              <RailSection key={f.name} title={f.label}>{f.help}</RailSection>
            ))}
          </ExplainRail>
        </div>
      </div>
    </div>
  )
}
