"use client"

import { useCallback, useEffect, useState } from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
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
import { Alert, AlertDescription } from "@/components/ui/alert"
import { TaskList } from "@/components/airflow/task-list"
import { LogsViewer } from "@/components/airflow/logs-viewer"
import {
  ArrowLeft,
  RefreshCw,
  AlertCircle,
  Calendar,
  Clock,
  CheckCircle2,
  XCircle,
  Play,
  Timer,
} from "lucide-react"
import { formatDistance } from "date-fns"

interface DagRun {
  dag_run_id: string
  dag_id: string
  execution_date: string
  start_date?: string
  end_date?: string
  state: string
  run_type: string
  conf?: Record<string, unknown>
}

interface TaskInstance {
  task_id: string
  dag_id: string
  execution_date: string
  start_date?: string
  end_date?: string
  duration?: number
  state?: string
  try_number?: number
  max_tries?: number
  operator?: string
}

export default function RunDetailPage() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const run_id = params.run_id as string
  const dag_id = searchParams.get("dag_id") || ""

  const [run, setRun] = useState<DagRun | null>(null)
  const [tasks, setTasks] = useState<TaskInstance[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedTask, setSelectedTask] = useState<string | null>(null)
  const [showLogs, setShowLogs] = useState(false)

  const fetchData = useCallback(async () => {
    if (!dag_id) {
      setError("DAG ID is required")
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)

    try {
      // Fetch run details — correct endpoint: /dags/{dag_id}/dag-runs/{run_id}
      const runRes = await fetch(`/api/airflow/dags/${dag_id}/dag-runs/${encodeURIComponent(run_id)}`)
      if (!runRes.ok) throw new Error("Failed to fetch run")
      const runData = await runRes.json()
      setRun(runData)

      // Fetch task instances — correct endpoint: /dags/{dag_id}/dag-runs/{run_id}/task-instances
      const tasksRes = await fetch(`/api/airflow/dags/${dag_id}/dag-runs/${encodeURIComponent(run_id)}/task-instances`)
      if (tasksRes.ok) {
        const tasksData = await tasksRes.json()
        // API returns { task_instances: [...], total_entries: N }
        setTasks(Array.isArray(tasksData) ? tasksData : (tasksData.task_instances ?? []))
      }
    } catch (err) {
      console.error("Failed to fetch data:", err)
      setError(err instanceof Error ? err.message : "Failed to load run")
    } finally {
      setLoading(false)
    }
  }, [dag_id, run_id])

  useEffect(() => {
    if (!run_id || !dag_id) return
    const initial = window.setTimeout(() => { void fetchData() }, 0)
    const interval = window.setInterval(() => {
      if (run?.state === "running") void fetchData()
    }, 5000)

    return () => {
      window.clearTimeout(initial)
      window.clearInterval(interval)
    }
  }, [run_id, dag_id, run?.state, fetchData])

  const handleViewLogs = (taskId: string) => {
    setSelectedTask(taskId)
    setShowLogs(true)
  }

  const getStateIcon = (state: string) => {
    switch (state) {
      case "success":
        return <CheckCircle2 className="h-5 w-5 text-green-500" />
      case "failed":
        return <XCircle className="h-5 w-5 text-red-500" />
      case "running":
        return <RefreshCw className="h-5 w-5 text-blue-500 animate-spin" />
      case "queued":
        return <Clock className="h-5 w-5 text-yellow-500" />
      default:
        return <Clock className="h-5 w-5 text-gray-500" />
    }
  }

  const getStateBadge = (state: string) => {
    switch (state) {
      case "success":
        return <Badge className="bg-green-600">Success</Badge>
      case "failed":
        return <Badge variant="destructive">Failed</Badge>
      case "running":
        return <Badge className="bg-blue-600">Running</Badge>
      case "queued":
        return <Badge className="bg-yellow-600">Queued</Badge>
      default:
        return <Badge variant="secondary">{state}</Badge>
    }
  }

  const calculateDuration = (start?: string, end?: string) => {
    if (!start) return "N/A"
    const startTime = new Date(start)
    const endTime = end ? new Date(end) : new Date()
    const durationMs = endTime.getTime() - startTime.getTime()
    const seconds = Math.floor(durationMs / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)

    if (hours > 0) {
      return `${hours}h ${minutes % 60}m`
    } else if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`
    } else {
      return `${seconds}s`
    }
  }

  const formatTimeAgo = (dateString: string) => {
    try {
      return formatDistance(new Date(dateString), new Date(), { addSuffix: true })
    } catch {
      return dateString
    }
  }

  const successTasks = tasks.filter((t) => t.state === "success").length
  const failedTasks = tasks.filter((t) => t.state === "failed").length
  const runningTasks = tasks.filter((t) => t.state === "running").length
  const totalTasks = tasks.length

  if (loading && !run) {
    return (
      <div className="flex-1 p-8 pt-6">
        <div className="text-center py-12 text-muted-foreground">Loading...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex-1 p-8 pt-6">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
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
            <BreadcrumbLink href="/jobs">Jobs</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{run_id}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" onClick={() => router.back()}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            {run && getStateIcon(run.state)}
            <h2 className="text-3xl font-bold tracking-tight">{dag_id}</h2>
            {run && getStateBadge(run.state)}
          </div>
          <p className="text-muted-foreground ml-11">{run_id}</p>
        </div>

        <div className="flex gap-2">
          <Button variant="outline" onClick={fetchData} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Run Info Card */}
      {run && (
        <Card>
          <CardHeader>
            <CardTitle>Run Information</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <div className="text-muted-foreground flex items-center gap-2">
                  <Play className="h-4 w-4" />
                  Run Type
                </div>
                <div className="font-medium capitalize mt-1">{run.run_type}</div>
              </div>
              <div>
                <div className="text-muted-foreground flex items-center gap-2">
                  <Calendar className="h-4 w-4" />
                  Started
                </div>
                <div className="font-medium mt-1">
                  {run.start_date ? formatTimeAgo(run.start_date) : "Not started"}
                </div>
              </div>
              <div>
                <div className="text-muted-foreground flex items-center gap-2">
                  <Timer className="h-4 w-4" />
                  Duration
                </div>
                <div className="font-medium mt-1">
                  {calculateDuration(run.start_date, run.end_date)}
                </div>
              </div>
              <div>
                <div className="text-muted-foreground flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4" />
                  Progress
                </div>
                <div className="font-medium mt-1">
                  {successTasks}/{totalTasks} tasks
                </div>
              </div>
            </div>

            {run.state === "running" && (
              <div className="mt-4">
                <div className="h-2 bg-secondary rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-600 transition-all duration-500"
                    style={{
                      width: `${totalTasks > 0 ? (successTasks / totalTasks) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Task Stats Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Total Tasks</CardTitle>
              <Play className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalTasks}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Running</CardTitle>
              <RefreshCw className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{runningTasks}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Success</CardTitle>
              <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">{successTasks}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Failed</CardTitle>
              <XCircle className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-600">{failedTasks}</div>
          </CardContent>
        </Card>
      </div>

      {/* Task List */}
      <TaskList tasks={tasks} onViewLogs={handleViewLogs} />

      {/* Logs Viewer */}
      {selectedTask && run && (
        <LogsViewer
          taskId={selectedTask}
          dagId={dag_id}
          runId={run_id}
          tryNumber={1}
          isOpen={showLogs}
          onClose={() => {
            setShowLogs(false)
            setSelectedTask(null)
          }}
          autoRefresh={run.state === "running"}
        />
      )}
    </div>
  )
}
