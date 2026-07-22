"use client"

import { useEffect, useRef, useState } from "react"
import { useParams } from "next/navigation"
import { CapabilityGate } from "@/lib/capabilities"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorBox, EmptyState } from "@/components/ui/error-box"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Table, Database, Eye, ExternalLink, Columns3, CheckCircle2 } from "lucide-react"
import { useRouter } from "next/navigation"

interface Column {
  name: string
  type: string
  nullable: boolean
  comment?: string
}

interface ColumnStat {
  column: string
  null_rate: number
  null_count: number
  distinct_count: number
  min?: string
  max?: string
}

interface PreviewData {
  columns: string[]
  rows: Record<string, unknown>[]
  total_returned: number
  column_stats: ColumnStat[]
}

interface TableDetail {
  name: string
  namespace: string
  table_type: string
  location: string
  columns: Column[]
  row_count?: number
  properties?: Record<string, unknown>
  last_updated?: string
}

function TableDetailPageInner() {
  const params = useParams()
  const router = useRouter()
  const namespace = params.namespace as string
  const tableName = params.table as string

  const [tableDetail, setTableDetail] = useState<TableDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const previewRequested = useRef(false)

  useEffect(() => {
    const fetchTableDetail = async () => {
      try {
        setLoading(true)
        setError(null)
        const res = await fetch(`/api/catalog/tables/${namespace}/${tableName}`)
        if (!res.ok) throw new Error(`Failed to fetch table: ${res.statusText}`)
        setTableDetail(await res.json())
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load table")
      } finally {
        setLoading(false)
      }
    }
    fetchTableDetail()
  }, [namespace, tableName])

  const loadPreview = async () => {
    if (preview) return
    setPreviewLoading(true)
    setPreviewError(null)
    try {
      const res = await fetch(`/api/catalog/tables/${namespace}/${tableName}/preview?limit=100`)
      if (!res.ok) throw new Error(`Preview request failed (HTTP ${res.status})`)
      setPreview(await res.json())
    } catch (requestError) {
      setPreview(null)
      setPreviewError(requestError instanceof Error ? requestError.message : "Failed to load table preview")
    } finally {
      setPreviewLoading(false)
    }
  }

  // The preview tab is the default, but Tabs only fires onValueChange on a
  // change — never for the initial value — so trigger the initial load here.
  // The ref guards against a double-invocation (e.g. React strict mode).
  useEffect(() => {
    if (previewRequested.current) return
    previewRequested.current = true
    void loadPreview()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace, tableName])

  const formatNumber = (num?: number) => {
    if (num == null) return "—"
    return num.toLocaleString()
  }

  // Overall fill rate (100 − mean null_rate) across profiled columns. Only meaningful
  // once the preview has actually returned stats — otherwise we leave it unknown rather
  // than implying a perfect 100%.
  const stats = preview?.column_stats ?? []
  const completeness =
    stats.length > 0
      ? Math.round((100 - stats.reduce((sum, s) => sum + s.null_rate, 0) / stats.length) * 10) / 10
      : null

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Skeleton className="h-5 w-[300px]" />
        <div className="space-y-2">
          <Skeleton className="h-8 w-[200px]" />
          <Skeleton className="h-4 w-[400px]" />
        </div>
        <Skeleton className="h-[600px]" />
      </div>
    )
  }

  if (error || !tableDetail) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink href="/dashboard">Home</BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbLink href="/catalog">Catalog</BreadcrumbLink>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <div role="alert" aria-live="polite">
          <ErrorBox msg={error || "Table not found"} />
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
            <BreadcrumbLink href="/catalog">Catalog</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{namespace}</BreadcrumbPage>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{tableName}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
              <Table className="h-5 w-5 text-muted-foreground" />
            </div>
            <h2 className="text-3xl font-bold tracking-tight">{tableDetail.name}</h2>
          </div>
          <div className="flex gap-2 mb-2">
            <Badge variant="secondary">{tableDetail.namespace}</Badge>
            <Badge variant="outline">{tableDetail.table_type}</Badge>
          </div>
          <p className="text-sm text-muted-foreground">{tableDetail.location}</p>
        </div>
      </div>

      {/* Statistics Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Row Count</CardTitle>
              <Database className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold dp-num">
              {formatNumber(tableDetail.row_count)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Columns</CardTitle>
              <Columns3 className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold dp-num">
              {formatNumber(tableDetail.columns.length)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Data Completeness</CardTitle>
              <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            {completeness == null ? (
              // Fail closed: no profiled stats yet → "—", not a fabricated 100%.
              <div className="text-2xl font-bold dp-num text-muted-foreground">—</div>
            ) : (
              <>
                <div
                  className="text-2xl font-bold dp-num"
                  style={{ color: completeness >= 95 ? "var(--dp-good)" : completeness >= 80 ? "var(--dp-warn)" : "var(--destructive)" }}
                >
                  {completeness}%
                </div>
                <div className="mt-2 h-1.5 rounded-full bg-muted overflow-hidden" role="presentation">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${completeness}%`,
                      backgroundColor: completeness >= 95 ? "var(--dp-good)" : completeness >= 80 ? "var(--dp-warn)" : "var(--destructive)",
                    }}
                  />
                </div>
                <p className="mt-1.5 text-xs text-muted-foreground">non-null across {stats.length} profiled column{stats.length === 1 ? "" : "s"}</p>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="preview" onValueChange={(v) => v === "preview" && loadPreview()}>
        <div className="flex items-center justify-between">
          <TabsList>
            <TabsTrigger value="preview" className="gap-1.5"><Eye className="h-3.5 w-3.5" />Preview</TabsTrigger>
            <TabsTrigger value="schema">Schema</TabsTrigger>
            <TabsTrigger value="metadata">Metadata</TabsTrigger>
          </TabsList>
          <button
            onClick={() => router.push(`/query?sql=${encodeURIComponent(`SELECT * FROM ${namespace}.${tableName} LIMIT 100`)}`)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ExternalLink className="h-3.5 w-3.5" />Open in Query Lab
          </button>
        </div>

        {/* Preview Tab */}
        <TabsContent value="preview" className="space-y-4">
          {/* Column stats */}
          {stats.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Column Statistics</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b bg-muted/40">
                        <th className="px-4 py-2 text-left font-medium">Column</th>
                        <th className="px-4 py-2 text-left font-medium w-[34%]">Null rate</th>
                        <th className="px-4 py-2 text-right font-medium">Distinct</th>
                        <th className="px-4 py-2 text-left font-medium">Min</th>
                        <th className="px-4 py-2 text-left font-medium">Max</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.map(s => {
                        // Encode null density as form + colour: green ≤5%, amber ≤20%, red above.
                        const tone = s.null_rate <= 5 ? "var(--dp-good)" : s.null_rate <= 20 ? "var(--dp-warn)" : "var(--destructive)"
                        return (
                          <tr key={s.column} className="border-b last:border-0 hover:bg-muted/20">
                            <td className="px-4 py-1.5 font-mono whitespace-nowrap">{s.column}</td>
                            <td className="px-4 py-1.5">
                              <div className="flex items-center gap-2">
                                <div
                                  className="h-1.5 flex-1 min-w-[48px] rounded-full bg-muted overflow-hidden"
                                  role="img"
                                  aria-label={`${s.null_rate}% null (${formatNumber(s.null_count)} rows)`}
                                >
                                  <div
                                    className="h-full rounded-full"
                                    style={{ width: `${Math.min(s.null_rate, 100)}%`, backgroundColor: tone }}
                                  />
                                </div>
                                <span className="tabular-nums text-right w-10 shrink-0" style={{ color: s.null_rate > 20 ? tone : undefined }}>
                                  {s.null_rate}%
                                </span>
                              </div>
                            </td>
                            <td className="px-4 py-1.5 text-right tabular-nums text-muted-foreground">{s.distinct_count.toLocaleString()}</td>
                            <td className="px-4 py-1.5 font-mono text-muted-foreground truncate max-w-[160px]">{s.min ?? "—"}</td>
                            <td className="px-4 py-1.5 font-mono text-muted-foreground truncate max-w-[160px]">{s.max ?? "—"}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Data rows */}
          <Card>
            <CardHeader className="pb-2 flex flex-row items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                Data Preview
                {preview && preview.rows.length > 0 && (
                  // Be explicit that this is a capped sample, not the full table.
                  <Badge variant="secondary" className="font-normal tabular-nums">
                    first {preview.total_returned.toLocaleString()} rows
                  </Badge>
                )}
              </CardTitle>
              {!preview && !previewLoading && !previewError && (
                <button onClick={loadPreview} className="text-xs text-primary hover:underline">Load preview</button>
              )}
            </CardHeader>
            <CardContent className="p-0">
              {previewLoading ? (
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                  <div className="h-4 w-4 border-2 border-primary border-t-transparent rounded-full animate-spin mr-2" />
                  Loading…
                </div>
              ) : previewError ? (
                <div className="p-4" role="alert" aria-live="polite">
                  <ErrorBox
                    msg={previewError}
                    action={<button onClick={loadPreview} className="text-xs font-medium underline">Retry preview</button>}
                  />
                </div>
              ) : !preview ? (
                <EmptyState
                  icon={Eye}
                  title="No preview loaded"
                  hint="Fetch the first 100 rows to inspect this table's data."
                  action={
                    <button onClick={loadPreview} className="mt-1 text-xs text-primary hover:underline font-medium">Load preview</button>
                  }
                />
              ) : preview.rows.length === 0 ? (
                <EmptyState icon={Table} title="Table is empty" hint="No rows were returned for this table." />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b bg-muted/40">
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground w-10 sticky left-0 bg-muted/40">#</th>
                        {preview.columns.map(col => (
                          <th key={col} className="px-3 py-2 text-left font-medium font-mono whitespace-nowrap">{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {preview.rows.map((row, i) => (
                        <tr key={i} className="border-b last:border-0 hover:bg-muted/30 odd:bg-muted/[0.04]">
                          <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground/50 select-none">{i + 1}</td>
                          {preview.columns.map(col => (
                            <td key={col} className="px-3 py-1.5 font-mono text-muted-foreground whitespace-nowrap max-w-[200px] truncate">
                              {row[col] === null || row[col] === undefined
                                ? <span className="text-muted-foreground/40 italic">null</span>
                                : String(row[col])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Schema Tab */}
        <TabsContent value="schema" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Table Schema</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="rounded-md border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/50">
                      <th className="p-3 text-left font-medium">Column Name</th>
                      <th className="p-3 text-left font-medium">Data Type</th>
                      <th className="p-3 text-left font-medium">Nullable</th>
                      <th className="p-3 text-left font-medium">Comment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableDetail.columns.map((column, index) => (
                      <tr key={index} className="border-b last:border-b-0">
                        <td className="p-3 font-mono">{column.name}</td>
                        <td className="p-3">
                          <Badge variant="outline">{column.type}</Badge>
                        </td>
                        <td className="p-3">
                          <Badge variant={column.nullable ? "secondary" : "outline"}>
                            {column.nullable ? "Yes" : "No"}
                          </Badge>
                        </td>
                        <td className="p-3 text-muted-foreground">
                          {column.comment || "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Metadata Tab */}
        <TabsContent value="metadata" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Table Metadata</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div>
                  <p className="text-sm font-medium mb-1">Table Type</p>
                  <Badge>{tableDetail.table_type}</Badge>
                </div>
                <div>
                  <p className="text-sm font-medium mb-1">Location</p>
                  <p className="text-sm text-muted-foreground font-mono break-all">
                    {tableDetail.location}
                  </p>
                </div>
                {tableDetail.last_updated && (
                  <div>
                    <p className="text-sm font-medium mb-1">Last Updated</p>
                    <p className="text-sm text-muted-foreground">
                      {new Date(tableDetail.last_updated).toLocaleString()}
                    </p>
                  </div>
                )}
                {tableDetail.properties && Object.keys(tableDetail.properties).length > 0 && (
                  <div>
                    <p className="text-sm font-medium mb-2">Properties</p>
                    <pre className="rounded-md bg-muted p-4 text-xs overflow-auto">
                      {JSON.stringify(tableDetail.properties, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default function TableDetailPage() {
  return (
    <CapabilityGate capability="catalog">
      <TableDetailPageInner />
    </CapabilityGate>
  )
}
