"use client"

import { useEffect, useState } from "react"
import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ChoiceGroup } from "@/components/ui/choice-group"
import { ErrorBox } from "@/components/ui/error-box"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { readJson } from "@/lib/source-state"
import { useToast } from "@/lib/toast"
import {
  MANUAL, canTestCdc, cdcConnection, createRequest, emptyStream, objectsMade, streamProblem, streamedTables,
  type CdcTest, type StreamForm, type StreamKind,
} from "@/lib/streaming"

type SourceRow = { id: string; name: string; connector_type: string }

const field = "h-9 w-full rounded-md border bg-background px-2 text-sm"

/** One form for a new stream: database changes (CDC) from an existing source, or a
 *  Kafka/Kinesis topic. The rail checks the database before Create is allowed. */
export function NewStream({ kind: initialKind, existingSources, onCreated, onCancel }: {
  kind: StreamKind
  /** RisingWave source names already present, to mark tables already streamed */
  existingSources: string[]
  onCreated: () => void
  onCancel: () => void
}) {
  const { toast } = useToast()
  const [f, setF] = useState<StreamForm>(() => emptyStream(initialKind))
  const set = (patch: Partial<StreamForm>) => setF(prev => ({ ...prev, ...patch }))
  const [pgSources, setPgSources] = useState<SourceRow[] | null>(null)
  const [test, setTest] = useState<CdcTest | null>(null)
  const [testing, setTesting] = useState(false)
  const [testedAt, setTestedAt] = useState<Date | null>(null)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch("/api/connectors/connections")
      .then(r => readJson<SourceRow[]>(r))
      .then(rows => {
        if (cancelled) return
        const pg = (Array.isArray(rows) ? rows : []).filter(r => ["postgresql", "postgres"].includes(String(r.connector_type).toLowerCase()))
        setPgSources(pg)
        setF(prev => (prev.connectionId ? prev : { ...prev, connectionId: pg[0]?.id ?? MANUAL }))
      })
      .catch(() => { if (!cancelled) { setPgSources([]); setF(prev => (prev.connectionId ? prev : { ...prev, connectionId: MANUAL })) } })
    return () => { cancelled = true }
  }, [])

  const runTest = async (form: StreamForm) => {
    setTesting(true); setTest(null)
    try {
      const r = await fetch("/api/streaming/cdc-test", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cdcConnection(form)),
      })
      const d = await readJson<CdcTest>(r)
      setTest(d); setTestedAt(new Date())
      setF(prev => ({ ...prev, tables: prev.tables.filter(t => d.tables.includes(t)) }))
    } catch (e) {
      setTest({ success: false, tables: [], error: e instanceof Error ? e.message : "Check failed" })
    } finally {
      setTesting(false)
    }
  }

  // An existing source is checked as soon as it is chosen; typed-in details on request.
  const autoTestId = f.kind === "cdc" && f.connectionId && f.connectionId !== MANUAL ? f.connectionId : null
  useEffect(() => {
    if (!autoTestId) return
    const t = window.setTimeout(() => void runTest({ ...emptyStream(), connectionId: autoTestId, schema: f.schema }), 0)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoTestId])

  const problem = streamProblem(f, test)
  const streamed = streamedTables(existingSources, test?.tables ?? [])
  const sourceName = pgSources?.find(s => s.id === f.connectionId)?.name

  const create = async () => {
    if (problem || creating) return
    setCreating(true); setCreateError(null)
    try {
      const { url, body } = createRequest(f)
      const d = await readJson<{ tables_failed?: number; results?: { table: string; error: string | null }[] }>(
        await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }))
      const failed = (d.results ?? []).filter(r => r.error)
      if (failed.length) {
        setCreateError(`${failed.length} table${failed.length === 1 ? "" : "s"} failed: ${failed.map(r => `${r.table}: ${r.error}`).join("; ")}`)
        onCreated()
        return
      }
      toast(`Created ${f.name.trim()}`, "success")
      onCreated()
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Create failed")
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="flex flex-wrap items-start gap-6">
      <form className="min-w-0 flex-[3_1_540px] space-y-4 rounded-xl border bg-card p-5" onSubmit={e => { e.preventDefault(); void create() }}>
        <h3 className="text-base font-semibold">New stream</h3>
        <ChoiceGroup<StreamKind> label="Stream from" value={f.kind} onChange={kind => { set({ kind }); setCreateError(null) }}
          options={[{ label: "Database changes (CDC)", value: "cdc" }, { label: "Kafka", value: "kafka" }, { label: "Kinesis", value: "kinesis" }]} />

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="ns-name">Name</Label>
            <Input id="ns-name" className="font-mono" value={f.name} onChange={e => set({ name: e.target.value })} placeholder="orders_cdc" />
          </div>
          {f.kind === "cdc" && (
            <div className="space-y-1.5">
              <Label htmlFor="ns-src">Source</Label>
              <select id="ns-src" className={field} value={f.connectionId} disabled={pgSources === null}
                      onChange={e => { set({ connectionId: e.target.value, tables: [] }); setTest(null) }}>
                {pgSources === null && <option value="">Loading sources…</option>}
                {pgSources?.map(s => <option key={s.id} value={s.id}>{s.name} — PostgreSQL</option>)}
                <option value={MANUAL}>Another database…</option>
              </select>
              <p className="text-xs text-muted-foreground">
                {f.connectionId === MANUAL ? "Typed in here; stored only in the stream." : "Reuses the source's connection and stored password."}
              </p>
            </div>
          )}
        </div>

        {f.kind === "cdc" && f.connectionId === MANUAL && (
          <fieldset className="grid gap-3 rounded-lg border p-3 sm:grid-cols-3">
            <legend className="px-1 text-xs font-semibold">Database</legend>
            <div className="space-y-1.5 sm:col-span-2"><Label htmlFor="ns-host">Host</Label><Input id="ns-host" value={f.host} onChange={e => set({ host: e.target.value })} /></div>
            <div className="space-y-1.5"><Label htmlFor="ns-port">Port</Label><Input id="ns-port" inputMode="numeric" value={f.port} onChange={e => set({ port: e.target.value })} /></div>
            <div className="space-y-1.5"><Label htmlFor="ns-db">Database</Label><Input id="ns-db" value={f.database} onChange={e => set({ database: e.target.value })} /></div>
            <div className="space-y-1.5"><Label htmlFor="ns-user">User</Label><Input id="ns-user" autoComplete="off" value={f.user} onChange={e => set({ user: e.target.value })} /></div>
            <div className="space-y-1.5"><Label htmlFor="ns-pw">Password</Label><Input id="ns-pw" type="password" autoComplete="new-password" value={f.password} onChange={e => set({ password: e.target.value })} /></div>
            <div className="sm:col-span-3"><Button type="button" variant="outline" size="sm" disabled={!canTestCdc(f) || testing} onClick={() => void runTest(f)}>
              {testing && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Check the database
            </Button></div>
          </fieldset>
        )}

        {f.kind === "cdc" && test?.success && (
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Tables</legend>
            {test.tables.length === 0 ? <p className="text-xs text-muted-foreground">No tables in schema {f.schema}.</p> : (
              <div className="grid gap-1.5 text-sm sm:grid-cols-3">
                {test.tables.map(t => (
                  <label key={t} className="flex items-center gap-2">
                    <input type="checkbox" checked={f.tables.includes(t)}
                           onChange={e => set({ tables: e.target.checked ? [...f.tables, t] : f.tables.filter(x => x !== t) })} />
                    <span className="font-mono text-xs">{t}</span>
                    {streamed.has(t) && <span className="text-xs text-muted-foreground" title="A stream already captures a table with this name, possibly from another database.">(also in {streamed.get(t)})</span>}
                  </label>
                ))}
              </div>
            )}
          </fieldset>
        )}

        {f.kind === "kafka" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5"><Label htmlFor="ns-topic">Topic</Label><Input id="ns-topic" className="font-mono" value={f.topic} onChange={e => set({ topic: e.target.value })} /></div>
            <div className="space-y-1.5"><Label htmlFor="ns-boot">Bootstrap servers</Label><Input id="ns-boot" className="font-mono" value={f.bootstrap} onChange={e => set({ bootstrap: e.target.value })} placeholder="kafka:9092" /></div>
          </div>
        )}
        {f.kind === "kinesis" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5"><Label htmlFor="ns-stream">Stream name</Label><Input id="ns-stream" className="font-mono" value={f.stream} onChange={e => set({ stream: e.target.value })} /></div>
            <div className="space-y-1.5"><Label htmlFor="ns-region">Region</Label><Input id="ns-region" className="font-mono" value={f.region} onChange={e => set({ region: e.target.value })} /></div>
          </div>
        )}
        {f.kind !== "cdc" && (
          <div className="grid gap-3 sm:grid-cols-[160px_minmax(0,1fr)]">
            <div className="space-y-1.5">
              <Label htmlFor="ns-fmt">Message format</Label>
              <select id="ns-fmt" className={field} value={f.format} onChange={e => set({ format: e.target.value as StreamForm["format"] })}>
                <option value="json">JSON</option><option value="avro">Avro</option><option value="csv">CSV</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ns-cols">Columns</Label>
              <Input id="ns-cols" className="font-mono" value={f.columns} onChange={e => set({ columns: e.target.value })} />
              <p className="text-xs text-muted-foreground">Column definitions, e.g. <code className="font-mono">user_id BIGINT, event VARCHAR, ts TIMESTAMPTZ</code>.</p>
            </div>
          </div>
        )}

        <div className="max-w-xs space-y-1.5">
          <Label htmlFor="ns-ns">Write to namespace</Label>
          <select id="ns-ns" className={field} value={f.namespace} onChange={e => set({ namespace: e.target.value })}>
            <option value="raw">raw</option><option value="refined">refined</option>
          </select>
        </div>

        {createError && <div role="alert"><ErrorBox msg={createError} /></div>}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={!!problem || creating}>
            {creating && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}Create stream
          </Button>
          <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
          {problem && !testing && <span className="text-xs text-muted-foreground">{problem}</span>}
        </div>
      </form>

      <ExplainRail label="Can this stream run">
        {f.kind === "cdc" ? (
          <RailSection title="Can this database stream?">
            {testing ? <p className="flex items-center gap-1.5"><Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />Checking{sourceName ? ` ${sourceName}` : ""}…</p>
              : !test ? <p>{f.connectionId === MANUAL ? "Fill in the database and press Check." : "Choose a source."}</p>
              : (
                <>
                  {testedAt && <p className="text-xs">Checked{sourceName ? ` on ${sourceName}` : ""} at {testedAt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}.</p>}
                  <ul className="space-y-2.5 text-foreground">
                    {(test.checks ?? [{ key: "reachable", ok: false, label: "Reachable", detail: test.error ?? null }]).map(c => (
                      <li key={c.key} className="flex gap-2">
                        {c.key === "publication" ? <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                          : c.ok ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: "var(--dp-good)" }} aria-hidden />
                          : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden />}
                        <span>
                          <span className={c.ok || c.key === "publication" ? "" : "font-semibold"}>{c.label}</span>
                          <span className="sr-only">{c.ok ? " (ok)" : " (not ok)"}</span>
                          {c.detail && <span className="block text-xs text-muted-foreground">{c.detail}</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {test.success && (test.checks ?? []).some(c => !c.ok) && (
                    <RailAttention title="Create stays off until every check passes" tone="bad">
                      <Button type="button" variant="outline" size="sm" className="mt-1" onClick={() => void runTest(f)}>Check again</Button>
                    </RailAttention>
                  )}
                </>
              )}
          </RailSection>
        ) : (
          <RailSection title="What it reads">
            <p>{f.kind === "kafka" ? "New messages on the topic from now on (latest offset)." : "New records on the stream from now on."} Each message is parsed as {f.format.toUpperCase()} into the columns you list.</p>
          </RailSection>
        )}
        <RailSection title="Creates">
          <p>
            {f.kind === "cdc"
              ? <>For each table: a source, a materialized view and an Iceberg sink in <code className="font-mono text-foreground">{f.namespace}</code>{f.tables.length ? ` — ${f.tables.length * 3} objects` : ""}.</>
              : <>A source, a materialized view and an Iceberg sink in <code className="font-mono text-foreground">{f.namespace}</code>.</>}
          </p>
          {objectsMade(f).length > 0 && f.name.trim() && (
            <p className="font-mono text-xs">{objectsMade(f).slice(0, 6).join(", ")}{objectsMade(f).length > 6 ? ", …" : ""}</p>
          )}
        </RailSection>
      </ExplainRail>
    </div>
  )
}
