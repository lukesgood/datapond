"use client"

import { useEffect, useState, useMemo } from "react"
import {
  ChevronRight, Database, Table2, Columns3,
  RefreshCw, Search, X, AlertCircle, Eye, EyeOff
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"

interface Column { name: string; type: string }
interface Table  { name: string; columns: Column[] | null }
interface Schema { name: string; tables: Table[] }
interface Catalog { name: string; catalog_type?: string; schemas: Schema[] }

const CATALOG_TYPE_BADGE: Record<string, { label: string; cls: string }> = {
  managed:  { label: "M", cls: "text-emerald-700 bg-emerald-100" },
  external: { label: "E", cls: "text-amber-700 bg-amber-100" },
  foreign:  { label: "F", cls: "text-blue-700 bg-blue-100" },
}

interface Props {
  onTableSelect: (catalog: string, schema: string, table: string) => void
}

// System schemas to hide by default
const SYSTEM_SCHEMAS = new Set([
  "information_schema", "pg_catalog", "pg_toast",
  "pg_temp_1", "pg_toast_temp_1", "$internal"
])

// Map Trino/SQL types to short labels + color
function typeTag(raw: string): { label: string; cls: string } {
  const t = raw.toLowerCase().split("(")[0].trim()
  if (["bigint","integer","int","smallint","tinyint","int64","int32"].includes(t))
    return { label: "int", cls: "text-blue-600 bg-blue-50" }
  if (["double","float","real","decimal","numeric","float64"].includes(t))
    return { label: "dec", cls: "text-purple-600 bg-purple-50" }
  if (["varchar","char","text","string","character varying"].includes(t))
    return { label: "str", cls: "text-green-700 bg-green-50" }
  if (["boolean","bool"].includes(t))
    return { label: "bool", cls: "text-orange-600 bg-orange-50" }
  if (["timestamp","date","time","timestamptz"].includes(t))
    return { label: "date", cls: "text-rose-600 bg-rose-50" }
  if (t === "array" || raw.startsWith("array"))
    return { label: "arr", cls: "text-cyan-600 bg-cyan-50" }
  if (t === "row" || t === "map" || t === "json")
    return { label: "obj", cls: "text-yellow-700 bg-yellow-50" }
  return { label: t.slice(0, 4), cls: "text-gray-500 bg-gray-100" }
}

export function SchemaTree({ onTableSelect }: Props) {
  const [catalogs, setCatalogs]     = useState<Catalog[]>([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState<string | null>(null)
  const [search, setSearch]         = useState("")
  const [showSystem, setShowSystem] = useState(false)
  const [openNodes, setOpenNodes]   = useState<Set<string>>(new Set())
  // Columns load lazily per table (the tree itself comes back without columns now).
  const [colCache, setColCache]     = useState<Record<string, Column[]>>({})
  const [colLoading, setColLoading] = useState<Set<string>>(new Set())

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch("/api/catalog/schemas")
      if (!res.ok) throw new Error(`${res.status}`)
      const data = await res.json()
      const cats: Catalog[] = data.catalogs || []
      setCatalogs(cats)

      // Auto-open first non-system catalog
      const autoOpen = new Set<string>()
      for (const cat of cats) {
        const schemas = cat.schemas.filter(s => !SYSTEM_SCHEMAS.has(s.name))
        if (schemas.length > 0) {
          autoOpen.add(cat.name)
          autoOpen.add(`${cat.name}.${schemas[0].name}`)
          break
        }
      }
      setOpenNodes(prev => new Set([...prev, ...autoOpen]))

    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const toggle = (key: string) =>
    setOpenNodes(prev => {
      const n = new Set(prev)
      n.has(key) ? n.delete(key) : n.add(key)
      return n
    })

  // Toggle a table node; on first open, lazily fetch its columns.
  const toggleTable = async (catalog: string, schema: string, table: string, tableKey: string) => {
    const willOpen = !openNodes.has(tableKey)
    toggle(tableKey)
    if (willOpen && !colCache[tableKey] && !colLoading.has(tableKey)) {
      setColLoading(prev => new Set(prev).add(tableKey))
      try {
        const qs = new URLSearchParams({ catalog, schema, table })
        const res = await fetch(`/api/catalog/columns?${qs}`)
        const cols: Column[] = res.ok ? await res.json() : []
        setColCache(prev => ({ ...prev, [tableKey]: cols }))
      } catch {
        setColCache(prev => ({ ...prev, [tableKey]: [] }))
      } finally {
        setColLoading(prev => { const n = new Set(prev); n.delete(tableKey); return n })
      }
    }
  }

  // Filter tree based on search
  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim()
    return catalogs
      .map(cat => ({
        ...cat,
        schemas: cat.schemas
          .filter(s => showSystem || !SYSTEM_SCHEMAS.has(s.name))
          .map(schema => ({
            ...schema,
            tables: schema.tables.filter(t =>
              !q ||
              t.name.toLowerCase().includes(q) ||
              schema.name.toLowerCase().includes(q) ||
              cat.name.toLowerCase().includes(q)
            )
          }))
          .filter(s => !q || s.tables.length > 0 || s.name.toLowerCase().includes(q))
      }))
      .filter(cat => cat.schemas.length > 0 || !q)
  }, [catalogs, search, showSystem])

  // Auto-expand matching nodes when searching
  useEffect(() => {
    if (!search) return
    const q = search.toLowerCase()
    const toOpen = new Set<string>()
    for (const cat of filtered) {
      for (const schema of cat.schemas) {
        if (schema.tables.some(t => t.name.toLowerCase().includes(q))) {
          toOpen.add(cat.name)
          toOpen.add(`${cat.name}.${schema.name}`)
        }
      }
    }
    if (toOpen.size > 0) setOpenNodes(prev => new Set([...prev, ...toOpen]))
  }, [search, filtered])

  // ── Loading ────────────────────────────────────────────────────────────────
  if (loading) return (
    <div className="p-3 space-y-2">
      {[...Array(5)].map((_, i) => (
        <Skeleton key={i} className="h-6 w-full" style={{ width: `${70 + (i % 3) * 10}%` }} />
      ))}
    </div>
  )

  // ── Error ──────────────────────────────────────────────────────────────────
  if (error) return (
    <div className="p-4 text-center space-y-2">
      <AlertCircle className="h-8 w-8 mx-auto text-muted-foreground opacity-40" />
      <p className="text-xs text-muted-foreground">Failed to load schemas</p>
      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={load}>
        <RefreshCw className="h-3 w-3 mr-1" />Retry
      </Button>
    </div>
  )

  // ── Main ───────────────────────────────────────────────────────────────────
  const totalTables = filtered.reduce((a, c) =>
    a + c.schemas.reduce((b, s) => b + s.tables.length, 0), 0)

  return (
    <div className="flex flex-col h-full text-sm">
      {/* Toolbar */}
      <div className="px-2 pt-2 pb-1 space-y-1.5 border-b shrink-0">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder="Search tables..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="h-7 pl-7 pr-7 text-xs"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground">
            {search
              ? `${totalTables} result${totalTables !== 1 ? "s" : ""}`
              : `${filtered.length} catalog${filtered.length !== 1 ? "s" : ""}`}
          </span>
          <div className="flex gap-0.5">
            <Button
              variant="ghost" size="icon"
              className="h-6 w-6"
              title={showSystem ? "Hide system schemas" : "Show system schemas"}
              onClick={() => setShowSystem(v => !v)}
            >
              {showSystem
                ? <Eye className="h-3 w-3 text-muted-foreground" />
                : <EyeOff className="h-3 w-3 text-muted-foreground" />}
            </Button>
            <Button
              variant="ghost" size="icon"
              className="h-6 w-6"
              title="Refresh"
              onClick={load}
            >
              <RefreshCw className="h-3 w-3 text-muted-foreground" />
            </Button>
          </div>
        </div>
      </div>

      {/* Tree */}
      <div className="flex-1 overflow-y-auto py-1">
        {filtered.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-muted-foreground">
            {search ? "No matching tables found" : "No catalogs available"}
          </div>
        ) : (
          filtered.map(cat => {
            const catOpen = openNodes.has(cat.name)
            return (
              <div key={cat.name}>
                {/* Catalog row */}
                <button
                  onClick={() => toggle(cat.name)}
                  className="w-full flex items-center gap-1.5 px-2 py-1 text-xs font-semibold
                             hover:bg-muted/60 transition-colors text-foreground"
                >
                  <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform ${catOpen ? "rotate-90" : ""}`} />
                  <Database className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate">{cat.name}</span>
                  {cat.catalog_type && CATALOG_TYPE_BADGE[cat.catalog_type] && (
                    <span className={`text-[9px] font-medium px-1 rounded shrink-0 ${CATALOG_TYPE_BADGE[cat.catalog_type].cls}`}>
                      {CATALOG_TYPE_BADGE[cat.catalog_type].label}
                    </span>
                  )}
                  <span className="ml-auto text-[10px] text-muted-foreground font-normal">
                    {cat.schemas.reduce((a, s) => a + s.tables.length, 0)}
                  </span>
                </button>

                {catOpen && cat.schemas.map(schema => {
                  const schemaKey = `${cat.name}.${schema.name}`
                  const schemaOpen = openNodes.has(schemaKey)
                  return (
                    <div key={schemaKey}>
                      {/* Schema row */}
                      <button
                        onClick={() => toggle(schemaKey)}
                        className="w-full flex items-center gap-1.5 pl-6 pr-2 py-0.5 text-xs
                                   hover:bg-muted/60 transition-colors text-muted-foreground hover:text-foreground"
                      >
                        <ChevronRight className={`h-3 w-3 shrink-0 transition-transform ${schemaOpen ? "rotate-90" : ""}`} />
                        <span className="truncate font-medium">{schema.name}</span>
                        <span className="ml-auto text-[10px]">{schema.tables.length}</span>
                      </button>

                      {schemaOpen && schema.tables.map(table => {
                        const tableKey = `${schemaKey}.${table.name}`
                        const tableOpen = openNodes.has(tableKey)
                        // Columns come either from the (legacy) eager tree or the lazy cache.
                        const cols = colCache[tableKey] ?? table.columns ?? null
                        const colsLoading = colLoading.has(tableKey)
                        return (
                          <div key={tableKey}>
                            {/* Table row */}
                            <div className={`
                              flex items-center pl-10 pr-1 group
                              hover:bg-muted/60 transition-colors
                              ${tableOpen ? "bg-muted/30" : ""}
                            `}>
                              {/* Expand columns */}
                              <button
                                className="shrink-0 p-0.5 mr-0.5 text-muted-foreground/50
                                           hover:text-muted-foreground transition-colors"
                                onClick={() => toggleTable(cat.name, schema.name, table.name, tableKey)}
                                title="Show columns"
                              >
                                <ChevronRight className={`h-3 w-3 transition-transform ${tableOpen ? "rotate-90" : ""}`} />
                              </button>

                              {/* Table name — click to insert SELECT */}
                              <button
                                className="flex-1 flex items-center gap-1.5 py-1 text-xs
                                           text-left min-w-0"
                                onClick={() => onTableSelect(cat.name, schema.name, table.name)}
                                title={`${cat.name}.${schema.name}.${table.name}`}
                              >
                                <Table2 className="h-3 w-3 shrink-0 text-muted-foreground" />
                                <span className="truncate min-w-0">{table.name}</span>
                              </button>
                            </div>

                            {/* Columns (lazy-loaded on expand) */}
                            {tableOpen && (
                              <div className="pl-14 pr-2 pb-1">
                                {colsLoading && (!cols || cols.length === 0) && (
                                  <p className="text-[11px] text-muted-foreground/60 italic py-0.5">Loading columns…</p>
                                )}
                                {!colsLoading && cols && cols.length === 0 && (
                                  <p className="text-[11px] text-muted-foreground/60 italic py-0.5">No column info</p>
                                )}
                                {(cols || []).map(col => {
                                  const tag = typeTag(col.type)
                                  return (
                                    <div
                                      key={col.name}
                                      className="flex items-center gap-1.5 py-0.5 group/col
                                                 hover:bg-muted/40 px-1 rounded"
                                    >
                                      <Columns3 className="h-2.5 w-2.5 shrink-0 text-muted-foreground/50" />
                                      <span
                                        className="text-[11px] text-muted-foreground truncate flex-1 min-w-0"
                                        title={`${col.name}: ${col.type}`}
                                      >
                                        {col.name}
                                      </span>
                                      <span className={`text-[9px] font-mono px-1 py-px rounded shrink-0 ${tag.cls}`}>
                                        {tag.label}
                                      </span>
                                    </div>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        )
                      })}

                      {schemaOpen && schema.tables.length === 0 && (
                        <p className="pl-12 py-1 text-[11px] text-muted-foreground/60 italic">
                          No tables
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
