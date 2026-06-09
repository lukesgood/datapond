"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { useToast } from "@/lib/toast"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { AssetGraph } from "@/components/pipelines/asset-graph"
import { AssetContextPanel } from "@/components/pipelines/asset-context-panel"
import { AssetNodeData } from "@/components/pipelines/asset-node"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import {
  ArrowLeft, Play, Pause, RefreshCw, AlertCircle,
  Calendar, Clock, TrendingUp, CheckCircle2, XCircle,
  GitBranch, Tag, User, Timer, Activity, ExternalLink,
  Settings2, Zap, PanelRightClose,
} from "lucide-react"
import { formatDistanceToNow, format } from "date-fns"

// ── Types ──────────────────────────────────────────────────────────────────
interface DAG {
  dag_id: string; is_paused: boolean; is_active: boolean
  description?: string; schedule_interval?: string; tags: string[]
  owners?: string[]; catchup?: boolean
  max_active_runs?: number; max_active_tasks?: number
  fileloc?: string; timezone?: string
}
interface DagStats {
  total_runs: number; success_runs: number; failed_runs: number
  running_runs: number; queued_runs: number
  success_rate: number; avg_duration?: number
}
interface DagRun {
  dag_run_id: string; dag_id: string; execution_date: string
  start_date?: string; end_date?: string; state: string; run_type: string
  conf?: Record<string, unknown>
}

// ── Helpers ────────────────────────────────────────────────────────────────
function fmtDuration(sec?: number) {
  if (!sec) return "—"
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60)
  if (m === 0) return `${s}s`
  return m < 60 ? `${m}m ${s}s` : `${Math.floor(m/60)}h ${m%60}m`
}
function fmtDate(d?: string) {
  if (!d) return "—"
  try { return format(new Date(d), "MM/dd HH:mm:ss") } catch { return d }
}
function timeAgo(d?: string) {
  if (!d) return "—"
  try { return formatDistanceToNow(new Date(d), { addSuffix: true }) } catch { return d }
}
function runDuration(start?: string, end?: string) {
  if (!start) return "—"
  const ms = (end ? new Date(end) : new Date()).getTime() - new Date(start).getTime()
  return fmtDuration(ms / 1000)
}

function RunStateBadge({ state }: { state: string }) {
  const map: Record<string, string> = {
    success: "bg-emerald-500/15 text-emerald-700 border-emerald-200",
    failed:  "bg-red-500/15 text-red-700 border-red-200",
    running: "bg-blue-500/15 text-blue-700 border-blue-200",
    queued:  "bg-yellow-500/15 text-yellow-700 border-yellow-200",
  }
  const icons: Record<string, React.ReactNode> = {
    success: <CheckCircle2 className="h-3 w-3" />,
    failed:  <XCircle className="h-3 w-3" />,
    running: <RefreshCw className="h-3 w-3 animate-spin" />,
    queued:  <Clock className="h-3 w-3" />,
  }
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-md border ${map[state] ?? "bg-muted text-muted-foreground border-border"}`}>
      {icons[state]}{state}
    </span>
  )
}

// ── Main ───────────────────────────────────────────────────────────────────
export default function DagDetailPage() {
  const { toast } = useToast()
  const params  = useParams()
  const router  = useRouter()
  const dag_id  = params.dag_id as string

  const [dag,        setDag]        = useState<DAG | null>(null)
  const [stats,      setStats]      = useState<DagStats | null>(null)
  const [runs,       setRuns]       = useState<DagRun[]>([])
  const [graphData,  setGraphData]  = useState<{ nodes: any[]; edges: any[] } | null>(null)
  const [taskStates, setTaskStates] = useState<Record<string, string>>({})
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState<string | null>(null)
  const isDraft = useRef(false)
  const [triggerOpen, setTriggerOpen] = useState(false)
  const [triggerConf, setTriggerConf] = useState("{}")
  const [triggering,  setTriggering]  = useState(false)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [showRuns, setShowRuns] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [dagR, statsR, runsR, graphR] = await Promise.all([
        fetch(`/api/airflow/dags/${dag_id}`),
        fetch(`/api/airflow/dags/${dag_id}/stats`),
        fetch(`/api/airflow/dags/${dag_id}/runs?limit=50`),
        fetch(`/api/airflow/dags/${dag_id}/structure`),
      ])

      // If not in Airflow, try loading from saved pipelines (draft)
      if (!dagR.ok) {
        const savedR = await fetch(`/api/pipelines/${dag_id}`)
        if (savedR.ok) {
          const saved = await savedR.json()
          if (saved.status === "draft") {
            // Redirect to editor with saved pipeline loaded
            router.replace(`/pipelines/new?load=${encodeURIComponent(saved.name)}`)
            return
          }
          setDag({ dag_id: saved.name, is_paused: true, is_active: false, description: saved.description, schedule_interval: saved.schedule, tags: [], owners: [] })
          if (saved.nodes?.length) {
            setGraphData({ nodes: saved.nodes, edges: saved.edges || [] })
          }
          isDraft.current = true
          return
        }
        throw new Error("DAG not found")
      }

      setDag(await dagR.json())
      if (statsR.ok) setStats(await statsR.json())
      if (runsR.ok) {
        const rd = await runsR.json()
        setRuns(Array.isArray(rd) ? rd : (rd.dag_runs ?? []))
      }
      if (graphR.ok) setGraphData(await graphR.json())

      // Latest run task states
      const latestRes = await fetch(`/api/airflow/dags/${dag_id}/runs?limit=1`)
      if (latestRes.ok) {
        const lr = await latestRes.json()
        const latest = Array.isArray(lr) ? lr[0] : lr.dag_runs?.[0]
        if (latest?.dag_run_id) {
          const tR = await fetch(`/api/airflow/dags/${dag_id}/dag-runs/${encodeURIComponent(latest.dag_run_id)}/task-instances`)
          if (tR.ok) {
            const td = await tR.json()
            const instances = Array.isArray(td) ? td : (td.task_instances ?? [])
            const map: Record<string,string> = {}
            instances.forEach((t:any) => { if (t.task_id) map[t.task_id] = t.state ?? "none" })
            setTaskStates(map)
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load")
    } finally {
      setLoading(false)
    }
  }, [dag_id])

  // Adaptive polling: 5s when tasks are running, 30s otherwise
  const hasRunningTasks = Object.values(taskStates).some(s => s === "running" || s === "queued")

  useEffect(() => {
    load()
    const interval = hasRunningTasks ? 5000 : 30000
    const t = setInterval(() => { if (!isDraft.current) load() }, interval)
    return () => clearInterval(t)
  }, [load, hasRunningTasks])

  const togglePause = async () => {
    if (!dag) return
    await fetch(`/api/airflow/dags/${dag_id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_paused: !dag.is_paused }),
    })
    setDag({ ...dag, is_paused: !dag.is_paused })
  }

  const triggerRun = async () => {
    setTriggering(true)
    try {
      let conf = {}
      try { conf = JSON.parse(triggerConf) } catch { /* ignore */ }
      const r = await fetch(`/api/airflow/dags/${dag_id}/runs`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conf }),
      })
      if (!r.ok) throw new Error("Trigger failed")
      setTriggerOpen(false); setTriggerConf("{}")
      setTimeout(load, 1500)
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed", "error")
    } finally {
      setTriggering(false)
    }
  }

  // ── Loading ────────────────────────────────────────────────────────────
  if (loading && !dag) return (
    <div className="flex-1 px-6 py-5 space-y-4">
      <Skeleton className="h-8 w-64" />
      <div className="grid grid-cols-4 gap-3">
        {Array(4).fill(0).map((_,i) => <Skeleton key={i} className="h-20" />)}
      </div>
      <Skeleton className="h-[500px]" />
    </div>
  )

  if (error) return (
    <div className="flex-1 p-8">
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    </div>
  )

  const latestRun = runs[0]

  return (
    <div className="flex-1 flex flex-col overflow-hidden" style={{ height: "calc(100vh - 56px)" }}>

      {/* ── Top bar ── */}
      <div className="flex items-center justify-between px-6 h-12 border-b shrink-0 bg-background gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <Button variant="ghost" size="sm" className="h-7 gap-1.5 text-xs shrink-0"
            onClick={() => router.push("/pipelines")}>
            <ArrowLeft className="h-3.5 w-3.5" />Pipelines
          </Button>
          <Separator orientation="vertical" className="h-4" />
          <div className="flex items-center gap-2 min-w-0">
            <GitBranch className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="text-sm font-semibold truncate">{dag_id}</span>
            {dag?.is_paused
              ? <Badge variant="outline" className="text-xs shrink-0">Paused</Badge>
              : <Badge className="text-xs bg-emerald-600 hover:bg-emerald-600 shrink-0">Active</Badge>
            }
          </div>
          {dag?.description && (
            <span className="text-xs text-muted-foreground truncate hidden lg:block">
              {dag.description}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <Button variant="ghost" size="sm" className="h-7 text-xs gap-1.5"
            onClick={load} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
          <Button variant="outline" size="sm" className="h-7 text-xs gap-1.5"
            onClick={togglePause} disabled={!dag}>
            {dag?.is_paused
              ? <><Play className="h-3.5 w-3.5" />Resume</>
              : <><Pause className="h-3.5 w-3.5" />Pause</>
            }
          </Button>
          <Button size="sm" className="h-7 text-xs gap-1.5"
            onClick={() => setTriggerOpen(true)} disabled={dag?.is_paused}>
            <Zap className="h-3.5 w-3.5" />Trigger
          </Button>
        </div>
      </div>

      {/* ── Stats strip ── */}
      <div className="grid grid-cols-6 border-b shrink-0">
        {[
          { label: "Total Runs",    value: stats?.total_runs ?? "—",                 icon: Activity },
          { label: "Success",       value: stats ? `${stats.success_rate.toFixed(0)}%` : "—", icon: TrendingUp,
            sub: stats ? `${stats.success_runs} runs` : undefined,
            color: stats && stats.success_rate >= 90 ? "text-emerald-600" : stats && stats.success_rate < 70 ? "text-red-600" : "" },
          { label: "Failed",        value: stats?.failed_runs ?? "—",                icon: XCircle,
            color: stats && stats.failed_runs > 0 ? "text-red-600" : "" },
          { label: "Running",       value: stats?.running_runs ?? "—",               icon: RefreshCw,
            color: stats && stats.running_runs > 0 ? "text-blue-600" : "" },
          { label: "Avg Duration",  value: fmtDuration(stats?.avg_duration),         icon: Timer },
          { label: "Last Run",      value: latestRun ? timeAgo(latestRun.start_date) : "Never",
            icon: Clock,
            sub: latestRun ? <RunStateBadge state={latestRun.state} /> : undefined },
        ].map(({ label, value, icon: Icon, sub, color }) => (
          <div key={label} className="flex items-center gap-3 px-4 py-2.5 border-r last:border-r-0">
            <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
            <div className="min-w-0">
              <div className="text-[11px] text-muted-foreground">{label}</div>
              {loading && !stats
                ? <Skeleton className="h-5 w-12 mt-0.5" />
                : <div className={`text-sm font-semibold leading-tight ${color ?? ""}`}>{value}</div>
              }
              {sub && <div className="mt-0.5">{sub}</div>}
            </div>
          </div>
        ))}
      </div>

      {/* ── Graph + Context Panel ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* Canvas */}
        <div className="flex-1 overflow-hidden p-2">
          <AssetGraph
            dag_id={dag_id}
            nodes={graphData?.nodes ?? []}
            edges={graphData?.edges ?? []}
            taskStates={taskStates}
            onNodeSelect={setSelectedNodeId}
          />
        </div>

        {/* Context Panel */}
        {selectedNodeId && graphData && (
          <AssetContextPanel
            nodeId={selectedNodeId}
            nodeData={graphData.nodes.find((n: any) => n.id === selectedNodeId)?.data ?? null}
            dagId={dag_id}
            edges={graphData.edges}
            allNodes={graphData.nodes}
            onClose={() => setSelectedNodeId(null)}
          />
        )}
      </div>

      {/* ── Bottom Runs Drawer ── */}
      <div className={`border-t bg-background shrink-0 transition-all ${showRuns ? "h-52" : "h-9"}`}>
        <button
          onClick={() => setShowRuns(!showRuns)}
          className="flex items-center gap-2 px-4 h-9 text-xs text-muted-foreground hover:text-foreground w-full"
        >
          <Activity className="h-3.5 w-3.5" />
          <span>Recent Runs ({runs.length})</span>
          <PanelRightClose className={`h-3 w-3 ml-auto transition-transform ${showRuns ? "rotate-90" : "-rotate-90"}`} />
        </button>
        {showRuns && (
          <div className="overflow-auto h-[calc(100%-36px)] divide-y">
            {runs.slice(0, 10).map(run => (
              <Link
                key={run.dag_run_id}
                href={`/jobs/${encodeURIComponent(run.dag_run_id)}?dag_id=${dag_id}`}
                className="flex items-center gap-4 px-4 py-2 hover:bg-muted/50 transition-colors text-xs"
              >
                <RunStateBadge state={run.state} />
                <span className="font-mono text-muted-foreground truncate flex-1">{run.dag_run_id}</span>
                <span className="text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {fmtDate(run.start_date)}
                </span>
                <span className="text-muted-foreground w-14">
                  {runDuration(run.start_date, run.end_date)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Trigger Dialog */}
      <Dialog open={triggerOpen} onOpenChange={setTriggerOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <Zap className="h-4 w-4" />
              Trigger: {dag_id}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label className="text-xs font-medium">
                Config JSON <span className="text-muted-foreground font-normal">(선택)</span>
              </Label>
              <Textarea
                value={triggerConf}
                onChange={e => setTriggerConf(e.target.value)}
                placeholder='{"date": "2026-05-06", "env": "prod"}'
                className="font-mono text-sm resize-none"
                rows={5}
              />
              <p className="text-[11px] text-muted-foreground">
                DAG에 전달할 파라미터를 JSON으로 입력하세요
              </p>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => setTriggerOpen(false)}>
              Cancel
            </Button>
            <Button size="sm" onClick={triggerRun} disabled={triggering} className="gap-1.5">
              {triggering
                ? <><RefreshCw className="h-3.5 w-3.5 animate-spin" />Triggering...</>
                : <><Zap className="h-3.5 w-3.5" />Trigger Now</>
              }
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
