"use client"

import { useEffect, useState } from "react"
import { Input } from "@/components/ui/input"
import type { CatalogEntry } from "@/lib/metrics"

/** Pickers for the metric form: the catalog, a table in it, and a column of a table.
 *  Each falls back to a text box when its list cannot be read, so a slow or partly
 *  failing catalog never blocks writing a definition by hand. */

type Column = { name: string; type: string }
const columnCache = new Map<string, Promise<Column[] | null>>()

function loadColumns(catalog: string, table: string): Promise<Column[] | null> {
  const [schema, name] = table.split(".")
  if (!catalog || !schema || !name) return Promise.resolve(null)
  const key = `${catalog.toLowerCase()}|${table.toLowerCase()}`
  let p = columnCache.get(key)
  if (!p) {
    const q = new URLSearchParams({ catalog, schema, table: name })
    p = fetch(`/api/catalog/columns?${q}`)
      .then(r => (r.ok ? r.json() : null))
      .then((d: unknown) => (Array.isArray(d) ? (d as Column[]) : null))
      .catch(() => null)
    p.then(v => { if (v === null) columnCache.delete(key) })
    columnCache.set(key, p)
  }
  return p
}

export function useColumns(catalog: string, table: string): Column[] | null | undefined {
  // undefined: loading; null: could not read; []: no columns
  const [state, setState] = useState<{ key: string; cols: Column[] | null } | null>(null)
  const key = `${catalog}|${table}`
  useEffect(() => {
    let live = true
    void loadColumns(catalog, table).then(cols => { if (live) setState({ key, cols }) })
    return () => { live = false }
  }, [catalog, table, key])
  return state?.key === key ? state.cols : undefined
}

const selectCls = "h-9 w-full rounded-md border bg-background px-2 text-sm"

export function CatalogSelect({ id, value, catalogs, onChange }: {
  id: string; value: string; catalogs: CatalogEntry[]; onChange: (v: string) => void
}) {
  if (!catalogs.length) return <Input id={id} value={value} onChange={e => onChange(e.target.value)} placeholder="AwsDataCatalog" />
  const known = catalogs.some(c => c.name.toLowerCase() === value.toLowerCase())
  return (
    <select id={id} className={selectCls} value={value} onChange={e => onChange(e.target.value)}>
      {!value && <option value="">Choose a catalog</option>}
      {value && !known && <option value={value}>{value}</option>}
      {catalogs.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
    </select>
  )
}

export function TableSelect({ id, value, tables, onChange }: {
  id: string; value: string; tables: string[] | null; onChange: (v: string) => void
}) {
  if (!tables?.length) return <Input id={id} value={value} onChange={e => onChange(e.target.value)} placeholder="schema.table" />
  const known = tables.some(t => t.toLowerCase() === value.toLowerCase())
  return (
    <select id={id} className={selectCls} value={value} onChange={e => onChange(e.target.value)}>
      {!value && <option value="">Choose a table</option>}
      {value && !known && <option value={value}>{value}</option>}
      {tables.map(t => <option key={t} value={t}>{t}</option>)}
    </select>
  )
}

export function ColumnSelect({ id, label, catalog, table, value, onChange, allowNone, noneLabel = "None", filter }: {
  id?: string; label?: string; catalog: string; table: string; value: string; onChange: (v: string) => void
  allowNone?: boolean; noneLabel?: string; filter?: (c: Column) => boolean
}) {
  const cols = useColumns(catalog, table)
  if (cols === null || (cols !== undefined && cols.length === 0)) {
    return <Input id={id} aria-label={label} value={value} onChange={e => onChange(e.target.value)} placeholder="column" />
  }
  const shown = (cols ?? []).filter(c => !filter || filter(c) || c.name.toLowerCase() === value.toLowerCase())
  const known = shown.some(c => c.name.toLowerCase() === value.toLowerCase())
  return (
    <select id={id} aria-label={label} className={selectCls} value={value} disabled={cols === undefined}
            onChange={e => onChange(e.target.value)}>
      {cols === undefined && <option value={value}>{value || "Loading columns…"}</option>}
      {allowNone && <option value="">{noneLabel}</option>}
      {!allowNone && !value && <option value="">Choose a column</option>}
      {value && !known && cols !== undefined && <option value={value}>{value}</option>}
      {shown.map(c => <option key={c.name} value={c.name}>{c.name} ({c.type})</option>)}
    </select>
  )
}

export const isTimeType = (c: Column) => /date|time/i.test(c.type)
