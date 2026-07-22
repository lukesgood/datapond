"use client"

import { useCallback, useEffect, useState } from "react"
import NextLink from "next/link"
import { CapabilityGate } from "@/lib/capabilities"
import { getUser } from "@/lib/auth"
import { ErrorBox, EmptyState } from "@/components/ui/error-box"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { TableCard } from "@/components/catalog/table-card"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Loader2, Sparkles, Clock } from "lucide-react"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Search, Database, FolderOpen, Layers } from "lucide-react"

interface Table {
  name: string
  namespace: string
  catalog: string
  catalog_type: string
  table_type: string
  last_updated?: string
}

// Catalog-type colors mirror the per-card badge palette in table-card.tsx so the
// summary breakdown and the individual cards read as the same encoding.
const CATALOG_TYPE_META: Record<string, { label: string; color: string }> = {
  managed:  { label: "Managed",  color: "var(--dp-managed)" },
  external: { label: "External", color: "var(--dp-warn)" },
  foreign:  { label: "Foreign",  color: "var(--chart-2)" },
}

interface NamespaceInfo {
  name: string
  properties?: Record<string, string>
}

interface CatalogData {
  tables: Table[]
  namespaces: NamespaceInfo[]
}

interface CollectionOption { name: string }
interface CollectionsResponse { collections?: CollectionOption[] }
interface CatalogColumn { name: string; type: string }

function CatalogPageInner() {
  const [data, setData] = useState<CatalogData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [selectedNamespace, setSelectedNamespace] = useState<string>("all")
  const [sendTable, setSendTable] = useState<Table | null>(null)
  // "Send to Knowledge" drives admin-only ingest-source/schedule endpoints — a
  // viewer would fill in the dialog only to hit a 403. Gate the action here,
  // mirroring how the AI Gateway hides admin-only forms from non-admins.
  const [isAdmin] = useState(() => getUser()?.role === "admin")

  const fetchData = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)

      const [tablesRes, namespacesRes] = await Promise.all([
        fetch("/api/catalog/tables"),
        fetch("/api/catalog/namespaces"),
      ])
      if (!tablesRes.ok || !namespacesRes.ok) {
        throw new Error(`Catalog request failed (tables ${tablesRes.status}, namespaces ${namespacesRes.status})`)
      }
      const tablesData = await tablesRes.json()
      const namespacesData = await namespacesRes.json()

      setData({
        tables: tablesData.tables || [],
        namespaces: namespacesData.namespaces || [],
      })
    } catch (requestError) {
      console.error("Failed to fetch catalog data:", requestError)
      setData(null)
      setError(requestError instanceof Error ? requestError.message : "Failed to load catalog data")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => void fetchData(), 0)
    return () => window.clearTimeout(initial)
  }, [fetchData])

  // Filter tables based on search and namespace
  const filteredTables = data?.tables.filter((table) => {
    const matchesSearch =
      searchQuery === "" ||
      table.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      table.namespace.toLowerCase().includes(searchQuery.toLowerCase())

    const matchesNamespace =
      selectedNamespace === "all" || table.namespace === selectedNamespace

    return matchesSearch && matchesNamespace
  })

  // Count tables per namespace
  const namespaceCounts = data?.tables.reduce((acc, table) => {
    acc[table.namespace] = (acc[table.namespace] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  // Catalog-type distribution (managed/external/foreign) for the summary breakdown —
  // scannable "what's in here" metadata without eagerly loading any columns.
  const typeCounts = data?.tables.reduce((acc, table) => {
    const key = table.catalog_type || "managed"
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {} as Record<string, number>)
  const typeSegments = Object.entries(typeCounts ?? {}).sort((a, b) => b[1] - a[1])

  const totalTables = data?.tables.length ?? 0
  const isFiltered = searchQuery !== "" || selectedNamespace !== "all"
  const clearFilters = () => { setSearchQuery(""); setSelectedNamespace("all") }
  // Keyboard activation for the namespace filter pills (Badge renders a span).
  const onFilterKeyDown = (ns: string) => (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedNamespace(ns) }
  }

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        {/* Breadcrumb skeleton */}
        <Skeleton className="h-5 w-[200px]" />

        {/* Header skeleton */}
        <div className="space-y-2">
          <Skeleton className="h-8 w-[150px]" />
          <Skeleton className="h-4 w-[300px]" />
        </div>

        {/* Search and filters skeleton */}
        <div className="flex gap-4">
          <Skeleton className="h-8 w-[300px]" />
          <Skeleton className="h-8 w-[150px]" />
        </div>

        {/* Stats skeleton */}
        <div className="grid gap-4 md:grid-cols-3">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-[120px]" />
          ))}
        </div>

        {/* Tables grid skeleton */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {[...Array(8)].map((_, i) => (
            <Skeleton key={i} className="h-[140px]" />
          ))}
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem><BreadcrumbLink href="/dashboard">Home</BreadcrumbLink></BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem><BreadcrumbPage>Catalog</BreadcrumbPage></BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Data Catalog</h2>
          <p className="text-muted-foreground">Browse and explore tables registered in the catalog</p>
        </div>
        <div role="alert" aria-live="polite">
          <ErrorBox
            msg={error ?? "Catalog data is unavailable"}
            action={<Button size="sm" variant="outline" onClick={fetchData}>Retry</Button>}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="/dashboard">Home</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Catalog</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Data Catalog</h2>
        <p className="text-muted-foreground">
          Browse and explore tables registered in the catalog
        </p>
        {!isAdmin && (
          <p className="mt-1 text-xs text-muted-foreground">
            Sending a table to Knowledge (RAG) requires an administrator — ask an administrator to enable it.
          </p>
        )}
      </div>

      {/* Search and Filters */}
      <div className="flex flex-col gap-4 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search tables..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
          />
        </div>
        <div className="flex gap-2 flex-wrap">
          <Badge
            role="button"
            tabIndex={0}
            aria-pressed={selectedNamespace === "all"}
            aria-label={`Show all namespaces (${totalTables} tables)`}
            variant={selectedNamespace === "all" ? "default" : "outline"}
            className="cursor-pointer px-3 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
            onClick={() => setSelectedNamespace("all")}
            onKeyDown={onFilterKeyDown("all")}
          >
            All ({totalTables})
          </Badge>
          {data?.namespaces.map((namespace) => (
            <Badge
              key={namespace.name}
              role="button"
              tabIndex={0}
              aria-pressed={selectedNamespace === namespace.name}
              aria-label={`Filter to namespace ${namespace.name} (${namespaceCounts?.[namespace.name] || 0} tables)`}
              variant={selectedNamespace === namespace.name ? "default" : "outline"}
              className="cursor-pointer px-3 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
              onClick={() => setSelectedNamespace(namespace.name)}
              onKeyDown={onFilterKeyDown(namespace.name)}
            >
              {namespace.name} ({namespaceCounts?.[namespace.name] || 0})
            </Badge>
          ))}
        </div>
      </div>

      {/* Statistics Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Total Tables</CardTitle>
              <Database className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="dp-num text-2xl font-bold tabular-nums">{totalTables}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Namespaces</CardTitle>
              <FolderOpen className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="dp-num text-2xl font-bold tabular-nums">{data?.namespaces.length || 0}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Table Types</CardTitle>
              <Layers className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            {totalTables > 0 && typeSegments.length > 0 ? (
              <>
                {/* Stacked share bar — same inline-bar idiom used across the app */}
                <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden="true">
                  {typeSegments.map(([type, count]) => (
                    <div
                      key={type}
                      className="h-full"
                      style={{
                        width: `${(count / totalTables) * 100}%`,
                        backgroundColor: CATALOG_TYPE_META[type]?.color ?? "var(--muted-foreground)",
                      }}
                    />
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                  {typeSegments.map(([type, count]) => (
                    <span key={type} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: CATALOG_TYPE_META[type]?.color ?? "var(--muted-foreground)" }}
                      />
                      {CATALOG_TYPE_META[type]?.label ?? type}
                      <span className="dp-num font-medium tabular-nums text-foreground">{count}</span>
                    </span>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No tables yet</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Tables Grid */}
      <div>
        <h3 className="text-xl font-semibold mb-4 flex items-baseline gap-2">
          {selectedNamespace === "all" ? "All Tables" : `Tables in ${selectedNamespace}`}
          <span className="text-sm font-normal text-muted-foreground tabular-nums">
            {isFiltered
              ? `${filteredTables?.length ?? 0} of ${totalTables} shown`
              : `${filteredTables?.length ?? 0} shown`}
          </span>
        </h3>
        {filteredTables && filteredTables.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filteredTables.map((table) => (
              <TableCard
                key={`${table.catalog}.${table.namespace}.${table.name}`}
                name={table.name}
                namespace={table.namespace}
                catalog={table.catalog}
                catalogType={table.catalog_type}
                tableType={table.table_type}
                lastUpdated={table.last_updated}
                onSendToKnowledge={isAdmin ? () => setSendTable(table) : undefined}
              />
            ))}
          </div>
        ) : (
          <Card>
            <CardContent>
              {(data?.tables.length || 0) === 0 ? (
                <EmptyState
                  icon={Database}
                  title="No tables yet"
                  hint="Connect a data source and sync it from Sources, and Iceberg tables will appear here."
                  action={<Button size="sm" render={<NextLink href="/connectors" />}>Go to Sources</Button>}
                />
              ) : (
                <EmptyState
                  icon={Search}
                  title="No tables match your filters"
                  hint={`None of the ${totalTables} table${totalTables !== 1 ? "s" : ""} in the catalog match the current search or namespace filter.`}
                  action={<Button size="sm" variant="outline" onClick={clearFilters}>Clear filters</Button>}
                />
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {sendTable && <SendToKnowledgeDialog key={`${sendTable.namespace}.${sendTable.name}`} table={sendTable} onClose={() => setSendTable(null)} />}
    </div>
  )
}

export default function CatalogPage() {
  return (
    <CapabilityGate capability="catalog">
      <CatalogPageInner />
    </CapabilityGate>
  )
}

// ── Send a catalog table to a RAG collection (embed a text column) ────────────────

function SendToKnowledgeDialog({ table, onClose }: { table: Table; onClose: () => void }) {
  const [collections, setCollections] = useState<CollectionOption[]>([])
  const [collection, setCollection] = useState("")
  const [newName, setNewName] = useState("")
  const [cols, setCols] = useState<CatalogColumn[]>([])
  const [col, setCol] = useState("")
  const [sched, setSched] = useState("")  // "" = one-off, else cron preset
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  // On success, remember the target collection so we can offer a link into
  // Knowledge instead of dead-ending the dialog on Close.
  const [done, setDone] = useState<string | null>(null)

  useEffect(() => {
    fetch("/api/ai/collections").then(r => r.json() as Promise<CollectionsResponse>)
      .then(d => { const options = d.collections ?? []; setCollections(options); if (options[0]) setCollection(options[0].name) })
      .catch(() => setCollections([]))
    const qs = new URLSearchParams({ catalog: "iceberg", schema: table.namespace, table: table.name })
    fetch(`/api/catalog/columns?${qs}`).then(r => r.json() as Promise<CatalogColumn[]>)
      .then(payload => { const columns = Array.isArray(payload) ? payload : []; setCols(columns); setCol(columns.find(column => /char|text|string/i.test(column.type))?.name ?? columns[0]?.name ?? "") })
      .catch(() => setCols([]))
  }, [table])

  const submit = async () => {
    const target = (collection === "__new__" ? newName : collection).trim()
    if (!target || !col) { setErr("Select a collection and a text column."); return }
    setBusy(true); setErr(null); setMsg(null); setDone(null)
    try {
      // ensure collection exists (idempotent)
      await fetch("/api/ai/collections", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: target, description: `From ${table.namespace}.${table.name}` }) })
      const source = { type: "iceberg", schema: table.namespace, table: table.name, text_column: col }
      if (sched) {
        const r = await fetch(`/api/ai/collections/${encodeURIComponent(target)}/schedule`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ schedule: sched, source }) })
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
        const d = await r.json(); setMsg(`Schedule created: auto re-embeds every ${d.interval_minutes} min`); setDone(target)
      } else {
        const r = await fetch(`/api/ai/collections/${encodeURIComponent(target)}/ingest-source`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(source) })
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
        const d = await r.json(); setMsg(`${d.documents} docs → ${d.chunks} chunks ingested (${target})`); setDone(target)
      }
    } catch (error) { setErr(error instanceof Error ? error.message : "Failed to send table to Knowledge") }
    setBusy(false)
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-1.5 text-base">
            <Sparkles className="h-4 w-4 text-primary" />Send to Knowledge
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
            <p className="text-xs text-muted-foreground">
              Embeds a text column from <span className="font-mono">{table.namespace}.{table.name}</span> into a RAG collection.
            </p>
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground">Collection</label>
              <select value={collection} onChange={e => setCollection(e.target.value)}
                className="h-9 w-full rounded-md border bg-background px-2 text-xs">
                {collections.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                <option value="__new__">+ New collection…</option>
              </select>
              {collection === "__new__" && (
                <Input value={newName} onChange={e => setNewName(e.target.value)} placeholder="new collection name" className="text-sm mt-1" />
              )}
            </div>
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground">Text column</label>
              <select value={col} onChange={e => setCol(e.target.value)}
                className="h-9 w-full rounded-md border bg-background px-2 text-xs">
                <option value="">column…</option>
                {cols.map(c => <option key={c.name} value={c.name}>{c.name} ({c.type})</option>)}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground">Mode</label>
              <select value={sched} onChange={e => setSched(e.target.value)}
                className="h-9 w-full rounded-md border bg-background px-2 text-xs">
                <option value="">Ingest once (now)</option>
                <option value="@hourly">Schedule — hourly</option>
                <option value="@daily">Schedule — daily</option>
                <option value="@weekly">Schedule — weekly</option>
              </select>
            </div>
            {msg && <p className="text-xs text-[var(--dp-good)]">{msg}</p>}
            {err && <div role="alert" aria-live="polite"><ErrorBox msg={err} /></div>}
          </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
          {done ? (
            <Button size="sm" render={<NextLink href={`/knowledge?collection=${encodeURIComponent(done)}`} />}>
              <Sparkles className="h-4 w-4 mr-1.5" />Open in Knowledge
            </Button>
          ) : (
            <Button size="sm" onClick={submit} disabled={busy || !table}>
              {busy ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : (sched ? <Clock className="h-4 w-4 mr-1.5" /> : <Sparkles className="h-4 w-4 mr-1.5" />)}
              {sched ? "Schedule" : "Ingest"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
