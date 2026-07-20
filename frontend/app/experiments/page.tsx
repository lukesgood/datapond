"use client"
import { CapabilityGate } from "@/lib/capabilities"

import { useState, useEffect, useCallback } from "react"
import { useToast } from "@/lib/toast"
import { ErrorBox } from "@/components/ui/error-box"
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import {
  Table, TableHeader, TableBody, TableHead, TableRow, TableCell,
} from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"
import {
  FlaskConical, Plus, RefreshCw, GitBranch, ChevronRight, X,
  BarChart3, Clock, CheckCircle2, XCircle, AlertCircle, Loader2,
  GitCompare, Trash2,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { getUser } from "@/lib/auth"
import { useConfirm } from "@/lib/confirm"
import { bestMetricValue } from "@/components/experiments/compare-runs"

// ── Types ──────────────────────────────────────────────────────────────────────

interface Experiment {
  experiment_id: string
  name: string
  lifecycle_stage: string
  creation_time?: number
  last_update_time?: number
}

interface Metric {
  key: string
  value: number
  step: number
  timestamp?: number
}

interface Param {
  key: string
  value: string
}

interface Tag {
  key: string
  value: string
}

interface RunInfo {
  run_id: string
  run_name?: string
  status: "RUNNING" | "FINISHED" | "FAILED" | "KILLED" | string
  start_time: number
  end_time?: number
  experiment_id?: string
}

interface Run {
  info: RunInfo
  data: {
    metrics: Metric[]
    params: Param[]
    tags: Tag[]
  }
}

interface CompareResult {
  runs: Run[]
  common_metrics: string[]
  common_params: string[]
  diff_metrics: string[]
  diff_params: string[]
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatDuration(startMs: number, endMs?: number): string {
  const ms = (endMs ?? Date.now()) - startMs
  if (ms < 0) return "—"
  const totalSecs = Math.floor(ms / 1000)
  const mins = Math.floor(totalSecs / 60)
  const secs = totalSecs % 60
  if (mins === 0) return `${secs}s`
  return `${mins}m ${secs}s`
}

function formatTs(ms: number): string {
  if (!ms) return "—"
  return new Date(ms).toLocaleString()
}

function runDisplayName(run: Run): string {
  return run.info.run_name || run.info.run_id.slice(0, 8)
}

type RunStatus = Run["info"]["status"]

function StatusBadge({ status }: { status: RunStatus }) {
  if (status === "FINISHED") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 bg-emerald-50 dark:bg-emerald-950/40 dark:text-emerald-400 px-1.5 py-0.5 rounded-md border border-emerald-200 dark:border-emerald-800">
        <CheckCircle2 className="h-3 w-3" />
        Finished
      </span>
    )
  }
  if (status === "RUNNING") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 bg-blue-50 dark:bg-blue-950/40 dark:text-blue-400 px-1.5 py-0.5 rounded-md border border-blue-200 dark:border-blue-800">
        <Loader2 className="h-3 w-3 animate-spin" />
        Running
      </span>
    )
  }
  if (status === "FAILED" || status === "KILLED") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-red-600 bg-red-50 dark:bg-red-950/40 dark:text-red-400 px-1.5 py-0.5 rounded-md border border-red-200 dark:border-red-800">
        <XCircle className="h-3 w-3" />
        {status === "KILLED" ? "Killed" : "Failed"}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded-md border border-border">
      <AlertCircle className="h-3 w-3" />
      {status}
    </span>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function KVTable({ rows }: { rows: Array<{ key: string; value: string | number }> }) {
  if (rows.length === 0) {
    return <p className="text-xs text-muted-foreground px-1 py-4 text-center">No data</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="text-xs w-1/2">Key</TableHead>
          <TableHead className="text-xs">Value</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.key}>
            <TableCell className="text-xs font-mono text-muted-foreground">{r.key}</TableCell>
            <TableCell className="text-xs font-mono">
              {typeof r.value === "number" ? r.value.toPrecision(6) : String(r.value)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function MetricsChartOrTable({ metrics }: { metrics: Metric[] }) {
  const hasSteps = metrics.some((m) => m.step > 0)

  if (hasSteps) {
    // Group by key → build step-based series
    const keys = Array.from(new Set(metrics.map((m) => m.key)))
    const byStep: Record<number, Record<string, number>> = {}
    metrics.forEach((m) => {
      if (!byStep[m.step]) byStep[m.step] = {}
      byStep[m.step][m.key] = m.value
    })
    const chartData = Object.entries(byStep)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([step, vals]) => ({ step: Number(step), ...vals }))

    const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"]

    return (
      <div className="space-y-3">
        <div className="h-36 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
              <XAxis dataKey="step" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} width={36} />
              <Tooltip
                contentStyle={{ fontSize: 11 }}
                formatter={(v) => typeof v === "number" ? v.toPrecision(5) : v}
              />
              {keys.map((k, i) => (
                <Line
                  key={k}
                  type="monotone"
                  dataKey={k}
                  stroke={COLORS[i % COLORS.length]}
                  dot={false}
                  strokeWidth={1.5}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <KVTable rows={metrics.map((m) => ({ key: `${m.key} (step ${m.step})`, value: m.value }))} />
      </div>
    )
  }

  return <KVTable rows={metrics.map((m) => ({ key: m.key, value: m.value }))} />
}

function RunDetailPanel({
  run,
  onClose,
}: {
  run: Run
  onClose: () => void
}) {
  const duration = formatDuration(run.info.start_time, run.info.end_time)

  return (
    <div className="flex flex-col h-full overflow-hidden border-l bg-background">
      {/* Panel header */}
      <div className="flex items-center justify-between px-3 py-2 border-b shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <GitBranch className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs font-medium truncate">{runDisplayName(run)}</span>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} className="h-6 w-6 shrink-0">
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview" className="flex flex-col flex-1 overflow-hidden">
        <div className="px-2 pt-1.5 shrink-0 border-b">
          <TabsList variant="line" className="h-7">
            <TabsTrigger value="overview" className="text-xs px-2 h-7">Overview</TabsTrigger>
            <TabsTrigger value="metrics" className="text-xs px-2 h-7">
              Metrics
              {run.data.metrics.length > 0 && (
                <span className="ml-1 text-[10px] bg-muted text-muted-foreground rounded px-1">
                  {run.data.metrics.length}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value="params" className="text-xs px-2 h-7">
              Params
              {run.data.params.length > 0 && (
                <span className="ml-1 text-[10px] bg-muted text-muted-foreground rounded px-1">
                  {run.data.params.length}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value="tags" className="text-xs px-2 h-7">Tags</TabsTrigger>
          </TabsList>
        </div>

        <div className="flex-1 overflow-y-auto">
          <TabsContent value="overview" className="p-3 space-y-2.5 mt-0">
            <div className="space-y-1.5">
              <div className="flex justify-between items-center">
                <span className="text-xs text-muted-foreground">Status</span>
                <StatusBadge status={run.info.status} />
              </div>
              <Separator />
              <div className="flex justify-between items-center">
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3 w-3" />Duration
                </span>
                <span className="text-xs font-mono">{duration}</span>
              </div>
              <Separator />
              <div className="flex justify-between items-start">
                <span className="text-xs text-muted-foreground">Started</span>
                <span className="text-xs text-right">{formatTs(run.info.start_time)}</span>
              </div>
              {run.info.end_time && (
                <>
                  <Separator />
                  <div className="flex justify-between items-start">
                    <span className="text-xs text-muted-foreground">Ended</span>
                    <span className="text-xs text-right">{formatTs(run.info.end_time)}</span>
                  </div>
                </>
              )}
              <Separator />
              <div className="flex justify-between items-center">
                <span className="text-xs text-muted-foreground">Run ID</span>
                <span className="text-[10px] font-mono text-muted-foreground">{run.info.run_id.slice(0, 12)}…</span>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="metrics" className="p-2 mt-0">
            <MetricsChartOrTable metrics={run.data.metrics} />
          </TabsContent>

          <TabsContent value="params" className="p-2 mt-0">
            <KVTable rows={run.data.params} />
          </TabsContent>

          <TabsContent value="tags" className="p-2 mt-0">
            <KVTable
              rows={run.data.tags.filter(
                (t) => !t.key.startsWith("mlflow.") // hide internal tags by default
              )}
            />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  )
}

function CompareView({
  result,
  onClose,
}: {
  result: CompareResult
  onClose: () => void
}) {
  const metricNames = Array.from(new Set([...result.common_metrics, ...result.diff_metrics]))
  const paramNames = Array.from(new Set([...result.common_params, ...result.diff_params]))
  // Highlight the best run per metric using the shared best-value rule
  // (lower is better for loss/error-like metrics, otherwise higher is better).
  const getBest = (metric: string): string | null => {
    const vals = result.runs.map((r) => ({
      id: r.info.run_id,
      v: r.data.metrics.find((value) => value.key === metric)?.value ?? null,
    })).filter((x) => x.v !== null) as Array<{ id: string; v: number }>
    if (vals.length === 0) return null
    const best = bestMetricValue(vals.map((x) => x.v), metric)
    if (best === null) return null
    return vals.find((x) => x.v === best)?.id ?? null
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b shrink-0">
        <div className="flex items-center gap-2">
          <GitCompare className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Run Comparison</span>
          <Badge variant="secondary" className="text-[10px]">{result.runs.length} runs</Badge>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} className="h-7 w-7">
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-4">
        {/* Metrics comparison */}
        {metricNames.length > 0 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
              Metrics
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="border-b">
                    <th className="text-left p-1.5 font-medium text-muted-foreground w-32">Metric</th>
                    {result.runs.map((r) => (
                      <th key={r.info.run_id} className="text-left p-1.5 font-medium min-w-[100px]">
                        {r.info.run_name || r.info.run_id.slice(0, 8)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {metricNames.map((metric) => {
                    const bestId = getBest(metric)
                    return (
                      <tr key={metric} className="border-b last:border-0 hover:bg-muted/30">
                        <td className="p-1.5 font-mono text-muted-foreground">{metric}</td>
                        {result.runs.map((r) => {
                          const v = r.data.metrics.find((value) => value.key === metric)?.value
                          const isBest = bestId === r.info.run_id && v !== undefined
                          return (
                            <td
                              key={r.info.run_id}
                              className={cn(
                                "p-1.5 font-mono",
                                isBest && "text-emerald-600 dark:text-emerald-400 font-semibold"
                              )}
                            >
                              {v !== undefined ? v.toPrecision(5) : <span className="text-muted-foreground/40">—</span>}
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Params comparison */}
        {paramNames.length > 0 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
              Parameters
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="border-b">
                    <th className="text-left p-1.5 font-medium text-muted-foreground w-32">Param</th>
                    {result.runs.map((r) => (
                      <th key={r.info.run_id} className="text-left p-1.5 font-medium min-w-[100px]">
                        {r.info.run_name || r.info.run_id.slice(0, 8)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paramNames.map((param) => (
                    <tr key={param} className="border-b last:border-0 hover:bg-muted/30">
                      <td className="p-1.5 font-mono text-muted-foreground">{param}</td>
                      {result.runs.map((r) => (
                        <td key={r.info.run_id} className="p-1.5 font-mono">
                          {r.data.params.find((value) => value.key === param)?.value ?? <span className="text-muted-foreground/40">—</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── New Experiment Dialog ──────────────────────────────────────────────────────

function NewExperimentDialog({
  open,
  onOpenChange,
  onCreate,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onCreate: (exp: Experiment) => void
}) {
  const [name, setName] = useState("")
  const [artifactLocation, setArtifactLocation] = useState("")
  const { toast } = useToast()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch("/api/mlflow/experiments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          ...(artifactLocation.trim() ? { artifact_location: artifactLocation.trim() } : {}),
        }),
      })
      if (!res.ok) {
        const msg = await res.text()
        throw new Error(msg || String(res.status))
      }
      const created = await res.json()
      toast(`Experiment "${name.trim()}" created`, "success")
      onCreate(created)
      setName("")
      setArtifactLocation("")
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create experiment")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4" />
            New Experiment
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="exp-name" className="text-xs">Name *</Label>
            <Input
              id="exp-name"
              placeholder="my-experiment"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={submitting}
              autoFocus
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="artifact-loc" className="text-xs">
              Artifact Location{" "}
              <span className="text-muted-foreground">(optional)</span>
            </Label>
            <Input
              id="artifact-loc"
              placeholder="s3://my-bucket/artifacts"
              value={artifactLocation}
              onChange={(e) => setArtifactLocation(e.target.value)}
              disabled={submitting}
            />
          </div>
          {error && <ErrorBox msg={error} />}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={submitting || !name.trim()}>
              {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────

function ExperimentsPageInner() {
  const [experiments, setExperiments] = useState<Experiment[]>([])
  const [runCounts, setRunCounts] = useState<Record<string, number>>({})
  const [selectedExp, setSelectedExp] = useState<Experiment | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [selectedRun, setSelectedRun] = useState<Run | null>(null)

  // Compare mode
  const [compareIds, setCompareIds] = useState<Set<string>>(new Set())
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null)
  const [comparePending, setComparePending] = useState(false)
  const [compareError, setCompareError] = useState<string | null>(null)

  // Loading / error state
  const [loadingExps, setLoadingExps] = useState(true)
  const [loadingRuns, setLoadingRuns] = useState(false)
  const [expError, setExpError] = useState<string | null>(null)
  const [runsError, setRunsError] = useState<string | null>(null)

  // Dialog
  const [createExpOpen, setCreateExpOpen] = useState(false)

  // Admin-gated actions
  const { toast } = useToast()
  const confirm = useConfirm()
  const isAdmin = getUser()?.role === "admin"

  // ── Loaders ────────────────────────────────────────────────────────────────

  const loadExperiments = useCallback(async () => {
    setLoadingExps(true)
    setExpError(null)
    try {
      const res = await fetch("/api/mlflow/experiments")
      if (!res.ok) throw new Error(String(res.status))
      const data = await res.json() as Experiment[]
      if (!Array.isArray(data)) throw new Error("Invalid experiment response")
      const active = data.filter((e) => e.lifecycle_stage !== "deleted")
      setExperiments(active)

      // Fetch run counts in parallel (best-effort)
      const counts: Record<string, number> = {}
      await Promise.allSettled(
        active.map(async (exp) => {
          try {
            const r = await fetch(`/api/mlflow/experiments/${exp.experiment_id}/runs`)
            if (!r.ok) throw new Error(String(r.status))
            const runs = await r.json() as Run[]
            if (!Array.isArray(runs)) throw new Error("Invalid runs response")
            counts[exp.experiment_id] = runs.length
          } catch {
            counts[exp.experiment_id] = 0
          }
        })
      )
      setRunCounts(counts)
    } catch (err) {
      setExpError(err instanceof Error ? err.message : "Failed to load experiments")
    } finally {
      setLoadingExps(false)
    }
  }, [])

  const loadRuns = useCallback(async (exp: Experiment) => {
    setLoadingRuns(true)
    setRunsError(null)
    setRuns([])
    setSelectedRun(null)
    setCompareIds(new Set())
    setCompareResult(null)
    try {
      const res = await fetch(`/api/mlflow/experiments/${exp.experiment_id}/runs`)
      if (!res.ok) throw new Error(String(res.status))
      const data = await res.json() as Run[]
      if (!Array.isArray(data)) throw new Error("Invalid runs response")
      setRuns(data)
      // Update run count for this experiment
      setRunCounts((prev) => ({ ...prev, [exp.experiment_id]: data.length }))
    } catch (err) {
      setRunsError(err instanceof Error ? err.message : "Failed to load runs")
    } finally {
      setLoadingRuns(false)
    }
  }, [])

  const handleSelectExp = useCallback(
    (exp: Experiment) => {
      setSelectedExp(exp)
      setSelectedRun(null)
      setCompareResult(null)
      setCompareIds(new Set())
      loadRuns(exp)
    },
    [loadRuns]
  )

  const handleCompare = useCallback(async () => {
    if (compareIds.size < 2) return
    setComparePending(true)
    setCompareError(null)
    setCompareResult(null)
    setSelectedRun(null)
    try {
      const res = await fetch("/api/mlflow/runs/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_ids: Array.from(compareIds) }),
      })
      if (!res.ok) throw new Error(String(res.status))
      const data = await res.json()
      setCompareResult(data)
    } catch (err) {
      setCompareError(err instanceof Error ? err.message : "Compare failed")
    } finally {
      setComparePending(false)
    }
  }, [compareIds])

  const toggleCompareId = useCallback((runId: string) => {
    setCompareIds((prev) => {
      const next = new Set(prev)
      if (next.has(runId)) next.delete(runId)
      else next.add(runId)
      return next
    })
    setCompareResult(null)
  }, [])

  const handleDeleteExp = useCallback(async (exp: Experiment) => {
    const ok = await confirm({
      title: "Delete experiment",
      message: `Delete experiment "${exp.name}"? This moves it to MLflow's deleted stage and removes it from this list.`,
      confirmText: "Delete",
      destructive: true,
    })
    if (!ok) return
    try {
      const res = await fetch(`/api/mlflow/experiments/${exp.experiment_id}`, { method: "DELETE" })
      if (!res.ok) throw new Error(String(res.status))
      toast(`Experiment "${exp.name}" deleted`, "success")
      if (selectedExp?.experiment_id === exp.experiment_id) {
        setSelectedExp(null)
        setRuns([])
        setSelectedRun(null)
        setCompareResult(null)
        setCompareIds(new Set())
      }
      void loadExperiments()
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to delete experiment", "error")
    }
  }, [confirm, toast, selectedExp, loadExperiments])

  // Initial load
  useEffect(() => {
    const timer = window.setTimeout(() => { void loadExperiments() }, 0)
    return () => window.clearTimeout(timer)
  }, [loadExperiments])

  // ── Derived ────────────────────────────────────────────────────────────────

  const totalRuns = Object.values(runCounts).reduce((a, b) => a + b, 0)
  const rightPanelOpen = compareResult !== null || selectedRun !== null

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col" style={{ height: "calc(100vh - 56px)" }}>
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">ML Experiments</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Experiment tracking, metrics, and model runs
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs gap-1.5"
            onClick={loadExperiments}
            disabled={loadingExps}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loadingExps && "animate-spin")} />
            Refresh
          </Button>
          <Button
            size="sm"
            className="h-8 text-xs gap-1.5"
            onClick={() => setCreateExpOpen(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            New Experiment
          </Button>
        </div>
      </div>

      {/* ── Stats strip ────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-3 border-b shrink-0">
        {[
          {
            label: "Experiments",
            icon: FlaskConical,
            value: loadingExps ? null : experiments.length,
          },
          {
            label: "Total Runs",
            icon: GitBranch,
            value: loadingExps ? null : totalRuns,
          },
          {
            label: "Selected Runs",
            icon: BarChart3,
            value: selectedExp ? (loadingRuns ? null : runs.length) : "—",
          },
        ].map(({ label, icon: Icon, value }) => (
          <div key={label} className="flex items-center gap-3 px-5 py-2.5 border-r last:border-r-0">
            <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
            <div>
              <div className="text-xs text-muted-foreground">{label}</div>
              {value === null ? (
                <Skeleton className="h-5 w-8 mt-0.5" />
              ) : (
                <div className="text-lg font-semibold leading-tight">{value}</div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* ── Error banner ───────────────────────────────────────────────────── */}
      {expError && (
        <div className="flex items-center gap-2 px-6 py-2 bg-destructive/5 border-b text-destructive text-xs shrink-0">
          <AlertCircle className="h-3.5 w-3.5" />
          {expError}
        </div>
      )}

      {/* ── Main 3-column body ─────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── LEFT: Experiment list (~240px) ─────────────────────────────── */}
        <div className="w-60 shrink-0 border-r flex flex-col overflow-hidden bg-muted/30">
          <div className="px-3 py-2 border-b flex items-center justify-between">
            <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
              Experiments
            </span>
            {loadingExps && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
          </div>

          <div className="flex-1 overflow-y-auto">
            {loadingExps ? (
              <div className="p-2 space-y-1.5">
                {Array(5).fill(0).map((_, i) => (
                  <Skeleton key={i} className="h-11 w-full rounded-md" />
                ))}
              </div>
            ) : experiments.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 text-center px-4">
                <FlaskConical className="h-8 w-8 text-muted-foreground/30 mb-2" />
                <p className="text-xs text-muted-foreground">No experiments yet.</p>
                <p className="text-[11px] text-muted-foreground/60 mt-1">
                  Create your first experiment to start tracking ML runs.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3 h-7 text-xs gap-1"
                  onClick={() => setCreateExpOpen(true)}
                >
                  <Plus className="h-3 w-3" />
                  Create
                </Button>
              </div>
            ) : (
              <div className="p-1.5 space-y-0.5">
                {experiments.map((exp) => {
                  const count = runCounts[exp.experiment_id] ?? 0
                  const isSelected = selectedExp?.experiment_id === exp.experiment_id
                  const isDefault = exp.experiment_id === "0"
                  return (
                    <div key={exp.experiment_id} className="relative group">
                      <button
                        onClick={() => handleSelectExp(exp)}
                        className={cn(
                          "w-full text-left px-2.5 py-2 rounded-md transition-colors",
                          "hover:bg-muted/60",
                          isSelected
                            ? "bg-background border-l-2 border-l-blue-500 pl-[calc(0.625rem-2px)] shadow-sm"
                            : "border-l-2 border-l-transparent"
                        )}
                      >
                        <div className="flex items-center justify-between gap-1.5">
                          <span
                            className={cn(
                              "text-xs font-medium truncate leading-tight",
                              isSelected ? "text-foreground" : "text-foreground/80"
                            )}
                          >
                            {exp.name}
                          </span>
                          <div className="flex items-center gap-1 shrink-0">
                            {isDefault && (
                              <Badge variant="secondary" className="text-[9px] h-3.5 px-1">
                                default
                              </Badge>
                            )}
                            <span
                              className={cn(
                                "text-[10px] font-medium px-1.5 py-0.5 rounded-full",
                                count > 0
                                  ? "bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-400"
                                  : "bg-muted text-muted-foreground"
                              )}
                            >
                              {count}
                            </span>
                          </div>
                        </div>
                      </button>
                      {isAdmin && !isDefault && (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); void handleDeleteExp(exp) }}
                          aria-label={`Delete experiment ${exp.name}`}
                          title="Delete experiment"
                          className="absolute right-1.5 top-1/2 -translate-y-1/2 h-6 w-6 flex items-center justify-center rounded-md border bg-background text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive hover:border-destructive/40 transition-opacity"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* ── CENTER: Runs table ─────────────────────────────────────────── */}
        <div className={cn("flex flex-col overflow-hidden", rightPanelOpen ? "flex-1" : "flex-1")}>
          {/* Center header */}
          <div className="flex items-center justify-between px-4 py-2 border-b shrink-0 bg-background">
            {selectedExp ? (
              <>
                <div className="flex items-center gap-2 min-w-0">
                  <FlaskConical className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <span className="text-sm font-medium truncate">{selectedExp.name}</span>
                  {loadingRuns && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {compareIds.size >= 2 && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs gap-1.5"
                      onClick={handleCompare}
                      disabled={comparePending}
                    >
                      {comparePending
                        ? <Loader2 className="h-3 w-3 animate-spin" />
                        : <GitCompare className="h-3 w-3" />
                      }
                      Compare {compareIds.size} runs
                    </Button>
                  )}
                  {compareIds.size > 0 && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 text-xs"
                      onClick={() => { setCompareIds(new Set()); setCompareResult(null) }}
                    >
                      Clear
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs gap-1"
                    onClick={() => selectedExp && loadRuns(selectedExp)}
                    disabled={loadingRuns}
                  >
                    <RefreshCw className={cn("h-3 w-3", loadingRuns && "animate-spin")} />
                  </Button>
                </div>
              </>
            ) : (
              <span className="text-xs text-muted-foreground">Select an experiment to view runs</span>
            )}
          </div>

          {/* Compare error */}
          {compareError && (
            <div className="flex items-center gap-2 px-4 py-1.5 bg-destructive/5 border-b text-destructive text-xs shrink-0">
              <AlertCircle className="h-3.5 w-3.5" />
              {compareError}
            </div>
          )}

          {/* Runs error */}
          {runsError && (
            <div className="flex items-center gap-2 px-4 py-1.5 bg-destructive/5 border-b text-destructive text-xs shrink-0">
              <AlertCircle className="h-3.5 w-3.5" />
              {runsError}
            </div>
          )}

          {/* Runs content */}
          <div className="flex-1 overflow-auto">
            {!selectedExp ? (
              <div className="flex flex-col items-center justify-center h-full text-center px-8">
                <FlaskConical className="h-10 w-10 text-muted-foreground/20 mb-3" />
                <p className="text-sm text-muted-foreground">No experiment selected</p>
                <p className="text-xs text-muted-foreground/60 mt-1">
                  Pick an experiment from the left panel to browse its runs.
                </p>
              </div>
            ) : loadingRuns ? (
              <div className="p-4 space-y-2">
                {Array(6).fill(0).map((_, i) => (
                  <Skeleton key={i} className="h-9 w-full" />
                ))}
              </div>
            ) : runs.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center px-8">
                <Clock className="h-10 w-10 text-muted-foreground/20 mb-3" />
                <p className="text-sm text-muted-foreground">No runs yet</p>
                <p className="text-xs text-muted-foreground/60 mt-1 max-w-xs">
                  No runs in this experiment yet. Use the MLflow SDK in a notebook or the Query Lab to log runs.
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-xs w-8 pl-3">
                      <span className="sr-only">Compare</span>
                    </TableHead>
                    <TableHead className="text-xs">Name</TableHead>
                    <TableHead className="text-xs">Status</TableHead>
                    <TableHead className="text-xs">Duration</TableHead>
                    <TableHead className="text-xs">Metrics</TableHead>
                    <TableHead className="text-xs">Started</TableHead>
                    <TableHead className="text-xs w-6"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.map((run) => {
                    const isSelected = selectedRun?.info.run_id === run.info.run_id
                    const isChecked = compareIds.has(run.info.run_id)
                    // Show first 2 metrics as preview
                    const previewMetrics = run.data.metrics.slice(0, 2)

                    return (
                      <TableRow
                        key={run.info.run_id}
                        className={cn(
                          "cursor-pointer",
                          isSelected && "bg-muted/60"
                        )}
                        onClick={() => {
                          setSelectedRun(isSelected ? null : run)
                          setCompareResult(null)
                        }}
                      >
                        {/* Compare checkbox */}
                        <TableCell
                          className="pl-3 pr-0"
                          onClick={(e) => {
                            e.stopPropagation()
                            toggleCompareId(run.info.run_id)
                          }}
                        >
                          <Checkbox
                            checked={isChecked}
                            onClick={(e) => e.stopPropagation()}
                            onCheckedChange={() => toggleCompareId(run.info.run_id)}
                          />
                        </TableCell>

                        {/* Run name */}
                        <TableCell className="text-xs font-medium max-w-[160px]">
                          <span className="truncate block">{runDisplayName(run)}</span>
                        </TableCell>

                        {/* Status */}
                        <TableCell>
                          <StatusBadge status={run.info.status} />
                        </TableCell>

                        {/* Duration */}
                        <TableCell className="text-xs text-muted-foreground font-mono">
                          {formatDuration(run.info.start_time, run.info.end_time)}
                        </TableCell>

                        {/* Metrics preview */}
                        <TableCell className="text-xs">
                          {previewMetrics.length > 0 ? (
                            <div className="flex flex-wrap gap-1.5">
                              {previewMetrics.map((m) => (
                                <span
                                  key={m.key}
                                  className="inline-flex items-baseline gap-0.5 text-[10px] font-mono"
                                >
                                  <span className="text-muted-foreground">{m.key}:</span>
                                  <span className="font-medium">{m.value.toPrecision(4)}</span>
                                </span>
                              ))}
                              {run.data.metrics.length > 2 && (
                                <span className="text-[10px] text-muted-foreground">
                                  +{run.data.metrics.length - 2}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-muted-foreground/40 text-[11px]">—</span>
                          )}
                        </TableCell>

                        {/* Start time */}
                        <TableCell className="text-[11px] text-muted-foreground">
                          {formatTs(run.info.start_time)}
                        </TableCell>

                        {/* Chevron */}
                        <TableCell className="pr-2">
                          <ChevronRight
                            className={cn(
                              "h-3.5 w-3.5 text-muted-foreground/40 transition-transform",
                              isSelected && "rotate-90 text-muted-foreground"
                            )}
                          />
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            )}
          </div>
        </div>

        {/* ── RIGHT: Run detail or Compare view (~320px) ─────────────────── */}
        {rightPanelOpen && (
          <div className="w-80 shrink-0 flex flex-col overflow-hidden border-l">
            {compareResult ? (
              <CompareView
                result={compareResult}
                onClose={() => { setCompareResult(null) }}
              />
            ) : selectedRun ? (
              <RunDetailPanel
                run={selectedRun}
                onClose={() => setSelectedRun(null)}
              />
            ) : null}
          </div>
        )}
      </div>

      {/* ── New Experiment Dialog ───────────────────────────────────────────── */}
      <NewExperimentDialog
        open={createExpOpen}
        onOpenChange={setCreateExpOpen}
        onCreate={(exp) => {
          setExperiments((prev) => [exp, ...prev])
          setRunCounts((prev) => ({ ...prev, [exp.experiment_id]: 0 }))
          handleSelectExp(exp)
        }}
      />
    </div>
  )
}

export default function ExperimentsPage() {
  return (
    <CapabilityGate capability="experiments">
      <ExperimentsPageInner />
    </CapabilityGate>
  )
}
