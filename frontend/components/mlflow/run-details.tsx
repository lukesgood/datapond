"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { MetricsChart } from "./metrics-chart"
import {
  PlayCircle,
  CheckCircle,
  XCircle,
  Clock,
  User,
  GitBranch,
  Download,
  ExternalLink,
} from "lucide-react"
import { useState, useEffect } from "react"

interface RunDetailsProps {
  run: {
    info: {
      run_id: string
      run_name?: string
      experiment_id: string
      status: string
      start_time: number
      end_time?: number
      lifecycle_stage: string
      user_id?: string
    }
    data: {
      metrics?: Array<{ key: string; value: number; timestamp: number; step: number }>
      params?: Array<{ key: string; value: string }>
      tags?: Array<{ key: string; value: string }>
    }
  }
}

export function RunDetails({ run }: RunDetailsProps) {
  const [metricHistory, setMetricHistory] = useState<Record<string, any[]>>({})
  const [artifacts, setArtifacts] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  const getStatusIcon = () => {
    switch (run.info.status) {
      case "RUNNING":
        return <PlayCircle className="h-5 w-5 text-blue-500" />
      case "FINISHED":
        return <CheckCircle className="h-5 w-5 text-green-500" />
      case "FAILED":
        return <XCircle className="h-5 w-5 text-red-500" />
      default:
        return <Clock className="h-5 w-5 text-gray-500" />
    }
  }

  const getStatusBadge = () => {
    switch (run.info.status) {
      case "RUNNING":
        return <Badge className="bg-blue-600">Running</Badge>
      case "FINISHED":
        return <Badge className="bg-green-600">Finished</Badge>
      case "FAILED":
        return <Badge variant="destructive">Failed</Badge>
      default:
        return <Badge variant="outline">{run.info.status}</Badge>
    }
  }

  const formatDuration = () => {
    if (!run.info.end_time) return "Running..."
    const duration = run.info.end_time - run.info.start_time
    const seconds = Math.floor(duration / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)

    if (hours > 0) return `${hours}h ${minutes % 60}m`
    if (minutes > 0) return `${minutes}m ${seconds % 60}s`
    return `${seconds}s`
  }

  const formatTimestamp = (timestamp: number) => {
    return new Date(timestamp).toLocaleString()
  }

  useEffect(() => {
    // Fetch metric history for each metric
    const fetchMetricHistory = async () => {
      setLoading(true)
      try {
        // In real implementation, fetch from API
        // For now, use the single data point we have
        const history: Record<string, any[]> = {}
        run.data.metrics?.forEach((metric) => {
          if (!history[metric.key]) {
            history[metric.key] = []
          }
          history[metric.key].push({
            step: metric.step,
            timestamp: metric.timestamp,
            value: metric.value,
          })
        })
        setMetricHistory(history)
      } catch (error) {
        console.error("Error fetching metric history:", error)
      } finally {
        setLoading(false)
      }
    }

    fetchMetricHistory()
  }, [run])

  return (
    <div className="space-y-6">
      {/* Run Header */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                {getStatusIcon()}
                <CardTitle>
                  {run.info.run_name || `Run ${run.info.run_id.substring(0, 8)}`}
                </CardTitle>
                {getStatusBadge()}
              </div>
              <p className="text-sm text-muted-foreground font-mono">{run.info.run_id}</p>
            </div>
            <Button variant="outline" size="sm">
              <ExternalLink className="mr-2 h-4 w-4" />
              Open in MLflow
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-sm text-muted-foreground">Started</p>
              <p className="text-sm font-medium">{formatTimestamp(run.info.start_time)}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Duration</p>
              <p className="text-sm font-medium">{formatDuration()}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">User</p>
              <p className="text-sm font-medium flex items-center gap-1">
                <User className="h-3 w-3" />
                {run.info.user_id || "Unknown"}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Lifecycle</p>
              <p className="text-sm font-medium">{run.info.lifecycle_stage}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="metrics">Metrics</TabsTrigger>
          <TabsTrigger value="parameters">Parameters</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          {/* Quick Metrics Summary */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {run.data.metrics?.slice(0, 6).map((metric) => (
              <Card key={metric.key}>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium">{metric.key}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{metric.value.toFixed(4)}</div>
                  <p className="text-xs text-muted-foreground">Step {metric.step}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Tags */}
          {run.data.tags && run.data.tags.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Tags</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2">
                  {run.data.tags.map((tag) => (
                    <Badge key={tag.key} variant="outline">
                      {tag.key}: {tag.value}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="metrics" className="space-y-4">
          {Object.entries(metricHistory).map(([key, data]) => (
            <MetricsChart
              key={key}
              title={key}
              data={data}
              metricKey="value"
              color="#8b5cf6"
            />
          ))}
          {Object.keys(metricHistory).length === 0 && (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground">
                No metrics recorded for this run
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="parameters">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Parameters</CardTitle>
            </CardHeader>
            <CardContent>
              {run.data.params && run.data.params.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Parameter</TableHead>
                      <TableHead>Value</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {run.data.params.map((param) => (
                      <TableRow key={param.key}>
                        <TableCell className="font-medium">{param.key}</TableCell>
                        <TableCell className="font-mono text-sm">{param.value}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-center text-muted-foreground py-8">
                  No parameters recorded for this run
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="artifacts">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Artifacts</CardTitle>
            </CardHeader>
            <CardContent>
              {artifacts.length > 0 ? (
                <div className="space-y-2">
                  {artifacts.map((artifact, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between p-3 border rounded-lg"
                    >
                      <span className="font-mono text-sm">{artifact.path}</span>
                      <Button variant="outline" size="sm">
                        <Download className="mr-2 h-4 w-4" />
                        Download
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-center text-muted-foreground py-8">
                  No artifacts for this run
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
