"use client"

import { useCallback, useEffect, useState } from "react"
import NextLink from "next/link"
import { CapabilityGate } from "@/lib/capabilities"
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
import { Search, Database, FolderOpen } from "lucide-react"

interface Table {
  name: string
  namespace: string
  catalog: string
  catalog_type: string
  table_type: string
  last_updated?: string
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
            variant={selectedNamespace === "all" ? "default" : "outline"}
            className="cursor-pointer px-3 py-1"
            onClick={() => setSelectedNamespace("all")}
          >
            All ({data?.tables.length || 0})
          </Badge>
          {data?.namespaces.map((namespace) => (
            <Badge
              key={namespace.name}
              variant={selectedNamespace === namespace.name ? "default" : "outline"}
              className="cursor-pointer px-3 py-1"
              onClick={() => setSelectedNamespace(namespace.name)}
            >
              {namespace.name} ({namespaceCounts?.[namespace.name] || 0})
            </Badge>
          ))}
        </div>
      </div>

      {/* Statistics Cards */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Total Tables</CardTitle>
              <Database className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="dp-num text-2xl font-bold tabular-nums">{data?.tables.length || 0}</div>
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
      </div>

      {/* Tables Grid */}
      <div>
        <h3 className="text-xl font-semibold mb-4 flex items-baseline gap-2">
          {selectedNamespace === "all" ? "All Tables" : `Tables in ${selectedNamespace}`}
          <span className="text-sm font-normal text-muted-foreground tabular-nums">
            {filteredTables?.length ?? 0} shown
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
                onSendToKnowledge={() => setSendTable(table)}
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
                  hint="Connect a data source and sync it from Ingestion, and Iceberg tables will appear here."
                  action={<Button size="sm" render={<NextLink href="/connectors" />}>Go to Ingestion</Button>}
                />
              ) : (
                <p className="py-8 text-center text-muted-foreground">No tables found matching your search criteria</p>
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
    setBusy(true); setErr(null); setMsg(null)
    try {
      // ensure collection exists (idempotent)
      await fetch("/api/ai/collections", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: target, description: `From ${table.namespace}.${table.name}` }) })
      const source = { type: "iceberg", schema: table.namespace, table: table.name, text_column: col }
      if (sched) {
        const r = await fetch(`/api/ai/collections/${encodeURIComponent(target)}/schedule`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ schedule: sched, source }) })
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
        const d = await r.json(); setMsg(`Schedule created: auto re-embeds every ${d.interval_minutes} min`)
      } else {
        const r = await fetch(`/api/ai/collections/${encodeURIComponent(target)}/ingest-source`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(source) })
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
        const d = await r.json(); setMsg(`${d.documents} docs → ${d.chunks} chunks ingested (${target})`)
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
          <Button size="sm" onClick={submit} disabled={busy || !table}>
            {busy ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : (sched ? <Clock className="h-4 w-4 mr-1.5" /> : <Sparkles className="h-4 w-4 mr-1.5" />)}
            {sched ? "Schedule" : "Ingest"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
