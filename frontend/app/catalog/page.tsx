"use client"

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import NextLink from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import dynamic from "next/dynamic"
import { Search, Database, Share2 } from "lucide-react"
import { CapabilityGate } from "@/lib/capabilities"
import { getUser } from "@/lib/auth"
import { usePermissions } from "@/lib/permissions"
import { permissionState } from "@/lib/permission-state"
import { PermissionUnknown } from "@/components/ui/permission-state"
import { mayIngest } from "@/lib/knowledge-actions"
import { ErrorBox, EmptyState } from "@/components/ui/error-box"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Button, buttonVariants } from "@/components/ui/button"
import { PageHeader } from "@/components/ui/page-header"
import { ExplainRail, RailSection } from "@/components/ui/explain-rail"
import { SendToKnowledgePanel, TableRail, type CatalogTable } from "@/components/catalog/table-rail"
import { browserQuery, browserStateFrom, catalogTypeOf, inChip, isSourceKind, namespaceChips, type RegistryEntry } from "@/lib/catalog-view"
import { CatalogKindBadge } from "@/components/catalog/kind-badge"
import { findNodeId, soleCatalog, type RelGraph } from "@/lib/relationship-view"

// reactflow pulls in a chunk we should not pay for unless the map is opened.
const RelationshipGraph = dynamic(
  () => import("@/components/catalog/relationship-graph").then(m => m.RelationshipGraph),
  { ssr: false },
)

interface Table extends CatalogTable { catalog_type: string }
interface NamespaceInfo { name: string; catalog?: string }
interface Registry extends RegistryEntry { is_default?: boolean; enabled?: boolean }
interface CatalogData { tables: Table[]; namespaces: NamespaceInfo[]; registry: Registry[] }

const TYPE_LABEL: Record<string, string> = { managed: "Managed", external: "External", source: "Source database", foreign: "Foreign" }

const tableKey = (t: CatalogTable) => `${t.catalog}\u0000${t.namespace}\u0000${t.name}`

/** Browse every table the engine can query: catalog and namespace on the left, the
 *  tables in the middle, the selected table on the right. It opened on a relationship
 *  graph that filled the screen with "Finding relationships…", embedded the admin
 *  Data catalogs panel, and showed tables as cards below the fold. */
function CatalogPageInner() {
  const [data, setData] = useState<CatalogData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Catalog, namespace, search and the selected table start from, and are kept in, the
  // URL — a view can be shared, reloaded, and returned to from a table's page.
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const [initial] = useState(() => browserStateFrom(params))
  const [query, setQuery] = useState(initial.query)
  const [catalog, setCatalog] = useState(initial.catalog)
  const [chip, setChip] = useState(initial.chip)
  const [selected, setSelected] = useState<string | null>(initial.selected)
  useEffect(() => {
    const next = browserQuery({ catalog, chip, query, selected })
    if (next !== (params.toString() ? `?${params.toString()}` : "")) router.replace(`${pathname}${next}`, { scroll: false })
  }, [catalog, chip, query, selected, params, pathname, router])
  const [sending, setSending] = useState(false)
  const [showMap, setShowMap] = useState(false)
  const [showEmpty, setShowEmpty] = useState(false)
  const [graph, setGraph] = useState<RelGraph | null>(null)

  // Send to Knowledge drives ingest-source / schedule: knowledge:write plus
  // ai:generate, which mayIngest checks — the same decision the Knowledge page makes.
  const viewer = getUser()
  const { role, permissions, loaded: permsLoaded, error: permsError, refetch: refetchPerms } = usePermissions()
  const canSend = !!viewer && mayIngest({ owner_id: viewer.id }, { id: viewer.id, role, permissions })
  const sendAccess = permissionState({ loaded: permsLoaded, error: permsError, allowed: canSend })

  const fetchData = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [tablesRes, namespacesRes, registryRes] = await Promise.all([
        fetch("/api/catalog/tables"),
        fetch("/api/catalog/namespaces"),
        fetch("/api/catalogs").catch(() => null),
      ])
      if (!tablesRes.ok || !namespacesRes.ok) {
        throw new Error(`The catalog could not be read (tables HTTP ${tablesRes.status}, namespaces HTTP ${namespacesRes.status})`)
      }
      const tablesData = await tablesRes.json()
      const namespacesData = await namespacesRes.json()
      const registryData = registryRes?.ok ? await registryRes.json().catch(() => ({})) : {}
      setData({ tables: tablesData.tables ?? [], namespaces: namespacesData.namespaces ?? [], registry: registryData.catalogs ?? [] })
    } catch (e) {
      setData(null)
      setError(e instanceof Error ? e.message : "The catalog could not be read")
    } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const t = window.setTimeout(() => void fetchData(), 0)
    return () => window.clearTimeout(t)
  }, [fetchData])

  // Query history, for "Joined with" in the rail. Advisory: a failure leaves it empty.
  useEffect(() => {
    let cancelled = false
    fetch("/api/catalog/relationships?days=30")
      .then(r => (r.ok ? r.json() : { nodes: [], edges: [] }))
      .then((g: RelGraph) => { if (!cancelled) setGraph(g) })
      .catch(() => { if (!cancelled) setGraph({ nodes: [], edges: [] }) })
    return () => { cancelled = true }
  }, [])

  const tables = useMemo(() => data?.tables ?? [], [data])
  const registry = useMemo(() => data?.registry ?? [], [data])
  const catalogs = useMemo(() => {
    // Every enabled lake catalog is listed, even with no tables yet (an empty Polaris
    // catalog is still a place a sync or an export can land).
    const engines = [...new Set([...tables.map(t => t.catalog),
      ...registry.filter(r => r.enabled !== false && !isSourceKind(r.kind)).map(r => r.engine_catalog)])]
    return engines.map(e => {
      const r = registry.find(x => x.engine_catalog === e)
      // Named as SQL names it; the kind badge says what it is (Settings keeps the registry name).
      return { engine: e, kind: r?.kind ?? null, isDefault: !!r?.is_default, source: isSourceKind(r?.kind),
               count: tables.filter(t => t.catalog === e).length }
    }).sort((a, b) => Number(b.isDefault) - Number(a.isDefault) || a.engine.localeCompare(b.engine))
  }, [tables, registry])

  const inCatalog = useCallback((t: { catalog?: string }) => catalog === "all" || (t.catalog ?? "") === catalog, [catalog])
  const chips = useMemo(() => namespaceChips(tables.filter(inCatalog), (data?.namespaces ?? []).filter(inCatalog)), [tables, data, inCatalog])
  const scoped = tables.filter(t => inCatalog(t) && inChip(chip, t))
  const needle = query.trim().toLowerCase()
  const shown = needle ? scoped.filter(t => t.name.toLowerCase().includes(needle) || t.namespace.toLowerCase().includes(needle)) : scoped
  const current = tables.find(t => tableKey(t) === selected) ?? null
  const typeOf = (t: Table) => catalogTypeOf(t, registry)
  const sole = graph ? soleCatalog(graph) : null
  const nodeFor = (t: Table) => {
    if (!graph) return null
    const r = registry.find(x => x.engine_catalog === t.catalog)
    return findNodeId(graph, [t.catalog, r?.name ?? ""], t.namespace, t.name)
  }

  const pickCatalog = (c: string) => { setCatalog(c); setChip("all"); setSelected(null); setSending(false) }
  const pickChip = (k: string) => { setChip(k); setSelected(null); setSending(false) }
  const select = (t: Table) => { setSelected(tableKey(t)); setSending(false) }

  const header = (
    <PageHeader
      title="Catalog"
      description="Every table the lakehouse can query, by catalog and namespace."
      actions={
        <>
          <Button size="sm" variant="outline" aria-expanded={showMap} onClick={() => setShowMap(v => !v)}>
            <Share2 className="mr-1.5 h-3.5 w-3.5" />{showMap ? "Hide relationship map" : "Relationship map"}
          </Button>
          {(role === "admin" || permissions.has("catalog:write")) && (
            <NextLink href="/settings?tab=catalogs" className={buttonVariants({ size: "sm", variant: "outline" })}>
              {role === "admin" ? "Manage catalogs" : "Export and mirrors"}</NextLink>
          )}
        </>
      }
    />
  )

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        {header}
        <div className="flex gap-5">
          <Skeleton className="h-[420px] w-56" />
          <Skeleton className="h-[420px] flex-1" />
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        {header}
        <div role="alert" aria-live="polite">
          <ErrorBox msg={error ?? "The catalog could not be read"} action={<Button size="sm" variant="outline" onClick={fetchData}>Retry</Button>} />
        </div>
      </div>
    )
  }

  const navItem = (key: string, label: string, count: number, active: boolean, onClick: () => void, mono = false, extra?: React.ReactNode) => (
    <button key={key} type="button" onClick={onClick} aria-current={active ? "true" : undefined}
            className={`flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors ${active ? "bg-primary/10 font-semibold text-primary" : "hover:bg-muted"}`}>
      <span className="flex min-w-0 items-center gap-1.5">
        <span className={`truncate ${mono ? "font-mono text-xs" : ""}`}>{label}</span>
        {extra}
      </span>
      <span className="dp-num shrink-0 text-xs text-muted-foreground">{count}</span>
    </button>
  )
  const catalogItem = (c: (typeof catalogs)[number]) => navItem(c.engine, c.engine, c.count, catalog === c.engine, () => pickCatalog(c.engine), true,
    <>{!c.source && <CatalogKindBadge kind={c.kind} />}{c.isDefault && <span className="shrink-0 text-2xs font-normal text-muted-foreground">default</span>}</>)
  const lakeCatalogs = catalogs.filter(c => !c.source)
  const sourceCatalogs = catalogs.filter(c => c.source)
  const fullChips = chips.filter(c => c.count > 0)
  const emptyChips = chips.filter(c => c.count === 0)

  const typeCounts = Object.entries(tables.reduce<Record<string, number>>((acc, t) => {
    const k = typeOf(t); acc[k] = (acc[k] ?? 0) + 1; return acc
  }, {})).sort((a, b) => b[1] - a[1])

  return (
    <div className="mx-auto max-w-[1400px] flex-1 space-y-4 p-8 pt-6">
      {header}
      {sendAccess === "unknown" && <PermissionUnknown onRetry={refetchPerms} />}

      {showMap && (
        <section aria-label="Relationship map" className="rounded-xl border bg-card p-4">
          <RelationshipGraph days={30} />
        </section>
      )}

      {tables.length === 0 ? (
        <div className="rounded-xl border bg-card">
          <EmptyState icon={Database} title="No tables yet"
            hint="Add a source and sync it, and its tables appear here."
            action={<NextLink href="/connectors" className={buttonVariants({ size: "sm" })}>Go to Sources</NextLink>} />
        </div>
      ) : (
        <div className="flex flex-wrap items-start gap-5">
          <nav aria-label="Catalogs and namespaces" className="w-full space-y-4 lg:w-56 lg:shrink-0">
            {catalogs.length > 1 && (
              <div className="space-y-1">
                {navItem("all", "All catalogs", tables.length, catalog === "all", () => pickCatalog("all"))}
                {lakeCatalogs.length > 0 && <p className="px-2.5 pt-2 text-xs font-medium text-muted-foreground">Lakehouse</p>}
                {lakeCatalogs.map(catalogItem)}
                {sourceCatalogs.length > 0 && (
                  <p className="px-2.5 pt-2 text-xs font-medium text-muted-foreground">Source databases <span className="font-normal">· read live</span></p>
                )}
                {sourceCatalogs.map(catalogItem)}
              </div>
            )}
            <div className="space-y-1">
              <p className="px-2.5 text-xs font-medium text-muted-foreground">Namespace</p>
              {navItem("all", "All", tables.filter(inCatalog).length, chip === "all", () => pickChip("all"))}
              {fullChips.map(c => navItem(c.key, c.label, c.count, chip === c.key, () => pickChip(c.key), true))}
              {emptyChips.length > 0 && (showEmpty || emptyChips.some(c => c.key === chip)
                ? emptyChips.map(c => navItem(c.key, c.label, c.count, chip === c.key, () => pickChip(c.key), true))
                : (
                  <button type="button" onClick={() => setShowEmpty(true)}
                          className="px-2.5 py-1 text-xs text-primary hover:underline focus-visible:underline focus-visible:outline-none">
                    Show {emptyChips.length} empty namespace{emptyChips.length === 1 ? "" : "s"}
                  </button>
                ))}
            </div>
          </nav>

          <section aria-label="Tables" className="min-w-0 flex-[3_1_420px] space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <div className="relative min-w-[220px] flex-1">
                <Search aria-hidden className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input aria-label="Search tables" placeholder="Search tables" value={query} onChange={e => setQuery(e.target.value)} className="pl-8" />
              </div>
              <p className="dp-num text-xs text-muted-foreground">{shown.length === scoped.length ? `${shown.length} tables` : `${shown.length} of ${scoped.length} tables`}</p>
            </div>
            {shown.length === 0 ? (
              <div className="rounded-xl border bg-card">
                <EmptyState icon={Search} title="No tables match"
                  hint={`Nothing in this namespace matches "${query}".`}
                  action={<Button size="sm" variant="outline" onClick={() => setQuery("")}>Clear search</Button>} />
              </div>
            ) : (
              <div className="overflow-x-auto rounded-xl border bg-card">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
                      <th className="px-4 py-2 font-medium">Table</th>
                      <th className="px-4 py-2 font-medium">Namespace</th>
                      <th className="px-4 py-2 pr-6 font-medium">Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map(t => {
                      const on = tableKey(t) === selected
                      return (
                        <tr key={tableKey(t)} aria-selected={on}
                            className={`cursor-pointer border-b last:border-0 ${on ? "bg-primary/5" : "hover:bg-muted/30"}`}
                            onClick={() => select(t)}>
                          <td className="px-4 py-2">
                            <button type="button" className="text-left font-medium hover:underline focus-visible:underline focus-visible:outline-none"
                                    onClick={e => { e.stopPropagation(); select(t) }}>{t.name}</button>
                          </td>
                          <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                            {catalogs.length > 1 && catalog === "all" ? `${t.catalog}.` : ""}{t.namespace}
                          </td>
                          <td className="px-4 py-2 pr-6 text-xs">{TYPE_LABEL[typeOf(t)] ?? typeOf(t)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {current && sending ? (
            <SendToKnowledgePanel key={tableKey(current)} table={current} onClose={() => setSending(false)} />
          ) : current ? (
            <TableRail key={tableKey(current)} table={current} typeLabel={TYPE_LABEL[typeOf(current)] ?? typeOf(current)}
              catalogKind={registry.find(r => r.engine_catalog === current.catalog)?.kind}
              graph={graph} graphNode={nodeFor(current)} sole={sole}
              canSend={sendAccess === "allowed"} onSend={() => setSending(true)} onClose={() => setSelected(null)} />
          ) : (
            <ExplainRail label="About the catalog">
              <RailSection title={`${tables.length} tables in ${catalogs.length} catalog${catalogs.length === 1 ? "" : "s"}`}>
                <ul className="space-y-0.5">
                  {typeCounts.map(([k, n]) => <li key={k} className="flex justify-between"><span>{TYPE_LABEL[k] ?? k}</span><span className="dp-num text-foreground">{n}</span></li>)}
                </ul>
              </RailSection>
              <RailSection title="Choose a table">
                Its row count, columns, and the tables people join it to appear here, with Open in Analytics
                {sendAccess === "allowed" ? " and Send to Knowledge." : "."}
              </RailSection>
              {typeCounts.some(([k]) => k === "source") && (
                <RailSection title="Source database tables">
                  Read live from the source through the engine, not copied. Sync one from Sources to keep a copy in the lake.
                </RailSection>
              )}
              {sendAccess === "denied" && (
                <p className="text-xs text-muted-foreground">Sending a table to Knowledge needs knowledge:write and ai:generate.</p>
              )}
              {role === "admin" && (
                <p className="text-xs text-muted-foreground">Which catalogs are read, and exports between them, are set in <NextLink href="/settings?tab=catalogs" className="text-primary hover:underline">Settings → Data catalogs</NextLink>.</p>
              )}
            </ExplainRail>
          )}
        </div>
      )}
    </div>
  )
}

export default function CatalogPage() {
  return (
    <CapabilityGate capability="catalog">
      <Suspense fallback={null}><CatalogPageInner /></Suspense>
    </CapabilityGate>
  )
}
