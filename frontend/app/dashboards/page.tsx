"use client"

import { useEffect, useState, useCallback } from "react"
import { ErrorBox } from "@/components/ui/error-box"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  BarChart3, Eye, Clock, Search, Globe, Lock,
  LineChart, PieChart, TrendingUp, AreaChart, Table, Plus, RefreshCw,
} from "lucide-react"
import { dashboardApi, queryApi, Dashboard } from "@/lib/api"
import { formatDistanceToNow } from "date-fns"
import { ChartRenderer } from "@/components/query/chart-renderer"

interface QueryResult { columns: string[]; rows: any[][] }
type PreviewMap = Record<string, { data: any[]; error?: string }>

export default function DashboardsPage() {
  const router = useRouter()
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [previews, setPreviews] = useState<PreviewMap>({})
  const [loadingPreviews, setLoadingPreviews] = useState(false)

  useEffect(() => { loadDashboards() }, [])

  const loadDashboards = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await dashboardApi.list()
      setDashboards(data)
      // Fetch chart data for all dashboards in parallel
      fetchPreviews(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboards")
    } finally {
      setLoading(false)
    }
  }

  const fetchPreviews = useCallback(async (list: Dashboard[]) => {
    setLoadingPreviews(true)
    const results = await Promise.allSettled(
      list.map(async (d) => {
        try {
          const result = await queryApi.execute(d.query_text, false)
          const rows = result.rows ?? []
          const cols = result.columns ?? []
          const data = rows.map((row: any[]) => {
            const obj: any = {}
            cols.forEach((col: string, i: number) => { obj[col] = row[i] })
            return obj
          })
          return { id: d.id, data }
        } catch {
          return { id: d.id, data: [] }
        }
      })
    )
    const map: PreviewMap = {}
    results.forEach((r) => {
      if (r.status === "fulfilled") map[r.value.id] = { data: r.value.data }
    })
    setPreviews(map)
    setLoadingPreviews(false)
  }, [])

  const filteredDashboards = dashboards.filter((d) =>
    d.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    d.description?.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const getChartIcon = (chartType: string) => {
    switch (chartType) {
      case "line":  return <LineChart  className="h-4 w-4 text-blue-500" />
      case "bar":   return <BarChart3  className="h-4 w-4 text-green-500" />
      case "area":  return <AreaChart  className="h-4 w-4 text-purple-500" />
      case "pie":   return <PieChart   className="h-4 w-4 text-orange-500" />
      case "table": return <Table      className="h-4 w-4 text-gray-500" />
      default:      return <TrendingUp className="h-4 w-4 text-blue-500" />
    }
  }

  return (
    <div className="flex-1 space-y-5 px-6 py-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Dashboards</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Saved SQL queries visualised as charts
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5"
            onClick={loadDashboards} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button size="sm" className="h-8 text-xs gap-1.5"
            onClick={() => router.push("/query")}>
            <Plus className="h-3.5 w-3.5" />
            New in SQL Lab
          </Button>
        </div>
      </div>

      {/* Stats strip */}
      {!loading && !error && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Total",   value: dashboards.length,                                                 icon: BarChart3  },
            { label: "Public",  value: dashboards.filter(d => d.is_public).length,                       icon: Globe      },
            { label: "Private", value: dashboards.filter(d => !d.is_public).length,                      icon: Lock       },
            { label: "Types",   value: new Set(dashboards.map(d => d.chart_config.chartType)).size,       icon: PieChart   },
          ].map(({ label, value, icon: Icon }) => (
            <Card key={label}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-muted-foreground">{label}</span>
                  <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                </div>
                <div className="text-2xl font-bold">{value}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Search */}
      <div className="relative max-w-xs">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          placeholder="Search dashboards…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-8 h-8 text-sm"
        />
      </div>

      {/* Loading */}
      {loading && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardHeader><Skeleton className="h-5 w-3/4" /></CardHeader>
              <CardContent><Skeleton className="h-[220px] w-full" /></CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <ErrorBox msg={error}
          action={<Button onClick={loadDashboards} variant="outline" size="sm">Try Again</Button>} />
      )}

      {/* Empty */}
      {!loading && !error && dashboards.length === 0 && (
        <Card>
          <CardContent className="py-16 text-center space-y-3">
            <BarChart3 className="h-10 w-10 mx-auto text-muted-foreground/30" />
            <div>
              <p className="font-medium text-sm">No dashboards yet</p>
              <p className="text-xs text-muted-foreground mt-1">
                Run a query in SQL Lab and click "Save as Dashboard"
              </p>
            </div>
            <Button size="sm" onClick={() => router.push("/query")}>
              Go to SQL Lab
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Dashboard cards with inline charts */}
      {!loading && !error && filteredDashboards.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filteredDashboards.map((dashboard) => {
            const preview = previews[dashboard.id]
            const chartType = dashboard.chart_config.chartType
            return (
              <Card
                key={dashboard.id}
                className="hover:shadow-md transition-shadow cursor-pointer group"
                onClick={() => router.push(`/dashboards/${dashboard.id}`)}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      {getChartIcon(chartType)}
                      <CardTitle className="text-sm truncate">{dashboard.name}</CardTitle>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                        {chartType}
                      </Badge>
                      {dashboard.is_public
                        ? <Globe className="h-3.5 w-3.5 text-blue-400" />
                        : <Lock className="h-3.5 w-3.5 text-muted-foreground/40" />}
                    </div>
                  </div>
                  {dashboard.description && (
                    <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">
                      {dashboard.description}
                    </p>
                  )}
                </CardHeader>

                <CardContent className="pt-0 pb-3">
                  {/* Mini chart preview */}
                  <div className="rounded border bg-muted/20 overflow-hidden mb-3" style={{ height: 200 }}>
                    {!preview ? (
                      <div className="h-full flex items-center justify-center">
                        <div className="h-4 w-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
                      </div>
                    ) : preview.data.length === 0 ? (
                      <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
                        No data
                      </div>
                    ) : chartType === "table" ? (
                      <div className="overflow-auto h-full p-2">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b">
                              {Object.keys(preview.data[0]).map(k => (
                                <th key={k} className="text-left px-1 py-0.5 font-medium text-muted-foreground">{k}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {preview.data.slice(0, 5).map((row, i) => (
                              <tr key={i} className="border-b last:border-0">
                                {Object.values(row).map((v: any, j) => (
                                  <td key={j} className="px-1 py-0.5 text-muted-foreground">{String(v ?? "")}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="pointer-events-none scale-[0.85] origin-top-left" style={{ width: "118%", height: "118%" }}>
                        <ChartRenderer
                          data={preview.data}
                          chartType={chartType as any}
                          xAxis={dashboard.chart_config.xAxis || ""}
                          yAxis={dashboard.chart_config.yAxis || ""}
                          chartConfig={{
                            colors: dashboard.chart_config.colors,
                            showGrid: false,
                            showLegend: false,
                          }}
                        />
                      </div>
                    )}
                  </div>

                  {/* Footer */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      {formatDistanceToNow(new Date(dashboard.updated_at), { addSuffix: true })}
                    </div>
                    <Button variant="ghost" size="sm"
                      className="h-6 text-[10px] px-2 opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={(e) => { e.stopPropagation(); router.push(`/dashboards/${dashboard.id}`) }}>
                      <Eye className="h-3 w-3 mr-1" />Open
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* No search results */}
      {!loading && !error && dashboards.length > 0 && filteredDashboards.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center border rounded-lg bg-muted/20">
          <Search className="h-8 w-8 text-muted-foreground/30 mb-2" />
          <p className="text-sm text-muted-foreground">No dashboards match "{searchQuery}"</p>
        </div>
      )}
    </div>
  )
}
