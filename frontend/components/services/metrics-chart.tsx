"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Cpu, MemoryStick } from "lucide-react"

// Mirrors backend ServiceMetrics (backend/app/api/services.py) exactly —
// there is no cpu_usage/memory_usage/network_*/disk_usage/history on the
// real endpoint, so we never fabricate those.
export interface ServicePodMetric {
  name: string
  cpu: string
  memory: string
}

export interface ServiceMetricsData {
  service: string
  pods: ServicePodMetric[]
  total_cpu?: string | null
  total_memory?: string | null
}

interface MetricsChartProps {
  metrics: ServiceMetricsData | null
  loading?: boolean
}

export function MetricsChart({ metrics, loading = false }: MetricsChartProps) {
  if (loading) {
    return (
      <div className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          {[...Array(2)].map((_, i) => (
            <Skeleton key={i} className="h-[120px]" />
          ))}
        </div>
        <Skeleton className="h-[200px]" />
      </div>
    )
  }

  if (!metrics) {
    return (
      <Card>
        <CardContent className="p-8">
          <div className="text-muted-foreground text-center">
            No metrics available
          </div>
        </CardContent>
      </Card>
    )
  }

  const pods = metrics.pods ?? []
  const hasPods = pods.length > 0

  return (
    <div className="space-y-4">
      {/* Current Metrics Cards — real totals from metrics-server, no fabrication */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Total CPU</CardTitle>
              <Cpu className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics.total_cpu || "N/A"}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Summed across {pods.length} pod{pods.length === 1 ? "" : "s"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Total Memory</CardTitle>
              <MemoryStick className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics.total_memory || "N/A"}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Summed across {pods.length} pod{pods.length === 1 ? "" : "s"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Per-pod breakdown — only when metrics-server actually returned pods */}
      {hasPods ? (
        <Card>
          <CardHeader>
            <CardTitle>Per-Pod Usage</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Pod</TableHead>
                    <TableHead>CPU</TableHead>
                    <TableHead>Memory</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pods.map((pod) => (
                    <TableRow key={pod.name}>
                      <TableCell className="font-mono text-xs">{pod.name}</TableCell>
                      <TableCell>{pod.cpu}</TableCell>
                      <TableCell>{pod.memory}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            No per-pod metrics available — metrics-server may not be installed,
            or this service has no running pods.
          </CardContent>
        </Card>
      )}
    </div>
  )
}
