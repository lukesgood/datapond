"use client"

import { useEffect, useState } from "react"
import { Loader2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ChoiceGroup } from "@/components/ui/choice-group"
import { RailAttention } from "@/components/ui/explain-rail"
import { SourceState } from "@/components/ui/source-state"
import { readJson } from "@/lib/source-state"
import { useToast } from "@/lib/toast"

export interface SourceTable {
  name: string
  enabled: boolean
  sync_mode?: string
  incremental_column?: string | null
  last_value?: string | null
  effective_mode?: string
  partition_spec?: { column: string; transform: string }[] | null
  key_columns?: string[] | null
  pii_columns?: string[] | null
  target_catalog?: string | null
}

interface SchemaColumn { name: string; type: string }

const isTimeLike = (c: SchemaColumn) =>
  /timestamp|date/i.test(c.type) || /updated_at|created_at|modified/.test(c.name)

const list = (s: string) => s.split(",").map(x => x.trim()).filter(Boolean)

/** One table's sync settings, in the right column of the source page. They were an
 *  inline editor under the row, reached by a hover-only "Edit", with uppercase 11px
 *  labels, and its three saves never checked a response — a refused save closed the
 *  editor as if it had worked. */
export function TableSettingsPanel({ connId, table, lakes, defaultLake, canEdit, onSaved, onClose }: {
  connId: string
  table: SourceTable
  lakes: { name: string; is_default: boolean }[]
  defaultLake?: string
  canEdit: boolean
  onSaved: () => void | Promise<void>
  onClose: () => void
}) {
  const { toast } = useToast()
  const ps = table.partition_spec
  const [mode, setMode] = useState(table.sync_mode || "full")
  const [incCol, setIncCol] = useState(table.incremental_column || "")
  const [keyCols, setKeyCols] = useState((table.key_columns || []).join(", "))
  const [piiCols, setPiiCols] = useState((table.pii_columns || []).join(", "))
  const [target, setTarget] = useState(table.target_catalog || "")
  // "" = Auto (inferred), "__none__" = unpartitioned, other = column
  const [partCol, setPartCol] = useState(ps == null ? "" : ps.length === 0 ? "__none__" : ps[0].column)
  const [partTransform, setPartTransform] = useState(ps && ps.length > 0 ? ps[0].transform || "day" : "day")
  const [columns, setColumns] = useState<SchemaColumn[]>([])
  const [loadingCols, setLoadingCols] = useState(true)
  const [colsError, setColsError] = useState<string | null>(null)
  const [colsReload, setColsReload] = useState(0)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/connectors/${connId}/schema/${encodeURIComponent(table.name)}`)
      .then(r => readJson<{ columns?: SchemaColumn[] }>(r))
      .then(d => { if (!cancelled) { setColumns(d.columns ?? []); setColsError(null) } })
      .catch(e => { if (!cancelled) setColsError(e instanceof Error ? e.message : "failed") })
      .finally(() => { if (!cancelled) setLoadingCols(false) })
    return () => { cancelled = true }
  }, [connId, table.name, colsReload])

  const incremental = mode === "incremental"
  const timeCols = columns.filter(isTimeLike)
  const otherCols = columns.filter(c => !isTimeLike(c))

  const save = async () => {
    setSaving(true); setErr(null)
    const partition_spec = partCol === "" ? null : partCol === "__none__" ? [] : [{ column: partCol, transform: partTransform }]
    const steps: [string, string, unknown][] = [
      [`/api/connectors/${connId}/tables/${encodeURIComponent(table.name)}/enabled`, "table settings", {
        enabled: table.enabled,
        incremental_column: incremental ? (incCol || null) : null,
        key_columns: incremental ? list(keyCols) : [],
        pii_columns: list(piiCols),
        target_catalog: target,
      }],
      [`/api/connectors/${connId}/sync-mode`, "sync mode", { sync_mode: mode, table_name: table.name }],
      [`/api/connectors/${connId}/tables/${encodeURIComponent(table.name)}/partition`, "partitioning", { partition_spec }],
    ]
    try {
      for (const [url, what, body] of steps) {
        const r = await fetch(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          setErr(`Could not save the ${what}: ${typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`}`)
          return
        }
      }
      toast(`${table.name} saved`, "success")
      await onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save")
    } finally { setSaving(false) }
  }

  return (
    <aside aria-label={`Settings for ${table.name}`}
           className="min-w-0 flex-[2_1_320px] space-y-4 rounded-xl border border-primary/50 bg-muted/40 p-5 text-sm lg:sticky lg:top-6">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">Table</p>
          <h3 className="truncate font-mono text-base font-semibold">{table.name}</h3>
        </div>
        <Button size="icon-sm" variant="ghost" aria-label="Close table settings" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>

      <fieldset disabled={!canEdit || saving} className="space-y-4">
        <div className="space-y-1.5">
          <Label>Sync mode</Label>
          <ChoiceGroup label="Sync mode" value={mode} onChange={v => { setMode(v); if (v !== "incremental") setIncCol("") }}
            options={[{ label: "Full refresh", value: "full" }, { label: "Changed rows only", value: "incremental" }]} />
        </div>

        {incremental && (
          <>
            <div className="space-y-1.5">
              <Label htmlFor="ts-inc">Changed since column</Label>
              <select id="ts-inc" value={incCol} onChange={e => setIncCol(e.target.value)} disabled={loadingCols}
                      className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                <option value="">{loadingCols ? "Loading columns…" : "Choose a column"}</option>
                {timeCols.length > 0 && <optgroup label="Recommended">{timeCols.map(c => <option key={c.name} value={c.name}>{c.name} ({c.type})</option>)}</optgroup>}
                {otherCols.length > 0 && <optgroup label="All columns">{otherCols.map(c => <option key={c.name} value={c.name}>{c.name} ({c.type})</option>)}</optgroup>}
              </select>
              {colsError && (
                <SourceState status="error" what="this table's columns" error={colsError}
                             onRetry={() => { setLoadingCols(true); setColsReload(n => n + 1) }}>{null}</SourceState>
              )}
              {table.last_value && <p className="text-xs text-muted-foreground">Last value seen: {String(table.last_value).slice(0, 19)}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ts-key">Key columns</Label>
              <Input id="ts-key" className="font-mono text-xs" value={keyCols} onChange={e => setKeyCols(e.target.value)} placeholder="id" />
              <p className="text-xs text-muted-foreground">Rows with the same key are updated, not duplicated. Blank appends every changed row.</p>
            </div>
          </>
        )}

        <div className="space-y-1.5">
          <Label htmlFor="ts-pii">Mask before loading</Label>
          <Input id="ts-pii" className="font-mono text-xs" value={piiCols} onChange={e => setPiiCols(e.target.value)} placeholder="email, phone" />
          <p className="text-xs text-muted-foreground">Comma separated; <code className="font-mono">*</code> masks every text column. Masked values never reach the lake.</p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="ts-part">Partition by</Label>
            <select id="ts-part" value={partCol} onChange={e => setPartCol(e.target.value)}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm">
              <option value="">Auto (day of a timestamp)</option>
              <option value="__none__">None</option>
              {columns.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ts-tr">Transform</Label>
            <select id="ts-tr" value={partTransform} onChange={e => setPartTransform(e.target.value)}
                    disabled={partCol === "" || partCol === "__none__"}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm disabled:opacity-50">
              <option value="day">day</option><option value="month">month</option><option value="year">year</option>
              <option value="identity">value as-is</option><option value="bucket">16-way hash</option>
            </select>
          </div>
        </div>

        {lakes.length > 1 && (
          <div className="space-y-1.5">
            <Label htmlFor="ts-target">Write to</Label>
            <select id="ts-target" value={target} onChange={e => setTarget(e.target.value)}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm">
              <option value="">{defaultLake ?? "Default catalog"} (default)</option>
              {lakes.filter(c => !c.is_default).map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </div>
        )}
      </fieldset>

      {incremental && !incCol && !loadingCols && (
        <RailAttention title="No changed-since column">The first run, and every run after it, reads the whole table.</RailAttention>
      )}
      <p className="text-xs text-muted-foreground">Partition changes apply on the next full sync, which recreates the table.</p>

      {err && <p role="alert" className="text-xs text-destructive">{err}</p>}
      {canEdit ? (
        <div className="flex gap-2">
          <Button size="sm" onClick={save} disabled={saving}>{saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Save table</Button>
          <Button size="sm" variant="ghost" onClick={onClose} disabled={saving}>Cancel</Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">Read-only: changing a table needs connector:write.</p>
      )}
    </aside>
  )
}
