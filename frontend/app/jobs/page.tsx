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
import {
  Boxes,
  Plus,
  CheckCircle2,
  XCircle,
  Clock,
  RefreshCw,
  AlertCircle,
  Play,
  Calendar,
  Timer,
  ExternalLink,
} from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { formatDistance } from "date-fns"
import Link from "next/link"

interface DagRun {
  dag_run_id: string
  dag_id: string
  execution_date: string
  start_date?: string
  end_date?: string
  state: string
  run_type: string
}

export default function JobsPage() {
  const [runs, setRuns] = useState<DagRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = async () => {
    setLoading(true)
    setError(null)

    try {
      // Fetch all DAGs first
      const dagsRes = await fetch("/api/airflow/dags?limit=100")
      if (!dagsRes.ok) throw new Error("Failed to fetch DAGs")
      const dagsData = await dagsRes.json()
      const dags: { dag_id: string }[] = Array.isArray(dagsData) ? dagsData : (dagsData.dags ?? [])

      // Fetch recent runs for each DAG
      const runsPromises = dags.map(async (dag: { dag_id: string }) => {
        try {
          const runsRes = await fetch(`/api/airflow/dags/${dag.dag_id}/runs?limit=10`)
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

      setRuns(allRuns)
    } catch (err) {
      console.error("Failed to fetch data:", err)
      setError(err instanceof Error ? err.message : "Failed to load jobs")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()

    // Refresh every 10 seconds for running jobs
    const interval = setInterval(fetchData, 10000)
    return () => clearInterval(interval)
  }, [])

  const getStateIcon = (state: string) => {
    switch (state) {
      case "success":
        return <CheckCircle2 className="h-4 w-4 text-green-500" />
      case "failed":
        return <XCircle className="h-4 w-4 text-red-500" />
      case "running":
        return <RefreshCw className="h-4 w-4 text-blue-500 animate-spin" />
      case "queued":
        return <Clock className="h-4 w-4 text-yellow-500" />
      default:
        return <Clock className="h-4 w-4 text-gray-500" />
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
    if (!start) return null
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

  const successRuns = runs.filter((r) => r.state === "success").length
  const failedRuns = runs.filter((r) => r.state === "failed").length
  const runningRuns = runs.filter((r) => r.state === "running").length
  const queuedRuns = runs.filter((r) => r.state === "queued").length
  const successRate = runs.length > 0 ? (successRuns / runs.length) * 100 : 0

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
            <BreadcrumbPage>Jobs</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Job Management</h2>
          <p className="text-muted-foreground">
            Monitor and control Airflow DAG runs
          </p>
        </div>

        <div className="flex gap-2">
          <Button variant="outline" onClick={fetchData} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Statistics Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Total Runs</CardTitle>
              <Boxes className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{runs.length}</div>
            <p className="text-xs text-muted-foreground mt-1">Recent executions</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Running Now</CardTitle>
              <RefreshCw className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{runningRuns}</div>
            <p className="text-xs text-muted-foreground mt-1">
              {queuedRuns} queued
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Success Rate</CardTitle>
              <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{successRate.toFixed(0)}%</div>
            <p className="text-xs text-muted-foreground mt-1">
              {successRuns} successful
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Failed Runs</CardTitle>
              <XCircle className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{failedRuns}</div>
            <p className="text-xs text-muted-foreground mt-1">Require attention</p>
          </CardContent>
        </Card>
      </div>

      {/* Jobs List */}
      <Tabs defaultValue="all" className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xl font-semibold">Job Runs</h3>
          <TabsList>
            <TabsTrigger value="all">All ({runs.length})</TabsTrigger>
            <TabsTrigger value="running">Running ({runningRuns})</TabsTrigger>
            <TabsTrigger value="failed">Failed ({failedRuns})</TabsTrigger>
            <TabsTrigger value="success">Success ({successRuns})</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="all" className="space-y-3">
          {loading ? (
            <div className="text-center py-8 text-muted-foreground">Loading...</div>
          ) : runs.length === 0 ? (
            <Card>
              <CardContent className="py-8">
                <div className="text-center space-y-3">
                  <Boxes className="h-12 w-12 mx-auto text-muted-foreground opacity-50" />
                  <p className="text-muted-foreground">No job runs found</p>
                </div>
              </CardContent>
            </Card>
          ) : (
            runs.map((run) => (
              <Card key={run.dag_run_id} className="hover:shadow-md transition-shadow">
                <CardContent className="p-6">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 space-y-3">
                      {/* Header */}
                      <div className="flex items-center gap-3">
                        {getStateIcon(run.state)}
                        <div className="flex-1">
                          <h4 className="text-lg font-semibold">{run.dag_id}</h4>
                          <p className="text-sm text-muted-foreground">{run.dag_run_id}</p>
                        </div>
                        {getStateBadge(run.state)}
                      </div>

                      {/* Details Grid */}
                      <div className="grid grid-cols-3 gap-4 text-sm">
                        <div className="flex items-center gap-2">
                          <Play className="h-4 w-4 text-muted-foreground" />
                          <div>
                            <span className="text-muted-foreground">Type:</span>
                            <span className="ml-2 font-medium capitalize">{run.run_type}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <Calendar className="h-4 w-4 text-muted-foreground" />
                          <div>
                            <span className="text-muted-foreground">Started:</span>
                            <span className="ml-2 font-medium">
                              {run.start_date ? formatTimeAgo(run.start_date) : "Not started"}
                            </span>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <Timer className="h-4 w-4 text-muted-foreground" />
                          <div>
                            <span className="text-muted-foreground">Duration:</span>
                            <span className="ml-2 font-medium">
                              {calculateDuration(run.start_date, run.end_date) || "N/A"}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Progress Bar (only for running jobs) */}
                      {run.state === "running" && run.start_date && (
                        <div className="space-y-1">
                          <div className="h-2 bg-secondary rounded-full overflow-hidden">
                            <div className="h-full bg-blue-600 animate-pulse w-2/3" />
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="flex gap-2 ml-4">
                      <Link href={`/jobs/${run.dag_run_id}?dag_id=${run.dag_id}`}>
                        <Button variant="outline" size="sm">
                          <ExternalLink className="h-4 w-4 mr-1" />
                          View Details
                        </Button>
                      </Link>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </TabsContent>

        <TabsContent value="running" className="space-y-3">
          {runs
            .filter((r) => r.state === "running")
            .map((run) => (
              <Card key={run.dag_run_id} className="hover:shadow-md transition-shadow">
                <CardContent className="p-6">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 space-y-3">
                      <div className="flex items-center gap-3">
                        {getStateIcon(run.state)}
                        <div className="flex-1">
                          <h4 className="text-lg font-semibold">{run.dag_id}</h4>
                          <p className="text-sm text-muted-foreground">{run.dag_run_id}</p>
                        </div>
                        {getStateBadge(run.state)}
                      </div>
                      <div className="h-2 bg-secondary rounded-full overflow-hidden">
                        <div className="h-full bg-blue-600 animate-pulse w-2/3" />
                      </div>
                    </div>
                    <Link href={`/jobs/${run.dag_run_id}?dag_id=${run.dag_id}`}>
                      <Button variant="outline" size="sm">
                        <ExternalLink className="h-4 w-4" />
                      </Button>
                    </Link>
                  </div>
                </CardContent>
              </Card>
            ))}
        </TabsContent>

        <TabsContent value="failed" className="space-y-3">
          {runs
            .filter((r) => r.state === "failed")
            .map((run) => (
              <Card key={run.dag_run_id} className="hover:shadow-md transition-shadow">
                <CardContent className="p-6">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 space-y-3">
                      <div className="flex items-center gap-3">
                        {getStateIcon(run.state)}
                        <div className="flex-1">
                          <h4 className="text-lg font-semibold">{run.dag_id}</h4>
                          <p className="text-sm text-muted-foreground">{run.dag_run_id}</p>
                        </div>
                        {getStateBadge(run.state)}
                      </div>
                    </div>
                    <Link href={`/jobs/${run.dag_run_id}?dag_id=${run.dag_id}`}>
                      <Button variant="outline" size="sm">
                        <ExternalLink className="h-4 w-4" />
                      </Button>
                    </Link>
                  </div>
                </CardContent>
              </Card>
            ))}
        </TabsContent>

        <TabsContent value="success" className="space-y-3">
          {runs
            .filter((r) => r.state === "success")
            .map((run) => (
              <Card key={run.dag_run_id} className="hover:shadow-md transition-shadow">
                <CardContent className="p-6">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 space-y-3">
                      <div className="flex items-center gap-3">
                        {getStateIcon(run.state)}
                        <div className="flex-1">
                          <h4 className="text-lg font-semibold">{run.dag_id}</h4>
                          <p className="text-sm text-muted-foreground">{run.dag_run_id}</p>
                        </div>
                        {getStateBadge(run.state)}
                      </div>
                    </div>
                    <Link href={`/jobs/${run.dag_run_id}?dag_id=${run.dag_id}`}>
                      <Button variant="outline" size="sm">
                        <ExternalLink className="h-4 w-4" />
                      </Button>
                    </Link>
                  </div>
                </CardContent>
              </Card>
            ))}
        </TabsContent>
      </Tabs>
    </div>
  )
}
