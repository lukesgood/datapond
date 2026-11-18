"use client"

import { useEffect, useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { useToast } from "@/lib/toast"
import { responseErrorMessage } from "@/lib/auth"
import {
  approvalWarning, describeDraft, fieldError, unresolvedJoinDims,
  type CatalogEntry, type DimensionRow, type MetricDetail,
} from "@/lib/metrics"
import { CatalogSelect, ColumnSelect, TableSelect, isTimeType } from "./catalog-pickers"

export type Join = { id: number; catalog: string; from_table: string; to_table: string; on_columns: string[][]; source: string; approved_by_name: string | null }
export type TableRef = { catalog: string; namespace: string; name: string }

const GRAINS = ["day", "week", "month", "quarter", "year"]
type DimRow = { name: string; column: string; join_id: number | null; joinRef?: DimensionRow["join"] }

function Field({ id, label, hint, error, children }: { id: string; label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-sm font-semibold">{label}</label>
      {children}
      {error ? <p className="text-xs text-destructive">{error}</p> : hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function Section({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="space-y-3 border-t pt-4">
      <div className="flex items-center justify-between gap-2"><h3 className="text-sm font-semibold">{title}</h3>{action}</div>
      {children}
    </section>
  )
}

export function MetricEditor({ mode, base, catalogs, tables, onDone, onCancel }: {
  mode: "new" | "version"; base: MetricDetail | null; catalogs: CatalogEntry[]; tables: TableRef[] | null
  onDone: (name: string) => void; onCancel: () => void
}) {
  const { toast } = useToast()
  const cur = base?.versions[0]
  const [name, setName] = useState(base?.metric.name ?? "")
  const [label, setLabel] = useState(base?.metric.label ?? "")
  const [synonyms, setSynonyms] = useState((base?.metric.synonyms ?? []).join(", "))
  const [catalog, setCatalog] = useState(cur?.catalog ?? (catalogs[0]?.name ?? ""))
  const [table, setTable] = useState(cur?.base_table ?? "")
  const [measure, setMeasure] = useState(cur?.measure ?? "")
  const [filters, setFilters] = useState(cur?.filters ?? "")
  const [timeColumn, setTimeColumn] = useState(cur?.time_column ?? "")
  const [grains, setGrains] = useState<string[]>(cur?.grains ?? [])
  const [maxDays, setMaxDays] = useState(cur?.max_period_days ?? 366)
  const [dims, setDims] = useState<DimRow[]>((cur?.dimensions ?? []).map(d => ({ name: d.name, column: d.column, join_id: null, joinRef: d.join })))
  const [note, setNote] = useState("")
  const [joins, setJoins] = useState<Join[]>([])
  const [joinsLoaded, setJoinsLoaded] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [preview, setPreview] = useState<{ columns: string[]; rows: unknown[][]; citation: { sql: string } } | null>(null)
  const [previewing, setPreviewing] = useState(false)

  useEffect(() => {
    fetch("/api/semantic/joins").then(r => r.ok ? r.json() : { joins: [] }).then(d => {
      setJoins(d.joins)
      // A saved version stores the join by its tables and columns; find the registry row again.
      setDims(prev => prev.map(x => {
        const ref = x.joinRef
        const hit = ref && (d.joins as Join[]).find(j => j.to_table === ref.to_table && JSON.stringify(j.on_columns) === JSON.stringify(ref.on))
        return hit ? { ...x, join_id: hit.id } : x
      }))
    }).catch(() => setJoins([])).finally(() => setJoinsLoaded(true))
  }, [])

  const entry = catalogs.find(c => c.name.toLowerCase() === catalog.toLowerCase())
  const tableNames = useMemo(() => {
    if (!tables || !entry) return null
    const engine = entry.engine_catalog.toLowerCase()
    return tables.filter(t => t.catalog.toLowerCase() === engine || t.catalog.toLowerCase() === entry.name.toLowerCase())
      .map(t => `${t.namespace}.${t.name}`).sort()
  }, [tables, entry])
  const usable = joins.filter(j => j.catalog.toLowerCase() === catalog.toLowerCase() && j.from_table.toLowerCase() === table.toLowerCase())

  const changeTable = (t: string) => {
    setTable(t)
    if (t.toLowerCase() !== table.toLowerCase()) { setTimeColumn(""); setGrains([]); setDims(ds => ds.map(d => ({ ...d, column: "", join_id: null, joinRef: undefined }))) }
  }

  const version = () => ({
    catalog, base_table: table, measure, filters: filters || null, time_column: timeColumn || null,
    grains, max_period_days: maxDays, change_note: note,
    dimensions: dims.filter(d => d.name && d.column).map(d => (d.join_id ? { name: d.name, column: d.column, join_id: d.join_id } : { name: d.name, column: d.column })),
  })
  const save = async () => {
    setErrors({})
    const unresolved = unresolvedJoinDims(dims)
    if (unresolved.length) {
      setErrors({ dimensions: `Pick the join for ${unresolved.join(", ")}: its approved join was not found.` })
      return
    }
    const url = mode === "new" ? "/api/semantic/metrics" : `/api/semantic/metrics/${name}/versions`
    const body = mode === "new"
      ? { name, label, synonyms: synonyms.split(",").map(s => s.trim()).filter(Boolean), version: version() }
      : version()
    setSaving(true)
    try {
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      if (res.ok) { const d = await res.json(); toast(`${d.name} v${d.version} saved as a draft`, "success"); onDone(d.name); return }
      const data = await res.json().catch(() => ({}))
      const fe = fieldError(data.detail)
      if (fe) setErrors({ [fe.field]: fe.message })
      else toast(typeof data.detail === "string" ? data.detail : "Save failed", "error")
    } catch (e) { toast(e instanceof Error ? e.message : "Save failed", "error") }
    finally { setSaving(false) }
  }
  const latest = base?.versions[0]
  const runPreview = async () => {
    if (!latest) return
    setPreviewing(true)
    try {
      const res = await fetch(`/api/semantic/metrics/${name}/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version: latest.version, ...(latest.time_column ? { period: "last_month" } : {}) }),
      })
      if (!res.ok) { toast(await responseErrorMessage(res, "Preview failed"), "error"); return }
      setPreview(await res.json())
    } catch (e) { toast(e instanceof Error ? e.message : "Preview failed", "error") }
    finally { setPreviewing(false) }
  }

  const sentence = describeDraft({ measure, filters, base_table: table, time_column: timeColumn, grains, dimensions: dims })
  const approvedSql = base?.example_sql
  const warn = base ? approvalWarning(base.partition_info) : null

  return (
    <>
      <form className="min-w-0 flex-[3_1_440px] space-y-4 rounded-xl border bg-card p-5" onSubmit={e => { e.preventDefault(); void save() }}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-base font-semibold">{mode === "new" ? "New metric" : `${base?.metric.label ?? name} — new version (v${(latest?.version ?? 0) + 1})`}</h2>
          {mode === "version" && base?.metric.version && (
            <span className="text-xs text-muted-foreground">from v{base.metric.version}{base.versions.find(v => v.version === base.metric.version)?.approved_by_name ? `, approved by ${base.versions.find(v => v.version === base.metric.version)?.approved_by_name}` : ""}</span>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field id="m-name" label="Name" hint={mode === "new" ? "Lowercase, digits and _. Fixed after the first version." : "Fixed after the first version."} error={errors.name}>
            <Input id="m-name" className="font-mono" value={name} disabled={mode !== "new"} onChange={e => setName(e.target.value)} placeholder="revenue" />
          </Field>
          <Field id="m-label" label="Label" hint={mode === "new" ? undefined : "Set when the metric was created."} error={errors.label}>
            <Input id="m-label" value={label} disabled={mode !== "new"} onChange={e => setLabel(e.target.value)} placeholder="매출" />
          </Field>
          <Field id="m-syn" label="Also called" hint={mode === "new" ? "Comma separated. Agents match these." : "Set when the metric was created."}>
            <Input id="m-syn" value={synonyms} disabled={mode !== "new"} onChange={e => setSynonyms(e.target.value)} placeholder="매출액, sales" />
          </Field>
        </div>

        <Section title="Where it comes from">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field id="m-cat" label="Catalog" error={errors.catalog}>
              <CatalogSelect id="m-cat" value={catalog} catalogs={catalogs} onChange={v => { setCatalog(v); changeTable("") }} />
            </Field>
            <Field id="m-table" label="Base table" error={errors.base_table} hint={tables === null ? "Loading tables…" : undefined}>
              <TableSelect id="m-table" value={table} tables={tableNames} onChange={changeTable} />
            </Field>
            <Field id="m-time" label="Time column" error={errors.time_column} hint="Leave empty to compute over all rows.">
              <ColumnSelect id="m-time" catalog={catalog} table={table} value={timeColumn} allowNone noneLabel="No time column"
                            filter={isTimeType} onChange={v => { setTimeColumn(v); if (!v) setGrains([]) }} />
            </Field>
          </div>
        </Section>

        <Section title="What it measures">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="m-measure" label="Measure" hint="One aggregate, or a ratio of two: SUM(x) / COUNT(*)." error={errors.measure}>
              <Input id="m-measure" className="font-mono" value={measure} onChange={e => setMeasure(e.target.value)} placeholder="SUM(amount)" />
            </Field>
            <Field id="m-filter" label="Only rows where" hint="Optional SQL condition on the base table." error={errors.filters}>
              <Input id="m-filter" className="font-mono" value={filters} onChange={e => setFilters(e.target.value)} placeholder="status = 'paid'" />
            </Field>
          </div>
        </Section>

        <Section title="Time">
          <div className="flex flex-wrap items-end gap-6">
            <fieldset disabled={!timeColumn} className="disabled:opacity-60">
              <legend className="mb-1.5 text-sm font-semibold">Can be grouped by</legend>
              <div className="flex flex-wrap gap-3 text-sm">
                {GRAINS.map(g => (
                  <label key={g} className="flex items-center gap-1.5">
                    <input type="checkbox" checked={grains.includes(g)} onChange={e => setGrains(e.target.checked ? [...grains, g] : grains.filter(x => x !== g))} /> {g}
                  </label>
                ))}
              </div>
              {errors.grains ? <p className="mt-1 text-xs text-destructive">{errors.grains}</p>
                : !timeColumn && <p className="mt-1 text-xs text-muted-foreground">Pick a time column first.</p>}
            </fieldset>
            <div className="w-44">
              <Field id="m-max" label="Longest period (days)" error={errors.max_period_days}>
                <Input id="m-max" type="number" min={1} max={3660} value={maxDays} onChange={e => setMaxDays(Number(e.target.value))} />
              </Field>
            </div>
          </div>
        </Section>

        <Section title="Can be split by"
                 action={<Button type="button" size="sm" variant="outline" onClick={() => setDims([...dims, { name: "", column: "", join_id: null }])}>Add dimension</Button>}>
          {dims.length === 0 ? (
            <p className="text-sm text-muted-foreground">No dimensions: the metric returns one number per period.{usable.length === 0 && table ? ` No approved joins start from ${table}; approve one in Joins to split by another table's column.` : ""}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-sm">
                <thead><tr className="text-left text-xs text-muted-foreground">
                  <th scope="col" className="pb-1 font-medium">Name</th><th scope="col" className="px-2 pb-1 font-medium">From</th>
                  <th scope="col" className="px-2 pb-1 font-medium">Column</th><th scope="col"><span className="sr-only">Remove</span></th>
                </tr></thead>
                <tbody>
                  {dims.map((d, i) => {
                    const join = usable.find(j => j.id === d.join_id)
                    const set = (patch: Partial<DimRow>) => setDims(dims.map((x, k) => (k === i ? { ...x, ...patch } : x)))
                    return (
                      <tr key={i} className="align-top">
                        <td className="py-1 pr-2"><Input aria-label={`Dimension ${i + 1} name`} className="font-mono" value={d.name} placeholder="region" onChange={e => set({ name: e.target.value })} /></td>
                        <td className="px-2 py-1">
                          <select aria-label={`Dimension ${i + 1} table`} className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={d.join_id ?? ""}
                                  onChange={e => set({ join_id: e.target.value ? Number(e.target.value) : null, joinRef: undefined, column: "" })}>
                            <option value="">{table || "base table"}</option>
                            {usable.map(j => <option key={j.id} value={j.id}>{j.to_table} (approved join)</option>)}
                            {d.joinRef && !d.join_id && <option value="" disabled>{d.joinRef.to_table} — join no longer approved</option>}
                          </select>
                        </td>
                        <td className="px-2 py-1">
                          <ColumnSelect label={`Dimension ${i + 1} column`} catalog={catalog} table={join ? join.to_table : (d.joinRef && !d.join_id ? d.joinRef.to_table : table)}
                                        value={d.column} onChange={v => set({ column: v })} />
                        </td>
                        <td className="py-1"><Button type="button" size="sm" variant="ghost" onClick={() => setDims(dims.filter((_, k) => k !== i))}>Remove</Button></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {errors.dimensions && <p className="text-xs text-destructive">{errors.dimensions}</p>}
        </Section>

        <Section title="What changed">
          <Field id="m-note" label="Change note" hint="Shown in the version history and to the approver.">
            <Textarea id="m-note" value={note} onChange={e => setNote(e.target.value)} placeholder={mode === "new" ? "First version." : "Exclude refunded orders."} />
          </Field>
        </Section>

        <div className="flex gap-2">
          <Button type="submit" disabled={!joinsLoaded || saving}>{saving ? "Saving…" : "Save draft"}</Button>
          <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
      </form>

      <ExplainRail label="About this draft">
        <RailSection title="This draft computes">
          {sentence ? <p className="font-mono text-xs text-foreground">{sentence}</p> : <p>Pick a base table and write a measure.</p>}
          <p className="mt-1 text-xs">The server compiles and checks the SQL when you save: columns, the measure, and every join.</p>
        </RailSection>
        {approvedSql && (
          <RailSection title={`What agents run now (v${base?.metric.version})`}>
            <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border bg-background p-2 text-xs text-foreground">{approvedSql}</pre>
          </RailSection>
        )}
        {mode === "version" && latest && (
          <RailSection title="Try the latest saved version">
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" size="sm" variant="outline" disabled={previewing} onClick={() => void runPreview()}>
                {previewing ? "Running…" : `Run v${latest.version}${latest.time_column ? " on last month" : ""}`}
              </Button>
              <span className="text-xs">Runs what is saved, not this form. Save first to try your changes.</span>
            </div>
            {preview && (
              <div className="mt-2 space-y-2">
                <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border bg-background p-2 text-xs text-foreground">{preview.citation.sql}</pre>
                {preview.rows.length === 0 ? <p className="text-xs">The query ran and returned no rows.</p> : (
                  <div className="overflow-x-auto rounded-md border bg-background">
                    <table className="w-full text-xs text-foreground">
                      <thead><tr>{preview.columns.map(c => <th key={c} scope="col" className="px-2 py-1 text-left font-medium">{c}</th>)}</tr></thead>
                      <tbody>{preview.rows.slice(0, 20).map((r, i) => <tr key={i} className="border-t">{r.map((c, j) => <td key={j} className="px-2 py-1">{String(c)}</td>)}</tr>)}</tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </RailSection>
        )}
        <RailSection title="Before an admin approves">
          <ul className="list-disc space-y-0.5 pl-4 text-xs">
            {mode === "version" && base?.metric.version
              ? <li>v{base.metric.version} stays the answer agents get until this version is approved.</li>
              : <li>Agents do not see the metric until an admin approves a version.</li>}
            <li>Joins were checked unique when they were approved, so a dimension never multiplies rows.</li>
            <li>Approved results cite the metric, its version and who approved it.</li>
          </ul>
        </RailSection>
        {warn && <RailAttention title="Partitioning unknown">{warn}</RailAttention>}
      </ExplainRail>
    </>
  )
}
