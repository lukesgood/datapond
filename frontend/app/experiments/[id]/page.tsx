"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  FlaskConical,
  ArrowLeft,
  PlayCircle,
  CheckCircle,
  XCircle,
  Clock,
  ExternalLink,
  TrendingUp,
  BarChart3,
} from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { serviceUrls } from "@/lib/urls"
import { cn } from "@/lib/utils"
import { bestMetricValue, metricLowerIsBetter } from "@/components/experiments/compare-runs"

interface Experiment {
  experiment_id: string
  name: string
}

interface Run {
  info: {
    run_id: string
    run_name?: string
    experiment_id: string
    status: string
    start_time: number
    end_time?: number
    user_id?: string
  }
  data: {
    metrics?: Array<{ key: string; value: number; timestamp: number; step: number }>
    params?: Array<{ key: string; value: string }>
    tags?: Array<{ key: string; value: string }>
  }
}

interface CompareData {
  runs: Run[]
  common_metrics?: string[]
  common_params?: string[]
  diff_params?: string[]
}

export default function ExperimentDetailPage({ params }: { params: { id: string } }) {
  const router = useRouter()
  const [experiment, setExperiment] = useState<Experiment | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedRuns, setSelectedRuns] = useState<string[]>([])
  const [sortBy, setSortBy] = useState<string>("start_time")
  const [compareData, setCompareData] = useState<CompareData | null>(null)
  const [comparing, setComparing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchExperimentDetails = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const expRes = await fetch(`/api/mlflow/experiments/${params.id}`)
      if (!expRes.ok) throw new Error(await expRes.text() || `HTTP ${expRes.status}`)
      setExperiment(await expRes.json() as Experiment)

      const runsRes = await fetch(`/api/mlflow/experiments/${params.id}/runs`)
      if (!runsRes.ok) throw new Error(await runsRes.text() || `HTTP ${runsRes.status}`)
      const runData = await runsRes.json() as Run[]
      if (!Array.isArray(runData)) throw new Error("Invalid runs response")
      setRuns(runData)
    } catch (caught) {
      setExperiment(null)
      setRuns([])
      setError(caught instanceof Error ? caught.message : "Failed to load experiment")
    } finally {
      setLoading(false)
    }
  }, [params.id])

  useEffect(() => {
    const timer = window.setTimeout(() => { void fetchExperimentDetails() }, 0)
    return () => window.clearTimeout(timer)
  }, [fetchExperimentDetails])

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "RUNNING":
        return <PlayCircle className="h-4 w-4 text-blue-500" />
      case "FINISHED":
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case "FAILED":
        return <XCircle className="h-4 w-4 text-red-500" />
      default:
        return <Clock className="h-4 w-4 text-gray-500" />
    }
  }

  const getStatusBadge = (status: string) => {
    // Theme-aware chips consistent with the Experiments overview StatusBadge
    // (subtle bg + border, readable in both light and dark).
    switch (status) {
      case "RUNNING":
        return (
          <Badge variant="outline" className="border-blue-200 dark:border-blue-800 bg-blue-50 text-blue-600 dark:bg-blue-950/40 dark:text-blue-400">
            Running
          </Badge>
        )
      case "FINISHED":
        return (
          <Badge variant="outline" className="border-emerald-200 dark:border-emerald-800 bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400">
            Finished
          </Badge>
        )
      case "FAILED":
        return <Badge variant="destructive">Failed</Badge>
      default:
        return <Badge variant="outline">{status}</Badge>
    }
  }

  const formatDuration = (startTime: number, endTime?: number) => {
    if (!endTime) return "Running..."
    const duration = endTime - startTime
    const seconds = Math.floor(duration / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)

    if (hours > 0) return `${hours}h ${minutes % 60}m`
    if (minutes > 0) return `${minutes}m ${seconds % 60}s`
    return `${seconds}s`
  }

  const formatTimestamp = (timestamp: number) => {
    const date = new Date(timestamp)
    return date.toLocaleString()
  }

  const toggleRunSelection = (runId: string) => {
    setSelectedRuns((prev) =>
      prev.includes(runId) ? prev.filter((id) => id !== runId) : [...prev, runId]
    )
  }

  // Get all unique metric keys
  const allMetrics = useMemo(
    () => Array.from(new Set(runs.flatMap((run) => run.data.metrics?.map((m) => m.key) || []))),
    [runs]
  )

  // Apply the sort control (previously inert — the Select changed state but the
  // table always rendered in fetch order). Rank statuses so active work floats up.
  const sortedRuns = useMemo(() => {
    const statusRank: Record<string, number> = { RUNNING: 0, FAILED: 1, FINISHED: 2 }
    // Running runs (no end_time) are still ongoing → treat as longest, float to top.
    const dur = (r: Run) => (r.info.end_time != null ? r.info.end_time - r.info.start_time : Number.POSITIVE_INFINITY)
    return [...runs].sort((a, b) => {
      switch (sortBy) {
        case "duration": return dur(b) - dur(a)
        case "status": return (statusRank[a.info.status] ?? 3) - (statusRank[b.info.status] ?? 3)
        default: return b.info.start_time - a.info.start_time
      }
    })
  }, [runs, sortBy])

  // Per-metric best value + range, so each metric column can flag the winning run
  // and draw a small direction-aware bar (lower-is-better for loss/error metrics).
  const metricStats = useMemo(() => {
    const stats: Record<string, { min: number; max: number; best: number | null; count: number; lowerBetter: boolean }> = {}
    for (const key of allMetrics) {
      const vals = runs
        .map((r) => r.data.metrics?.find((m) => m.key === key)?.value)
        .filter((v): v is number => typeof v === "number" && Number.isFinite(v))
      stats[key] = {
        min: vals.length ? Math.min(...vals) : 0,
        max: vals.length ? Math.max(...vals) : 0,
        best: bestMetricValue(vals, key),
        count: vals.length,
        lowerBetter: metricLowerIsBetter(key),
      }
    }
    return stats
  }, [runs, allMetrics])

  const handleCompare = async () => {
    if (selectedRuns.length < 2) return
    setComparing(true)
    try {
      const res = await fetch("/api/mlflow/runs/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_ids: selectedRuns }),
      })
      if (res.ok) setCompareData(await res.json())
    } catch { /* non-critical */ }
    finally { setComparing(false) }
  }

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full rounded-lg" />
          ))}
        </div>
        <Card>
          <CardContent className="space-y-2 py-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </CardContent>
        </Card>
      </div>
    )
  }

  if (!experiment) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Card>
          <CardContent className="py-8 text-center">
            <p className="text-muted-foreground">{error || "Experiment not found"}</p>
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
            <BreadcrumbLink href="/experiments">ML Experiments</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{experiment.name}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => router.back()}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <FlaskConical className="h-6 w-6 text-purple-500" />
            <h2 className="text-3xl font-bold tracking-tight">{experiment.name}</h2>
          </div>
          <p className="text-sm text-muted-foreground font-mono pl-11">
            ID: {experiment.experiment_id}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {selectedRuns.length > 0 && (
            <Button variant="default" size="sm" onClick={handleCompare} disabled={comparing}>
              <BarChart3 className="mr-2 h-4 w-4" />
              {comparing ? "Comparing…" : `Compare ${selectedRuns.length} Runs`}
            </Button>
          )}
          <Button
            variant="default"
            size="sm"
            onClick={() =>
              window.open(
                `${serviceUrls.mlflow()}/#/experiments/${params.id}`,
                "_blank"
              )
            }
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            Open in MLflow
          </Button>
        </div>
      </div>

      {/* Statistics */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Total Runs</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{runs.length}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Running</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {runs.filter((r) => r.info.status === "RUNNING").length}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Finished</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {runs.filter((r) => r.info.status === "FINISHED").length}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Failed</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {runs.filter((r) => r.info.status === "FAILED").length}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Runs Table */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Runs</CardTitle>
            <Select value={sortBy} onValueChange={(value) => setSortBy(value || "start_time")}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Sort by" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="start_time">Start Time</SelectItem>
                <SelectItem value="duration">Duration</SelectItem>
                <SelectItem value="status">Status</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {runs.length === 0 ? (
            <p className="text-center text-muted-foreground py-8">No runs yet</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">
                    <Checkbox
                      aria-label="Select all runs"
                      checked={runs.length > 0 && selectedRuns.length === runs.length}
                      onCheckedChange={(c) =>
                        setSelectedRuns(c ? runs.map((r) => r.info.run_id) : [])
                      }
                    />
                  </TableHead>
                  <TableHead>Run</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                  {allMetrics.slice(0, 3).map((metric) => (
                    <TableHead key={metric}>{metric}</TableHead>
                  ))}
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedRuns.map((run) => (
                  <TableRow
                    key={run.info.run_id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => router.push(`/experiments/${params.id}/runs/${run.info.run_id}`)}
                  >
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <Checkbox
                        checked={selectedRuns.includes(run.info.run_id)}
                        onCheckedChange={() => toggleRunSelection(run.info.run_id)}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1">
                        <p className="font-medium">
                          {run.info.run_name || run.info.run_id.substring(0, 8)}
                        </p>
                        <p className="text-xs text-muted-foreground font-mono">
                          {run.info.run_id.substring(0, 12)}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {getStatusIcon(run.info.status)}
                        {getStatusBadge(run.info.status)}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">
                      {formatTimestamp(run.info.start_time)}
                    </TableCell>
                    <TableCell className="text-sm">
                      {formatDuration(run.info.start_time, run.info.end_time)}
                    </TableCell>
                    {allMetrics.slice(0, 3).map((metric) => {
                      const stat = metricStats[metric]
                      const v = run.data.metrics?.find((m) => m.key === metric)?.value
                      const isBest = stat.best != null && v === stat.best && stat.count > 1
                      // Direction-aware fill: the "better" end of the range reads fuller.
                      const span = stat.max - stat.min
                      const goodness = v == null
                        ? 0
                        : span === 0
                          ? 1
                          : stat.lowerBetter
                            ? (stat.max - v) / span
                            : (v - stat.min) / span
                      return (
                        <TableCell key={metric} className="font-mono text-sm">
                          {v == null ? (
                            <span className="text-muted-foreground/40">—</span>
                          ) : (
                            <div className="space-y-1">
                              <span
                                className={cn(
                                  "tabular-nums inline-flex items-center gap-1",
                                  isBest && "font-semibold text-emerald-600 dark:text-emerald-400"
                                )}
                              >
                                {v.toFixed(4)}
                                {isBest && <span className="text-[10px]">★</span>}
                              </span>
                              {stat.count > 1 && (
                                <div className="h-1.5 w-14 rounded-full bg-muted overflow-hidden">
                                  <div
                                    className={cn("h-full rounded-full", isBest ? "bg-emerald-500" : "bg-blue-500/50")}
                                    style={{ width: `${Math.round(goodness * 100)}%` }}
                                  />
                                </div>
                              )}
                            </div>
                          )}
                        </TableCell>
                      )
                    })}
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation()
                          router.push(`/experiments/${params.id}/runs/${run.info.run_id}`)
                        }}
                      >
                        <TrendingUp className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Metrics Comparison */}
      {compareData && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Run Comparison</CardTitle>
              <Button variant="ghost" size="sm" className="h-7 text-xs"
                onClick={() => { setCompareData(null); setSelectedRuns([]) }}>
                Clear
              </Button>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/40">
                    <th className="text-left px-4 py-2 font-medium text-xs w-40">Field</th>
                    {compareData.runs.map((run) => (
                      <th key={run.info.run_id} className="text-left px-4 py-2 font-medium text-xs">
                        <div className="font-mono truncate max-w-[160px]">
                          {run.info.run_name || run.info.run_id.slice(0, 8)}
                        </div>
                        <div className="text-[10px] font-normal text-muted-foreground">
                          {run.info.run_id.slice(0, 8)}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {/* Metrics section */}
                  {(compareData.common_metrics?.length ?? 0) > 0 && (
                    <>
                      <tr className="bg-muted/20">
                        <td colSpan={compareData.runs.length + 1} className="px-4 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                          Metrics
                        </td>
                      </tr>
                      {(compareData.common_metrics ?? []).map((metric: string) => {
                        const vals = compareData.runs.map((r) =>
                          r.data.metrics?.find((m) => m.key === metric)?.value
                        )
                        const numVals = vals.filter((v): v is number => v != null)
                        const best = bestMetricValue(vals, metric)
                        return (
                          <tr key={metric} className="border-b hover:bg-muted/20">
                            <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{metric}</td>
                            {vals.map((v, i) => (
                              <td key={i} className={`px-4 py-2 font-mono text-xs font-medium tabular-nums ${
                                v === best && numVals.length > 1 ? "text-emerald-600 dark:text-emerald-400" : ""
                              }`}>
                                {v != null ? Number(v).toFixed(4) : "—"}
                                {v === best && numVals.length > 1 && (
                                  <span className="ml-1 text-[10px]">★</span>
                                )}
                              </td>
                            ))}
                          </tr>
                        )
                      })}
                    </>
                  )}
                  {/* Params section */}
                  {(compareData.common_params?.length ?? 0) > 0 && (
                    <>
                      <tr className="bg-muted/20">
                        <td colSpan={compareData.runs.length + 1} className="px-4 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                          Parameters
                        </td>
                      </tr>
                      {(compareData.common_params ?? []).map((param: string) => {
                        const vals = compareData.runs.map((r) =>
                          r.data.params?.find((p) => p.key === param)?.value
                        )
                        const allSame = new Set(vals).size === 1
                        return (
                          <tr key={param} className="border-b hover:bg-muted/20">
                            <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{param}</td>
                            {vals.map((v, i) => (
                              <td key={i} className={`px-4 py-2 font-mono text-xs ${
                                !allSame ? "font-medium" : "text-muted-foreground"
                              }`}>
                                {v ?? "—"}
                              </td>
                            ))}
                          </tr>
                        )
                      })}
                    </>
                  )}
                  {/* Diff params */}
                  {(compareData.diff_params?.length ?? 0) > 0 && (
                    <>
                      <tr className="bg-amber-50/50 dark:bg-amber-900/10">
                        <td colSpan={compareData.runs.length + 1} className="px-4 py-1 text-[10px] font-semibold text-amber-600 uppercase tracking-wide">
                          Differing Parameters
                        </td>
                      </tr>
                      {(compareData.diff_params ?? []).map((param: string) => {
                        const vals = compareData.runs.map((r) =>
                          r.data.params?.find((p) => p.key === param)?.value
                        )
                        return (
                          <tr key={param} className="border-b hover:bg-muted/20">
                            <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{param}</td>
                            {vals.map((v, i) => (
                              <td key={i} className="px-4 py-2 font-mono text-xs font-medium text-amber-600">
                                {v ?? <span className="text-muted-foreground/40">—</span>}
                              </td>
                            ))}
                          </tr>
                        )
                      })}
                    </>
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
