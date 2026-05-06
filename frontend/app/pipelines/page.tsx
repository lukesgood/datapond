"use client"

import { useEffect, useState } from "react"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { DagCard } from "@/components/airflow/dag-card"
import { DagRunList } from "@/components/airflow/dag-run-list"
import { useRouter } from "next/navigation"
import {
  Workflow,
  Plus,
  Clock,
  TrendingUp,
  XCircle,
  AlertCircle,
  RefreshCw,
} from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"

interface DAG {
  dag_id: string
  is_paused: boolean
  is_active: boolean
  description?: string
  schedule_interval?: string
  tags: string[]
}

interface DagStats {
  dag_id: string
  total_runs: number
  success_runs: number
  failed_runs: number
  running_runs: number
  success_rate: number
  avg_duration?: number
}

interface DagRun {
  dag_run_id: string
  dag_id: string
  execution_date: string
  start_date?: string
  end_date?: string
  state: string
  run_type: string
}

export default function PipelinesPage() {
  const [dags, setDags] = useState<DAG[]>([])
  const [dagStats, setDagStats] = useState<Map<string, DagStats>>(new Map())
  const [recentRuns, setRecentRuns] = useState<DagRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [savedStatuses, setSavedStatuses] = useState<Map<string, string>>(new Map())
  const router = useRouter()

  const fetchData = async () => {
    setLoading(true)
    setError(null)

    try {
      // Fetch all DAGs
      const dagsRes = await fetch("/api/airflow/dags?limit=100")
      if (!dagsRes.ok) throw new Error("Failed to fetch DAGs")
      const dagsData = await dagsRes.json()
      const dagsList: DAG[] = Array.isArray(dagsData) ? dagsData : (dagsData.dags ?? [])
      setDags(dagsList)

      // Fetch saved pipeline statuses
      try {
        const savedRes = await fetch("/api/pipelines")
        if (savedRes.ok) {
          const savedData = await savedRes.json()
          const map = new Map<string, string>()
          for (const p of savedData.pipelines || []) {
            map.set(p.name, p.status)
            map.set(`datapond_${p.name}`, p.status)
            // Add saved pipelines not yet in Airflow to the DAG list
            const dagId = p.name
            if (!dagsList.find(d => d.dag_id === dagId || d.dag_id === `datapond_${dagId}`)) {
              dagsList.push({
                dag_id: dagId,
                is_paused: true,
                is_active: false,
                description: p.schedule ? `Schedule: ${p.schedule}` : undefined,
                schedule_interval: p.schedule,
                tags: [],
              })
            }
          }
          setSavedStatuses(map)
          setDags([...dagsList])
        }
      } catch { /* non-critical */ }

      // Fetch stats for each DAG
      const statsPromises = dagsList.map(async (dag: DAG) => {
        try {
          const statsRes = await fetch(`/api/airflow/dags/${dag.dag_id}/stats`)
          if (statsRes.ok) {
            const stats = await statsRes.json()
            return [dag.dag_id, stats] as [string, DagStats]
          }
        } catch (err) {
          console.error(`Failed to fetch stats for ${dag.dag_id}:`, err)
        }
        return null
      })

      const statsResults = await Promise.all(statsPromises)
      const statsMap = new Map(
        statsResults.filter((r): r is [string, DagStats] => r !== null)
      )
      setDagStats(statsMap)

      // Fetch recent runs across all DAGs
      const runsPromises = dagsList.slice(0, 5).map(async (dag: DAG) => {
        try {
          const runsRes = await fetch(`/api/airflow/dags/${dag.dag_id}/runs?limit=5`)
          if (runsRes.ok) {
            return await runsRes.json()
          }
        } catch (err) {
          console.error(`Failed to fetch runs for ${dag.dag_id}:`, err)
        }
        return []
      })

      const runsResults = await Promise.all(runsPromises)
      const allRuns = runsResults.flat()
      // Sort by execution date descending
      allRuns.sort((a, b) =>
        new Date(b.execution_date).getTime() - new Date(a.execution_date).getTime()
      )
      setRecentRuns(allRuns.slice(0, 10))
    } catch (err) {
      console.error("Failed to fetch data:", err)
      setError(err instanceof Error ? err.message : "Failed to load pipelines")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()

    // Refresh every 30 seconds
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [])

  const handleTriggerDag = async (dag_id: string) => {
    try {
      const response = await fetch(`/api/airflow/dags/${dag_id}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conf: {} }),
      })
      if (response.ok) {
        // Refresh data to show new run
        fetchData()
      } else {
        throw new Error("Failed to trigger DAG")
      }
    } catch (err) {
      console.error("Failed to trigger DAG:", err)
      alert("Failed to trigger DAG")
    }
  }

  const handleTogglePause = async (dag_id: string, is_paused: boolean) => {
    try {
      const response = await fetch(`/api/airflow/dags/${dag_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_paused }),
      })
      if (response.ok) {
        // Update local state
        setDags((prevDags) =>
          prevDags.map((dag) =>
            dag.dag_id === dag_id ? { ...dag, is_paused } : dag
          )
        )
      } else {
        throw new Error("Failed to update DAG")
      }
    } catch (err) {
      console.error("Failed to toggle pause:", err)
      alert("Failed to update DAG")
    }
  }

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    try {
      const response = await fetch(`/api/pipelines/${deleteTarget}`, { method: "DELETE" })
      if (response.ok) {
        setDags((prev) => prev.filter((d) => d.dag_id !== deleteTarget))
      } else {
        throw new Error("Failed to delete pipeline")
      }
    } catch (err) {
      console.error("Failed to delete:", err)
      alert("파이프라인 삭제에 실패했습니다.")
    } finally {
      setDeleteTarget(null)
    }
  }

  const handleEdit = (dag_id: string) => {
    router.push(`/pipelines/${dag_id}`)
  }

  const activeDags = dags.filter((d) => !d.is_paused)
  const pausedDags = dags.filter((d) => d.is_paused)
  const runningDags = Array.from(dagStats.values()).filter((s) => s.running_runs > 0).length
  const avgSuccessRate =
    dagStats.size > 0
      ? Array.from(dagStats.values()).reduce((acc, s) => acc + s.success_rate, 0) / dagStats.size
      : 0

  // DAG 카드 공통 렌더 함수
  const renderDagCards = (list: DAG[]) => {
    if (loading) return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="rounded-lg border bg-card p-4 space-y-3 animate-pulse">
            <div className="h-4 bg-muted rounded w-2/3" />
            <div className="h-3 bg-muted rounded w-full" />
            <div className="h-3 bg-muted rounded w-1/2" />
            <div className="h-1 bg-muted rounded w-full" />
            <div className="flex gap-2">
              <div className="h-7 bg-muted rounded flex-1" />
              <div className="h-7 w-7 bg-muted rounded" />
              <div className="h-7 w-7 bg-muted rounded" />
            </div>
          </div>
        ))}
      </div>
    )
    if (list.length === 0) return (
      <div className="flex flex-col items-center justify-center py-16 text-center border rounded-lg bg-muted/20">
        <Workflow className="h-10 w-10 text-muted-foreground/30 mb-3" />
        <p className="text-sm text-muted-foreground">No pipelines found</p>
      </div>
    )
    return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {list.map((dag) => {
          const stats = dagStats.get(dag.dag_id)
          return (
            <DagCard
              key={dag.dag_id}
              dag_id={dag.dag_id}
              is_paused={dag.is_paused}
              description={dag.description}
              schedule_interval={dag.schedule_interval}
              last_run_state={
                stats?.running_runs ? "running" :
                stats?.success_runs ? "success" :
                stats?.failed_runs  ? "failed"  : "none"
              }
              success_rate={stats?.success_rate}
              savedStatus={savedStatuses.get(dag.dag_id)}
              onTrigger={handleTriggerDag}
              onTogglePause={handleTogglePause}
              onDelete={(id) => setDeleteTarget(id)}
              onEdit={handleEdit}
            />
          )
        })}
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-5 px-6 py-5">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Data Pipelines</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Airflow DAG 오케스트레이션
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchData} disabled={loading} className="h-8 text-xs gap-1.5">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button size="sm" className="h-8 text-xs gap-1.5"
            onClick={() => router.push("/pipelines/new")}>
            <Plus className="h-3.5 w-3.5" />
            New Pipeline
          </Button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Stats strip */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total", value: dags.length, sub: `${activeDags.length} active`, icon: Workflow },
          { label: "Running", value: runningDags, sub: "Executions", icon: Clock, accent: runningDags > 0 },
          { label: "Success Rate", value: `${avgSuccessRate.toFixed(0)}%`, sub: "Avg", icon: TrendingUp },
          {
            label: "Failed",
            value: Array.from(dagStats.values()).reduce((a, s) => a + s.failed_runs, 0),
            sub: "Last 100 runs",
            icon: XCircle,
            accent: Array.from(dagStats.values()).reduce((a, s) => a + s.failed_runs, 0) > 0,
          },
        ].map(({ label, value, sub, icon: Icon, accent }) => (
          <Card key={label} className={accent ? "border-red-200 bg-red-50/30" : ""}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-muted-foreground">{label}</span>
                <Icon className={`h-3.5 w-3.5 ${accent ? "text-red-400" : "text-muted-foreground"}`} />
              </div>
              <div className={`text-2xl font-bold ${accent ? "text-red-600" : ""}`}>{value}</div>
              <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Main: DAG list + recent runs */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_260px] gap-5">

        {/* DAG list */}
        <div className="space-y-3">
          <Tabs defaultValue="all">
            <div className="flex items-center justify-between mb-3">
              <TabsList className="h-8">
                <TabsTrigger value="all" className="text-xs h-7">All ({dags.length})</TabsTrigger>
                <TabsTrigger value="active" className="text-xs h-7">Active ({activeDags.length})</TabsTrigger>
                <TabsTrigger value="paused" className="text-xs h-7">Paused ({pausedDags.length})</TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="all">{renderDagCards(dags)}</TabsContent>
            <TabsContent value="active">{renderDagCards(activeDags)}</TabsContent>
            <TabsContent value="paused">{renderDagCards(pausedDags)}</TabsContent>
          </Tabs>
        </div>

        {/* Recent runs — sticky top so it stays visible while scrolling DAG list */}
        <div className="border rounded-lg bg-card p-4 self-start sticky top-4">
          <DagRunList runs={recentRuns} showDagId={true} />
        </div>
      </div>

      {/* Delete confirmation dialog */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>파이프라인 삭제</AlertDialogTitle>
            <AlertDialogDescription>
              <strong>{deleteTarget}</strong> 파이프라인을 삭제하시겠습니까?
              DAG 파일이 제거되고 실행 기록은 보존됩니다. 이 작업은 되돌릴 수 없습니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>취소</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteConfirm} className="bg-red-600 hover:bg-red-700">
              삭제
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

    </div>
  )
}
