"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { CheckCircle2, Loader2, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { ErrorBox } from "@/components/ui/error-box"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { SchedulePicker } from "@/components/ui/schedule-picker"
import { matchCron, parseCron } from "@/lib/schedule"
import { readJson } from "@/lib/source-state"
import { useToast } from "@/lib/toast"
import {
  NAMESPACES, dagIdFor, formProblem, previewSql, runStrip, runSummary, saveBody, tablesRead,
  type RunCell, type TransformForm,
} from "@/lib/transforms"

type Check = { ok: boolean; error: string | null; columns: { name: string; type: string }[] }
type Preview = { columns: string[]; rows: unknown[][]; pii_masked?: number }

const field = "h-9 w-full rounded-md border bg-background px-2 text-sm"

/** Create or edit one SQL transform: settings on the left, what will run on the right.
 *  Save deploys straight away (the API writes and activates the Airflow job). */
export function TransformEditor({ id, initial, dagId, onSaved, onCancel }: {
  /** null when creating */
  id: string | null
  initial: TransformForm
  dagId?: string | null
  onSaved: (id: string) => void
  onCancel: () => void
}) {
  const { toast } = useToast()
  const creating = id === null
  const [f, setF] = useState<TransformForm>(initial)
  const set = (patch: Partial<TransformForm>) => setF(prev => ({ ...prev, ...patch }))
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [check, setCheck] = useState<Check | null>(null)
  const [checking, setChecking] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [runs, setRuns] = useState<RunCell[] | null>(null)

  const problem = formProblem(f, creating)
  const job = dagId ?? (f.name.trim() ? dagIdFor(f.name.trim()) : null)
  const reads = tablesRead(f.sql)
  const utcHour = f.schedule ? (matchCron(f.schedule)?.freqId.match(/daily|weekly|monthly/) ? matchCron(f.schedule)!.hour : null) : null
  const target = `${f.target_namespace}.${f.target_table.trim() || "…"}`

  // Ask Trino whether the SELECT plans and what it writes, a moment after typing stops.
  const sql = f.sql
  const sqlLooksRight = !formProblem({ ...f, name: "x", target_table: "x", source_namespace: "a", target_namespace: "b" }, true)
  useEffect(() => {
    if (!sqlLooksRight) return
    let cancelled = false
    const t = window.setTimeout(async () => {
      setChecking(true)
      try {
        const r = await fetch("/api/transforms/check", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sql }),
        })
        const d = await readJson<Check>(r)
        if (!cancelled) setCheck(d)
      } catch (e) {
        if (!cancelled) setCheck({ ok: false, error: e instanceof Error ? e.message : "Could not check", columns: [] })
      } finally {
        if (!cancelled) setChecking(false)
      }
    }, 800)
    return () => { cancelled = true; window.clearTimeout(t) }
  }, [sql, sqlLooksRight])

  useEffect(() => {
    if (!dagId) return
    let cancelled = false
    fetch(`/api/airflow/dags/${encodeURIComponent(dagId)}/dag-runs?limit=10&order_by=-execution_date`)
      .then(r => readJson<{ dag_runs?: { state?: string; end_date?: string; execution_date?: string }[] }>(r))
      .then(d => { if (!cancelled) setRuns(runStrip(d.dag_runs ?? [])) })
      .catch(() => { if (!cancelled) setRuns(null) })
    return () => { cancelled = true }
  }, [dagId])

  const save = async () => {
    if (problem || saving) return
    setSaving(true); setSaveError(null)
    try {
      const r = await fetch(creating ? "/api/transforms" : `/api/transforms/${encodeURIComponent(id)}`, {
        method: creating ? "POST" : "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(saveBody(f, creating)),
      })
      const d = await readJson<{ id: string; dag_id: string }>(r)
      toast(creating ? `Deployed ${f.name.trim()} as ${d.dag_id}` : `Saved and redeployed ${f.name}`, "success")
      onSaved(d.id)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed")
    } finally {
      setSaving(false)
    }
  }

  const runPreview = async () => {
    setPreviewing(true); setPreviewError(null); setPreview(null)
    try {
      const r = await fetch("/api/queries/execute", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: previewSql(f.sql), save_history: false }),
      })
      setPreview(await readJson<Preview>(r))
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : "Preview failed")
    } finally {
      setPreviewing(false)
    }
  }

  return (
    <div className="flex flex-wrap items-start gap-6">
      <form className="min-w-0 flex-[3_1_560px] space-y-4 rounded-xl border bg-card p-5"
            onSubmit={e => { e.preventDefault(); void save() }}>
        <h3 className="text-base font-semibold">{creating ? "New transform" : `Edit ${initial.name}`}</h3>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="tf-name">Name</Label>
            <Input id="tf-name" value={f.name} disabled={!creating} onChange={e => set({ name: e.target.value })} />
            <p className="text-xs text-muted-foreground">
              {creating ? <>Becomes the Airflow job <code className="font-mono">{job ?? "transform_…"}</code>. Fixed after creating.</> : "Fixed after creating."}
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tf-desc">Description</Label>
            <Input id="tf-desc" value={f.description} onChange={e => set({ description: e.target.value })} />
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="tf-src">Reads from</Label>
            <select id="tf-src" className={field} value={f.source_namespace} onChange={e => set({ source_namespace: e.target.value })}>
              {[...new Set([...NAMESPACES, f.source_namespace])].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tf-dst">Writes to namespace</Label>
            <select id="tf-dst" className={field} value={f.target_namespace} onChange={e => set({ target_namespace: e.target.value })}>
              {NAMESPACES.map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tf-table">Table</Label>
            <Input id="tf-table" className="font-mono" value={f.target_table} onChange={e => set({ target_table: e.target.value })} />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="tf-sql">SELECT</Label>
          <Textarea id="tf-sql" spellCheck={false} rows={10} className="font-mono text-sm"
                    value={f.sql} onChange={e => set({ sql: e.target.value })} />
          <p className="text-xs text-muted-foreground">
            Only the SELECT. DataPond wraps it in CREATE OR REPLACE TABLE … AS and replaces the table on each run.
          </p>
        </div>

        <SchedulePicker id="tf-schedule" value={f.schedule} onChange={schedule => set({ schedule })} />

        {saveError && <div role="alert"><ErrorBox msg={saveError} /></div>}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={!!problem || saving}>
            {saving && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}Save and deploy
          </Button>
          <Button type="button" variant="outline" onClick={() => void runPreview()} disabled={!sqlLooksRight || previewing}>
            {previewing && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}Preview 50 rows
          </Button>
          <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
          {problem && <span className="text-xs text-muted-foreground">{problem}</span>}
        </div>

        {previewError && <div role="alert"><ErrorBox msg={`Preview failed: ${previewError}`} /></div>}
        {preview && (
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">
              {preview.rows.length} row{preview.rows.length === 1 ? "" : "s"} shown as you are allowed to see them
              {preview.pii_masked ? ` · ${preview.pii_masked} PII value${preview.pii_masked === 1 ? "" : "s"} masked` : ""}.
              The job itself writes unmasked rows.
            </p>
            <div className="max-h-72 overflow-auto rounded-lg border">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-muted">
                  <tr>{preview.columns.map(c => <th key={c} scope="col" className="px-2 py-1.5 text-left font-medium">{c}</th>)}</tr>
                </thead>
                <tbody>
                  {preview.rows.map((row, i) => (
                    <tr key={i} className="border-t">
                      {row.map((v, j) => <td key={j} className="whitespace-nowrap px-2 py-1 font-mono">{v === null ? "∅" : String(v)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </form>

      <ExplainRail label="What runs">
        <RailSection title="What runs">
          <ul className="list-disc space-y-1 pl-4">
            <li>{f.schedule ? parseCron(f.schedule) : "Only when someone presses Run now"}{f.schedule ? " (Airflow's clock, UTC)" : ""}.</li>
            <li>Replaces <code className="font-mono text-foreground">{target}</code> on each run.</li>
            {reads.length > 0 && <li>Reads {reads.map((t, i) => <span key={t}>{i > 0 && ", "}<code className="font-mono text-foreground">{t}</code></span>)}.</li>}
          </ul>
        </RailSection>

        <RailSection title="Checked against the catalog">
          {!sqlLooksRight ? <p>Checked once the SQL is one SELECT.</p>
            : checking && !check ? <p className="flex items-center gap-1.5"><Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />Checking…</p>
            : check?.ok ? (
              <p className="flex items-start gap-1.5 text-foreground">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: "var(--dp-good)" }} aria-hidden />
                <span>Plans in Trino; writes {check.columns.length} column{check.columns.length === 1 ? "" : "s"}
                  {check.columns.length > 0 && <>: <span className="font-mono text-xs">{check.columns.slice(0, 6).map(c => c.name).join(", ")}{check.columns.length > 6 ? ", …" : ""}</span></>}.
                  {checking && " Rechecking…"}</span>
              </p>
            ) : check ? (
              <p className="flex items-start gap-1.5 text-destructive">
                <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /><span className="break-words">{check.error}</span>
              </p>
            ) : null}
        </RailSection>

        {!creating && (
          <RailSection title="Last runs">
            {runs === null ? <p>Run history could not be read from Airflow.</p> : (
              <>
                <div className="flex gap-1" role="img" aria-label={runSummary(runs)}>
                  {runs.map((r, i) => (
                    <span key={i} title={`${r.state}${r.at ? ` · ${new Date(r.at).toLocaleString()}` : ""}`}
                          className="h-3.5 w-3.5 rounded-sm"
                          style={{ background: r.state === "success" ? "var(--dp-good)" : r.state === "failed" ? "var(--destructive)" : "var(--muted-foreground)" }} />
                  ))}
                </div>
                <p className="text-xs">{runSummary(runs)}</p>
              </>
            )}
            {dagId && <Link href={`/pipelines/${encodeURIComponent(dagId)}`} className="text-sm text-primary hover:underline">Run history and logs</Link>}
          </RailSection>
        )}

        {utcHour !== null && (
          <RailAttention title="Schedules are in UTC">
            Airflow runs on UTC: {String(utcHour).padStart(2, "0")}:00 UTC is {String((utcHour + 9) % 24).padStart(2, "0")}:00 in Korea.
          </RailAttention>
        )}
      </ExplainRail>
    </div>
  )
}
