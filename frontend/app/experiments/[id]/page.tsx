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
  Plus,
  GitBranch,
  PlayCircle,
  CheckCircle,
  XCircle,
  Clock,
  ExternalLink,
  TrendingUp,
  BarChart3,
} from "lucide-react"
import { MultiMetricsChart } from "@/components/mlflow/metrics-chart"
import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"

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

export default function ExperimentDetailPage({ params }: { params: { id: string } }) {
  const router = useRouter()
  const [experiment, setExperiment] = useState<any>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedRuns, setSelectedRuns] = useState<string[]>([])
  const [sortBy, setSortBy] = useState<string>("start_time")

  useEffect(() => {
    fetchExperimentDetails()
  }, [params.id])

  const fetchExperimentDetails = async () => {
    setLoading(true)
    try {
      // Fetch experiment info
      const expRes = await fetch(`/api/mlflow/experiments/${params.id}`)
      const expData = await expRes.json()
      setExperiment(expData.experiment)

      // Fetch runs
      const runsRes = await fetch(`/api/mlflow/experiments/${params.id}/runs`)
      const runsData = await runsRes.json()
      setRuns(runsData.runs || [])
    } catch (error) {
      console.error("Error fetching experiment details:", error)
    } finally {
      setLoading(false)
    }
  }

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
    switch (status) {
      case "RUNNING":
        return <Badge className="bg-blue-600">Running</Badge>
      case "FINISHED":
        return <Badge className="bg-green-600">Finished</Badge>
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

  const getMetricValue = (run: Run, metricKey: string) => {
    const metric = run.data.metrics?.find((m) => m.key === metricKey)
    return metric ? metric.value.toFixed(4) : "-"
  }

  const getParamValue = (run: Run, paramKey: string) => {
    const param = run.data.params?.find((p) => p.key === paramKey)
    return param ? param.value : "-"
  }

  // Get all unique metric keys
  const allMetrics = Array.from(
    new Set(runs.flatMap((run) => run.data.metrics?.map((m) => m.key) || []))
  )

  // Get all unique param keys
  const allParams = Array.from(
    new Set(runs.flatMap((run) => run.data.params?.map((p) => p.key) || []))
  )

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Card>
          <CardContent className="py-8 text-center">
            <p className="text-muted-foreground">Loading experiment...</p>
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
            <p className="text-muted-foreground">Experiment not found</p>
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
          <Button variant="outline" size="sm" disabled>
            <Plus className="mr-2 h-4 w-4" />
            New Run
          </Button>
          {selectedRuns.length > 0 && (
            <Button variant="default" size="sm">
              <BarChart3 className="mr-2 h-4 w-4" />
              Compare {selectedRuns.length} Runs
            </Button>
          )}
          <Button
            variant="default"
            size="sm"
            onClick={() =>
              window.open(
                `http://datapond.local/mlflow/#/experiments/${params.id}`,
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
                    <Checkbox />
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
                {runs.map((run) => (
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
                    {allMetrics.slice(0, 3).map((metric) => (
                      <TableCell key={metric} className="font-mono text-sm">
                        {getMetricValue(run, metric)}
                      </TableCell>
                    ))}
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

      {/* Metrics Comparison (if runs selected) */}
      {selectedRuns.length > 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Metrics Comparison</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">
              Comparing {selectedRuns.length} runs - detailed comparison view coming soon
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
