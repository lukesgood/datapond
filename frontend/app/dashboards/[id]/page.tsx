"use client"

import { useCallback, useEffect, useState } from "react"
import { useRouter, useParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import {
  Edit2,
  Trash2,
  Share2,
  RefreshCw,
  Globe,
  Lock,
  Loader2,
  ArrowLeft,
  Check,
  X,
  AlertTriangle,
} from "lucide-react"
import { dashboardApi, queryApi, Dashboard, type QueryResult } from "@/lib/api"
import { ChartRenderer } from "@/components/query/chart-renderer"
import { QueryResults } from "@/components/query/query-results"
import { useToast } from "@/lib/toast"
import { useConfirm } from "@/lib/confirm"
import { formatDistanceToNow } from "date-fns"

export default function DashboardViewPage() {
  const router = useRouter()
  const params = useParams()
  const { toast } = useToast()
  const confirm = useConfirm()
  const dashboardId = params.id as string

  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [executing, setExecuting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [execError, setExecError] = useState<string | null>(null)

  // Edit mode
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState("")
  const [editDescription, setEditDescription] = useState("")
  const [editIsPublic, setEditIsPublic] = useState(false)
  const [saving, setSaving] = useState(false)

  // Delete confirmation
  const [deleting, setDeleting] = useState(false)

  const executeQuery = useCallback(async (queryText: string) => {
    if (!queryText) return

    try {
      setExecuting(true)
      setExecError(null)
      const result = await queryApi.execute(queryText)
      setQueryResult(result)
    } catch (err) {
      // Fail closed: surface the failure in-panel and drop stale results so a
      // broken refresh can't keep rendering an old chart as if it were current.
      const msg = err instanceof Error ? err.message : "Query execution failed"
      setExecError(msg)
      setQueryResult(null)
      toast(msg, "error")
    } finally {
      setExecuting(false)
    }
  }, [toast])

  const loadDashboard = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await dashboardApi.get(dashboardId)
      setDashboard(data)
      setEditName(data.name)
      setEditDescription(data.description || "")
      setEditIsPublic(data.is_public)
      // Auto-execute query on load
      await executeQuery(data.query_text)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard")
    } finally {
      setLoading(false)
    }
  }, [dashboardId, executeQuery])

  useEffect(() => {
    if (!dashboardId) return
    const timer = window.setTimeout(() => { void loadDashboard() }, 0)
    return () => window.clearTimeout(timer)
  }, [dashboardId, loadDashboard])

  const handleSave = async () => {
    if (!dashboard) return

    try {
      setSaving(true)
      const updated = await dashboardApi.update(dashboardId, {
        name: editName.trim(),
        description: editDescription.trim() || undefined,
        is_public: editIsPublic,
      })
      setDashboard(updated)
      setIsEditing(false)
      toast("Dashboard updated successfully!", "success")
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to update dashboard", "error")
    } finally {
      setSaving(false)
    }
  }

  const handleCancelEdit = () => {
    if (dashboard) {
      setEditName(dashboard.name)
      setEditDescription(dashboard.description || "")
      setEditIsPublic(dashboard.is_public)
      setIsEditing(false)
    }
  }

  const handleDelete = async () => {
    if (!dashboard) return
    const ok = await confirm({
      title: "Delete Dashboard",
      message: `This deletes the "${dashboard.name}" dashboard and cannot be undone.`,
      destructive: true,
      confirmText: "Delete",
    })
    if (!ok) return
    try {
      setDeleting(true)
      await dashboardApi.delete(dashboardId)
      toast("Dashboard deleted successfully!", "success")
      router.push("/query?tab=dashboards")
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to delete dashboard", "error")
      setDeleting(false)
    }
  }

  const handleShare = () => {
    if (!dashboard) return
    if (!dashboard.is_public) {
      toast("This dashboard is private. Make it public to share.", "info")
      return
    }
    const url = window.location.href
    navigator.clipboard.writeText(url)
    toast("Dashboard link copied to clipboard!", "success")
  }

  const getChartData = () => {
    if (!queryResult || !queryResult.rows || queryResult.rows.length === 0) return []

    return queryResult.rows.map((row) => {
      const obj: Record<string, unknown> = {}
      queryResult.columns.forEach((col, idx) => {
        obj[col] = row[idx]
      })
      return obj
    })
  }

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-[400px] w-full" />
      </div>
    )
  }

  if (error || !dashboard) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Card className="border-destructive">
          <CardContent className="py-12">
            <div className="text-center space-y-3">
              <p className="text-destructive">{error || "Dashboard not found"}</p>
              <Button onClick={() => router.push("/query?tab=dashboards")} variant="outline">
                Back to Dashboards
              </Button>
            </div>
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
            <BreadcrumbLink href="/">Home</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink href="/query?tab=dashboards">Dashboards</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{dashboard.name}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 space-y-2">
          {isEditing ? (
            <div className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="edit-name">Dashboard Name</Label>
                <Input
                  id="edit-name"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  disabled={saving}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-description">Description</Label>
                <Textarea
                  id="edit-description"
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  disabled={saving}
                  rows={2}
                />
              </div>
              <div className="flex items-center justify-between rounded-lg border p-3">
                <div className="space-y-0.5">
                  <Label htmlFor="edit-public" className="cursor-pointer">
                    Make Public
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    Allow other users to view this dashboard
                  </p>
                </div>
                <Switch
                  id="edit-public"
                  checked={editIsPublic}
                  onCheckedChange={setEditIsPublic}
                  disabled={saving}
                />
              </div>
              <div className="flex gap-2">
                <Button onClick={handleSave} disabled={saving || !editName.trim()}>
                  {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  <Check className="mr-2 h-4 w-4" />
                  Save Changes
                </Button>
                <Button
                  variant="outline"
                  onClick={handleCancelEdit}
                  disabled={saving}
                >
                  <X className="mr-2 h-4 w-4" />
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <h2 className="text-3xl font-bold tracking-tight">{dashboard.name}</h2>
                {dashboard.is_public ? (
                  <Badge variant="secondary" className="gap-1">
                    <Globe className="h-3 w-3" />
                    Public
                  </Badge>
                ) : (
                  <Badge variant="outline" className="gap-1">
                    <Lock className="h-3 w-3" />
                    Private
                  </Badge>
                )}
              </div>
              {dashboard.description && (
                <p className="text-muted-foreground">{dashboard.description}</p>
              )}
              <p className="text-sm text-muted-foreground">
                Last updated {formatDistanceToNow(new Date(dashboard.updated_at), { addSuffix: true })}
              </p>
            </>
          )}
        </div>

        {!isEditing && (
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => router.push("/query?tab=dashboards")}
            >
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => executeQuery(dashboard.query_text)}
              disabled={executing}
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${executing ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button variant="outline" size="sm" onClick={handleShare}>
              <Share2 className="mr-2 h-4 w-4" />
              Share
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsEditing(true)}
            >
              <Edit2 className="mr-2 h-4 w-4" />
              Edit
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="mr-2 h-4 w-4" />
              )}
              Delete
            </Button>
          </div>
        )}
      </div>

      {/* Chart / Results */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {dashboard.chart_config.chartType === "table"
              ? "Data Table"
              : `${dashboard.chart_config.chartType.charAt(0).toUpperCase() + dashboard.chart_config.chartType.slice(1)} Chart`}
          </CardTitle>
          {/* Chart care: name the axis mapping and row count so the render is legible at a glance. */}
          {!execError && queryResult && (
            <p className="text-xs text-muted-foreground">
              {dashboard.chart_config.chartType !== "table" && dashboard.chart_config.xAxis && dashboard.chart_config.yAxis && (
                <>
                  <span className="text-foreground/70">X</span> {dashboard.chart_config.xAxis}
                  {"  ·  "}
                  <span className="text-foreground/70">Y</span> {dashboard.chart_config.yAxis}
                  {"  ·  "}
                </>
              )}
              <span className="tabular-nums">{(queryResult.rows?.length ?? 0).toLocaleString()}</span>{" "}
              {(queryResult.rows?.length ?? 0) === 1 ? "row" : "rows"}
            </p>
          )}
        </CardHeader>
        <CardContent>
          {executing && (
            <div className="flex items-center justify-center h-[400px]">
              <div className="text-center space-y-2">
                <Loader2 className="h-8 w-8 animate-spin mx-auto text-primary" />
                <p className="text-sm text-muted-foreground">Executing query...</p>
              </div>
            </div>
          )}

          {!executing && execError && (
            <div className="flex items-center justify-center h-[400px]">
              <div className="text-center space-y-3 max-w-md px-4">
                <AlertTriangle className="h-8 w-8 mx-auto text-[var(--dp-warn)]" />
                <div>
                  <p className="text-sm font-medium">Query failed</p>
                  <p className="text-xs text-muted-foreground mt-1 break-words">{execError}</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => executeQuery(dashboard.query_text)}
                  disabled={executing}
                >
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Retry
                </Button>
              </div>
            </div>
          )}

          {!executing && !execError && queryResult && (
            <>
              {dashboard.chart_config.chartType === "table" ? (
                <QueryResults
                  columns={queryResult.columns}
                  rows={queryResult.rows}
                  executionTime={queryResult.execution_time_ms}
                  loading={false}
                />
              ) : (
                <ChartRenderer
                  data={getChartData()}
                  chartType={dashboard.chart_config.chartType}
                  xAxis={dashboard.chart_config.xAxis || ""}
                  yAxis={dashboard.chart_config.yAxis || ""}
                  chartConfig={{
                    colors: dashboard.chart_config.colors,
                    showGrid: dashboard.chart_config.showGrid,
                    showLegend: dashboard.chart_config.showLegend,
                  }}
                />
              )}
            </>
          )}

          {!executing && !execError && !queryResult && (
            <div className="flex items-center justify-center h-[400px]">
              <p className="text-sm text-muted-foreground">No data available</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Query Info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">SQL Query</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="text-sm bg-muted p-4 rounded-lg overflow-x-auto">
            <code>{dashboard.query_text}</code>
          </pre>
        </CardContent>
      </Card>
    </div>
  )
}
