"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Table, Database, Eye, ExternalLink } from "lucide-react"
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
  rows: Record<string, any>[]
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
  properties?: Record<string, any>
  last_updated?: string
}

export default function TableDetailPage() {
  const params = useParams()
  const router = useRouter()
  const namespace = params.namespace as string
  const tableName = params.table as string

  const [tableDetail, setTableDetail] = useState<TableDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

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
    try {
      const res = await fetch(`/api/catalog/tables/${namespace}/${tableName}/preview?limit=100`)
      if (res.ok) setPreview(await res.json())
    } catch { /* non-critical */ }
    finally { setPreviewLoading(false) }
  }

  const formatNumber = (num?: number) => {
    if (!num) return "0"
    return num.toLocaleString()
  }

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

        <Card>
          <CardContent className="py-8 text-center">
            <p className="text-destructive">{error || "Table not found"}</p>
          </CardContent>
        </Card>
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
          {(preview?.column_stats ?? []).length > 0 && (
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
                        <th className="px-4 py-2 text-right font-medium">Null %</th>
                        <th className="px-4 py-2 text-right font-medium">Distinct</th>
                        <th className="px-4 py-2 text-left font-medium">Min</th>
                        <th className="px-4 py-2 text-left font-medium">Max</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview!.column_stats.map(s => (
                        <tr key={s.column} className="border-b last:border-0 hover:bg-muted/20">
                          <td className="px-4 py-1.5 font-mono">{s.column}</td>
                          <td className="px-4 py-1.5 text-right">
                            <span className={s.null_rate > 20 ? "text-[var(--dp-warn)]" : "text-muted-foreground"}>
                              {s.null_rate}%
                            </span>
                          </td>
                          <td className="px-4 py-1.5 text-right text-muted-foreground">{s.distinct_count.toLocaleString()}</td>
                          <td className="px-4 py-1.5 font-mono text-muted-foreground truncate max-w-[160px]">{s.min ?? "—"}</td>
                          <td className="px-4 py-1.5 font-mono text-muted-foreground truncate max-w-[160px]">{s.max ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Data rows */}
          <Card>
            <CardHeader className="pb-2 flex flex-row items-center justify-between">
              <CardTitle className="text-sm">
                {preview ? `Top ${preview.total_returned} rows` : "Data Preview"}
              </CardTitle>
              {!preview && !previewLoading && (
                <button onClick={loadPreview} className="text-xs text-primary hover:underline">Load preview</button>
              )}
            </CardHeader>
            <CardContent className="p-0">
              {previewLoading ? (
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                  <div className="h-4 w-4 border-2 border-primary border-t-transparent rounded-full animate-spin mr-2" />
                  Loading…
                </div>
              ) : !preview ? (
                <div className="text-center py-12 text-sm text-muted-foreground">Click "Load preview" to fetch data</div>
              ) : preview.rows.length === 0 ? (
                <div className="text-center py-12 text-sm text-muted-foreground">Table is empty</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b bg-muted/40">
                        {preview.columns.map(col => (
                          <th key={col} className="px-3 py-2 text-left font-medium font-mono whitespace-nowrap">{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {preview.rows.map((row, i) => (
                        <tr key={i} className="border-b last:border-0 hover:bg-muted/20">
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
