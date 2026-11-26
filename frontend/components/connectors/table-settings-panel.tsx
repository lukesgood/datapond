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
import { lakeLabel } from "@/lib/data-catalogs"
import { hasDataLine, targetRefusal, type AlsoSynced, type TargetRefusal } from "@/lib/sync-target"

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
  /** Other jobs of this connection landing in the same lake table (a second copy). */
  also_synced_as?: AlsoSynced[]
  /** No job yet on a source that has been set up: waits for a person to enable it. */
  is_new?: boolean
  last_run_at?: string | null
  last_run_status?: string | null
}

interface SchemaColumn { name: string; type: string }

const isTimeLike = (c: SchemaColumn) =>
  /timestamp|date/i.test(c.type) || /updated_at|created_at|modified/.test(c.name)

const list = (s: string) => s.split(",").map(x => x.trim()).filter(Boolean)

/** One table's sync settings, in the right column of the source page. They were an
 *  inline editor under the row, reached by a hover-only "Edit", with uppercase 11px
 *  labels, and its three saves never checked a response — a refused save closed the
 *  editor as if it had worked. */
export function TableSettingsPanel({ connId, table, lakes, defaultLake, canEdit, refetch = false, onSaved, onClose }: {
  connId: string
  /** S3, REST or custom Python: every sync reads everything again, so the choice is
   *  replace or merge by key — there is no changed-rows column to pick. */
  refetch?: boolean
  table: SourceTable
  lakes: { name: string; is_default: boolean; engine_catalog?: string; kind?: string }[]
  defaultLake?: string
  canEdit: boolean
  onSaved: () => void | Promise<void>
  onClose: () => void
}) {
  const { toast } = useToast()
  const ps = table.partition_spec
  // For a refetch source the "merge" mode is a full read plus key columns.
  const [mode, setMode] = useState(refetch ? ((table.key_columns || []).length ? "merge" : "full") : table.sync_mode || "full")
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
  // Set when the save is refused because the table already has data in another catalog.
  const [moving, setMoving] = useState<Extract<TargetRefusal, { kind: "has_data" }> | null>(null)
  const [choice, setChoice] = useState<"move" | "leave">("move")

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
  const merge = mode === "merge"
  const timeCols = columns.filter(isTimeLike)
  const otherCols = columns.filter(c => !isTimeLike(c))

  const save = async () => {
    if (merge && list(keyCols).length === 0) { setErr("Name at least one key column to merge by."); return }
    setSaving(true); setErr(null)
    const partition_spec = partCol === "" ? null : partCol === "__none__" ? [] : [{ column: partCol, transform: partTransform }]
    const steps: [string, string, unknown][] = [
      [`/api/connectors/${connId}/tables/${encodeURIComponent(table.name)}/enabled`, "table settings", {
        enabled: table.enabled,
        incremental_column: incremental ? (incCol || null) : null,
        key_columns: incremental || merge ? list(keyCols) : [],
        pii_columns: list(piiCols),
        target_catalog: target,
        ...(moving ? { existing: choice } : {}),
      }],
      [`/api/connectors/${connId}/sync-mode`, "sync mode", { sync_mode: merge ? "full" : mode, table_name: table.name }],
      [`/api/connectors/${connId}/tables/${encodeURIComponent(table.name)}/partition`, "partitioning", { partition_spec }],
    ]
    try {
      for (const [url, what, body] of steps) {
        const r = await fetch(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          const refusal = targetRefusal(r.status, d.detail)
          if (refusal?.kind === "has_data") { setMoving(refusal); return }
          if (refusal?.kind === "duplicate") { setErr(refusal.message); return }
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
          {refetch ? (
            <>
              <ChoiceGroup label="Sync mode" value={mode} onChange={v => setMode(v)}
                options={[{ label: "Replace the table", value: "full" }, { label: "Merge by key", value: "merge" }]} />
              <p className="text-xs text-muted-foreground">
                {merge
                  ? "Rows with the same key are updated; rows that left the source stay in the lake."
                  : "Each sync reads everything again and replaces the table, so it matches the source exactly."}
              </p>
            </>
          ) : (
            <ChoiceGroup label="Sync mode" value={mode} onChange={v => { setMode(v); if (v !== "incremental") setIncCol("") }}
              options={[{ label: "Full refresh", value: "full" }, { label: "Changed rows only", value: "incremental" }]} />
          )}
        </div>
        {merge && (
          <div className="space-y-1.5">
            <Label htmlFor="ts-key">Key columns</Label>
            <Input id="ts-key" className="font-mono text-xs" value={keyCols} onChange={e => setKeyCols(e.target.value)} placeholder="id"
                   list="ts-key-cols" />
            <datalist id="ts-key-cols">{columns.map(c => <option key={c.name} value={c.name} />)}</datalist>
            <p className="text-xs text-muted-foreground">Comma separated. Together they identify one row.</p>
          </div>
        )}

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
            <select id="ts-target" value={target} onChange={e => { setTarget(e.target.value); setMoving(null) }}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm">
              <option value="">{lakeLabel(defaultLake, lakes) ?? "Default catalog"} (default)</option>
              {lakes.filter(c => !c.is_default).map(c => <option key={c.name} value={c.name}>{lakeLabel(c.name, lakes)}</option>)}
            </select>
          </div>
        )}
        {moving && (
          <div role="group" aria-label={`What happens to ${moving.table} in ${moving.from}`}
               className="space-y-2 rounded-lg border border-[var(--dp-warn)]/40 bg-[var(--dp-warn)]/10 p-3">
            <p className="text-sm font-medium">{moving.table} already has data in {moving.from}</p>
            <p className="text-xs text-muted-foreground">{hasDataLine(moving)} Choose what happens to it.</p>
            <ChoiceGroup label="Existing data" value={choice} onChange={v => setChoice(v)}
              options={[{ value: "move" as const, label: `Move it to ${moving.to}` },
                        { value: "leave" as const, label: "Leave it and start fresh" }]} />
            <p className="text-xs text-muted-foreground">
              {choice === "move"
                ? `Registers the same files in ${moving.to} as the owner; ${moving.from} keeps a read-only mirror. Nothing is copied. Needs catalog:write.`
                : `The next sync writes a new table in ${moving.to}. ${moving.from}.${moving.table} stops updating; delete it when you no longer need it.`}
            </p>
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
          <Button size="sm" onClick={save} disabled={saving}>{saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}{moving ? (choice === "move" ? "Move and save" : "Save and start fresh") : "Save table"}</Button>
          <Button size="sm" variant="ghost" onClick={onClose} disabled={saving}>Cancel</Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">Read-only: changing a table needs connector:write.</p>
      )}
    </aside>
  )
}
