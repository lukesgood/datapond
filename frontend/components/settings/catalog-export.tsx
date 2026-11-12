"use client"

import { useCallback, useEffect, useState } from "react"
import { AlertCircle, CheckCircle2, Loader2, RefreshCw } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useToast } from "@/lib/toast"
import { lakeCatalogs, type DataCatalog } from "@/lib/data-catalogs"
import {
  MODE_HELP, canApply, exportBody, mirrorTone, summaryLine,
  type ExportMode, type ExportResult, type Mirror,
} from "@/lib/catalog-export"

async function call(url: string, init?: RequestInit) {
  const r = await fetch(url, init)
  const body = await r.json().catch(() => ({}))
  if (!r.ok) {
    const d = body?.detail
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x: { msg: string }) => x.msg).join("; ")
      : `HTTP ${r.status}`)
  }
  return body
}

const TONE_CLS = {
  good: "border-[var(--dp-good)]/30 text-[var(--dp-good-text)]",
  warn: "border-[var(--dp-warn)]/30 text-[var(--dp-warn-text)]",
  bad: "border-destructive/40 text-destructive",
} as const

/** Register one lake catalog's Iceberg tables in another, without copying data.
 *  Plan first (nothing changes), then Apply after an in-page confirmation. */
export function ExportDialog({ source, catalogs, onClose, onApplied }: {
  source: DataCatalog
  catalogs: DataCatalog[]
  onClose: () => void
  onApplied: () => void
}) {
  const targets = lakeCatalogs(catalogs).filter(c => c.name !== source.name)
  const [target, setTarget] = useState(targets[0]?.name ?? "")
  const [schema, setSchema] = useState("")
  const [mode, setMode] = useState<ExportMode>("mirror")
  const [busy, setBusy] = useState<"plan" | "apply" | null>(null)
  const [plan, setPlan] = useState<ExportResult | null>(null)
  const [result, setResult] = useState<ExportResult | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // Any change to the inputs makes the shown plan stale.
  const reset = () => { setPlan(null); setResult(null); setConfirming(false); setErr(null) }

  const run = async (apply: boolean) => {
    setBusy(apply ? "apply" : "plan"); setErr(null)
    try {
      const r: ExportResult = await call(`/api/catalogs/${encodeURIComponent(source.name)}/export`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(exportBody({ target, schema, mode, apply })),
      })
      if (apply) { setResult(r); setConfirming(false); onApplied() } else { setPlan(r); setResult(null) }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Export failed")
    } finally {
      setBusy(null)
    }
  }

  const shown = result ?? plan
  return (
    <Dialog open onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader><DialogTitle>Export tables from {source.name}</DialogTitle></DialogHeader>
        <div className="max-h-[65vh] space-y-3 overflow-y-auto py-1 pr-1 text-xs">
          <p className="text-muted-foreground">
            Registers this catalog&apos;s Iceberg tables in another catalog. Data files are not copied.
          </p>
          {targets.length === 0 ? (
            <p className="rounded-md border border-dashed px-3 py-2 text-muted-foreground">
              Add a second lake catalog (Glue, Iceberg REST or Polaris) to export to.</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="ex-target" className="text-xs">Target catalog</Label>
                  <select id="ex-target" value={target} className="h-8 w-full rounded-md border bg-background px-2 text-xs"
                          onChange={e => { setTarget(e.target.value); reset() }}>
                    {targets.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ex-schema" className="text-xs">Schema (optional)</Label>
                  <Input id="ex-schema" value={schema} placeholder="all schemas" className="h-8 text-xs"
                         onChange={e => { setSchema(e.target.value); reset() }} />
                </div>
              </div>
              <fieldset className="space-y-1.5">
                <legend className="text-xs font-medium">Mode</legend>
                {(["mirror", "move"] as ExportMode[]).map(m => (
                  <label key={m} className="flex items-start gap-2">
                    <input type="radio" name="ex-mode" className="mt-0.5" checked={mode === m}
                           onChange={() => { setMode(m); reset() }} />
                    <span className="text-muted-foreground">{MODE_HELP[m]}</span>
                  </label>
                ))}
              </fieldset>
            </>
          )}

          {shown && (
            <div className="space-y-2">
              <p className="font-medium">
                {result ? "Applied" : "Plan"}: {summaryLine(shown.summary)}
              </p>
              <div className="max-h-56 overflow-y-auto rounded-md border">
                <table className="w-full text-2xs">
                  <thead className="bg-muted/40 text-left text-muted-foreground">
                    <tr><th className="px-2 py-1">Table</th><th className="px-2 py-1">Action</th>
                      {result && <th className="px-2 py-1">Rows (source / target)</th>}
                      <th className="px-2 py-1">Detail</th></tr>
                  </thead>
                  <tbody className="divide-y">
                    {shown.tables.map(t => (
                      <tr key={`${t.schema}.${t.table}`}>
                        <td className="px-2 py-1 font-mono">{t.schema}.{t.table}</td>
                        <td className="px-2 py-1">{t.action.replace(/_/g, " ")}</td>
                        {result && <td className="px-2 py-1 tabular-nums">{t.rows_source ?? "—"} / {t.rows_target ?? "—"}</td>}
                        <td className="px-2 py-1 text-muted-foreground">{t.detail ?? ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {shown.allowed_locations_needed.length > 0 && (
                <div className="rounded-md border border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/5 px-3 py-2">
                  <p className="font-medium text-[var(--dp-warn-text)]">
                    The target catalog must be allowed to read these locations</p>
                  <ul className="mt-1 font-mono text-2xs text-muted-foreground">
                    {shown.allowed_locations_needed.map(l => <li key={l} className="break-all">{l}</li>)}
                  </ul>
                </div>
              )}
              {result && (
                <p className="flex items-center gap-1.5 text-[var(--dp-good-text)]">
                  <CheckCircle2 className="h-3.5 w-3.5" />Done. Mirrors are listed under Mirrors below.</p>
              )}
            </div>
          )}

          {confirming && plan && (
            <div className="rounded-md border border-primary/40 bg-primary/5 px-3 py-2">
              <p className="font-medium">
                Register {plan.tables.filter(t => t.action === "register").length} table(s) in {target} as {mode}?
              </p>
              <p className="mt-0.5 text-muted-foreground">
                This changes the target catalog. No data is copied, and row counts are compared on both sides afterwards.
              </p>
              <div className="mt-2 flex gap-2">
                <Button size="sm" disabled={busy !== null} onClick={() => void run(true)}>
                  {busy === "apply" && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Confirm and apply</Button>
                <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => setConfirming(false)}>Back</Button>
              </div>
            </div>
          )}

          {err && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-destructive">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{err}</div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
          <Button variant="outline" size="sm" disabled={!target || busy !== null} onClick={() => void run(false)}>
            {busy === "plan" && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Plan</Button>
          <Button size="sm" disabled={!canApply(plan) || result !== null || confirming || busy !== null}
                  onClick={() => setConfirming(true)}>Apply…</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Tables registered in two catalogs by an export: owner, read-only mirror, freshness. */
export function MirrorsSection({ refreshKey }: { refreshKey: number }) {
  const { toast } = useToast()
  const [mirrors, setMirrors] = useState<Mirror[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  const load = useCallback(async () => {
    try {
      const d = await call("/api/catalogs/mirrors")
      setMirrors(d.mirrors ?? []); setErr(null)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load mirrors")
    }
  }, [])
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load, refreshKey])

  const check = async () => {
    setChecking(true)
    try {
      const d = await call("/api/catalogs/mirrors/check", { method: "POST" })
      const n = (d.results ?? []).length
      toast(`Checked ${n} mirror${n === 1 ? "" : "s"}`, "success")
      await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Check failed")
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="space-y-2 border-t pt-3">
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-medium">Mirrors</h4>
        <Button size="sm" variant="outline" className="ml-auto h-7 gap-1.5" disabled={checking} onClick={() => void check()}>
          {checking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}Check now</Button>
      </div>
      <p className="text-2xs text-muted-foreground">
        A table has one writer. Each mirror is a read-only registration that follows its owner; Check now re-points
        mirrors that are behind and reports any that were committed to from outside.
      </p>
      {err ? (
        <p className="flex items-center gap-1.5 text-xs text-destructive"><AlertCircle className="h-3.5 w-3.5" />{err}</p>
      ) : mirrors === null ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />Loading…</p>
      ) : mirrors.length === 0 ? (
        <p className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
          No mirrors. Export a catalog to register its tables in a second catalog; they are listed here.</p>
      ) : (
        <div className="divide-y rounded-lg border">
          {mirrors.map(m => (
            <div key={m.mirror} className="flex flex-wrap items-center gap-2 px-3 py-2 text-xs">
              <span className="font-mono">{m.mirror}</span>
              <Badge variant="outline" className={`text-2xs ${TONE_CLS[mirrorTone(m.status)]}`}>{m.status}</Badge>
              <span className="text-muted-foreground">owner <span className="font-mono">{m.owner}</span></span>
              <span className="ml-auto text-2xs text-muted-foreground">
                {m.checked_at ? `checked ${new Date(m.checked_at).toLocaleString()}` : "not checked yet"}</span>
              {m.detail && <p className="w-full text-2xs text-muted-foreground">{m.detail}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
