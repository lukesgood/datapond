"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts"
import { Cpu, MemoryStick, Network, HardDrive } from "lucide-react"

interface MetricsData {
  cpu_usage?: number
  memory_usage?: number
  network_in?: number
  network_out?: number
  disk_usage?: number
  history?: {
    timestamp: string
    cpu: number
    memory: number
  }[]
}

interface MetricsChartProps {
  metrics: MetricsData | null
  loading?: boolean
}

export function MetricsChart({ metrics, loading = false }: MetricsChartProps) {
  if (loading) {
    return (
      <div className="space-y-4">
        <div className="grid gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-[120px]" />
          ))}
        </div>
        <Skeleton className="h-[300px]" />
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

  // Generate mock history data if not available
  const historyData = metrics.history || generateMockHistory(metrics)

  return (
    <div className="space-y-4">
      {/* Current Metrics Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">CPU Usage</CardTitle>
              <Cpu className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics.cpu_usage?.toFixed(1) || 0}%
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {getCpuStatus(metrics.cpu_usage || 0)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Memory</CardTitle>
              <MemoryStick className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics.memory_usage?.toFixed(1) || 0}%
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {getMemoryStatus(metrics.memory_usage || 0)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Network I/O</CardTitle>
              <Network className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-sm font-bold">
              ↓ {formatBytes(metrics.network_in || 0)}/s
            </div>
            <div className="text-sm font-bold mt-1">
              ↑ {formatBytes(metrics.network_out || 0)}/s
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Disk Usage</CardTitle>
              <HardDrive className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics.disk_usage?.toFixed(1) || 0}%
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {getDiskStatus(metrics.disk_usage || 0)}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* CPU Usage Chart */}
      <Card>
        <CardHeader>
          <CardTitle>CPU Usage History</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={historyData}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis
                dataKey="timestamp"
                className="text-xs"
                tickFormatter={(value) => {
                  const date = new Date(value)
                  return date.toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                }}
              />
              <YAxis className="text-xs" domain={[0, 100]} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--popover))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "var(--radius)",
                }}
                labelFormatter={(value) => {
                  return new Date(value).toLocaleString()
                }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="cpu"
                stroke="hsl(var(--primary))"
                strokeWidth={2}
                name="CPU %"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* Memory Usage Chart */}
      <Card>
        <CardHeader>
          <CardTitle>Memory Usage History</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={historyData}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis
                dataKey="timestamp"
                className="text-xs"
                tickFormatter={(value) => {
                  const date = new Date(value)
                  return date.toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                }}
              />
              <YAxis className="text-xs" domain={[0, 100]} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--popover))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "var(--radius)",
                }}
                labelFormatter={(value) => {
                  return new Date(value).toLocaleString()
                }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="memory"
                stroke="hsl(var(--chart-2))"
                strokeWidth={2}
                name="Memory %"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  )
}

// Helper functions
function getCpuStatus(usage: number): string {
  if (usage < 50) return "Normal"
  if (usage < 80) return "Moderate"
  return "High"
}

function getMemoryStatus(usage: number): string {
  if (usage < 70) return "Normal"
  if (usage < 90) return "High"
  return "Critical"
}

function getDiskStatus(usage: number): string {
  if (usage < 70) return "Normal"
  if (usage < 85) return "Warning"
  return "Critical"
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

function generateMockHistory(current: MetricsData) {
  const now = Date.now()
  const data = []

  for (let i = 60; i >= 0; i--) {
    const timestamp = new Date(now - i * 60000).toISOString()
    const cpu = (current.cpu_usage || 0) + (Math.random() - 0.5) * 20
    const memory = (current.memory_usage || 0) + (Math.random() - 0.5) * 15

    data.push({
      timestamp,
      cpu: Math.max(0, Math.min(100, cpu)),
      memory: Math.max(0, Math.min(100, memory)),
    })
  }

  return data
}
