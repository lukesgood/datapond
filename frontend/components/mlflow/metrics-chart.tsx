"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts"

interface MetricDataPoint {
  step: number
  timestamp: number
  value: number
}

interface MetricsChartProps {
  title: string
  data: MetricDataPoint[]
  metricKey?: string
  color?: string
}

export function MetricsChart({
  title,
  data,
  metricKey = "value",
  color = "#8b5cf6"
}: MetricsChartProps) {
  // Transform data for recharts
  const chartData = data.map((point) => ({
    step: point.step,
    [metricKey]: point.value,
    timestamp: new Date(point.timestamp).toLocaleString(),
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis
              dataKey="step"
              label={{ value: "Step", position: "insideBottom", offset: -5 }}
              className="text-xs"
            />
            <YAxis
              label={{ value: "Value", angle: -90, position: "insideLeft" }}
              className="text-xs"
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: "6px",
              }}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey={metricKey}
              stroke={color}
              strokeWidth={2}
              dot={{ fill: color, r: 3 }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}

interface MultiMetricsChartProps {
  title: string
  metrics: {
    name: string
    data: MetricDataPoint[]
    color: string
  }[]
}

export function MultiMetricsChart({ title, metrics }: MultiMetricsChartProps) {
  // Combine all metrics into single dataset
  const allSteps = new Set<number>()
  metrics.forEach(metric => {
    metric.data.forEach(point => allSteps.add(point.step))
  })

  const chartData = Array.from(allSteps).sort((a, b) => a - b).map(step => {
    const dataPoint: Record<string, number | null> = { step }
    metrics.forEach(metric => {
      const point = metric.data.find(p => p.step === step)
      dataPoint[metric.name] = point?.value ?? null
    })
    return dataPoint
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis
              dataKey="step"
              label={{ value: "Step", position: "insideBottom", offset: -5 }}
              className="text-xs"
            />
            <YAxis
              label={{ value: "Value", angle: -90, position: "insideLeft" }}
              className="text-xs"
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: "6px",
              }}
            />
            <Legend />
            {metrics.map(metric => (
              <Line
                key={metric.name}
                type="monotone"
                dataKey={metric.name}
                stroke={metric.color}
                strokeWidth={2}
                dot={{ fill: metric.color, r: 3 }}
                activeDot={{ r: 5 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
