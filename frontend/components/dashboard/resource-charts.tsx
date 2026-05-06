"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts"

interface ResourceChartsProps {
  className?: string
}

// Generate 24 hours of mock resource usage data
const generateResourceData = () => {
  return Array.from({ length: 24 }, (_, i) => {
    const hour = i
    // Create realistic patterns: higher during work hours (9-17), lower at night
    const timeMultiplier = hour >= 9 && hour <= 17 ? 1.3 : 0.8

    const baseCpu = 30 + Math.sin(hour / 4) * 15
    const baseMemory = 55 + Math.cos(hour / 3) * 12

    return {
      time: `${hour.toString().padStart(2, "0")}:00`,
      cpu: Number((baseCpu * timeMultiplier + (Math.random() - 0.5) * 8).toFixed(1)),
      memory: Number((baseMemory * timeMultiplier + (Math.random() - 0.5) * 6).toFixed(1))
    }
  })
}

export function ResourceCharts({ className }: ResourceChartsProps) {
  const data = generateResourceData()

  const avgCpu = (data.reduce((sum, d) => sum + d.cpu, 0) / data.length).toFixed(1)
  const avgMemory = (data.reduce((sum, d) => sum + d.memory, 0) / data.length).toFixed(1)

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Resource Usage</CardTitle>
            <CardDescription>
              CPU and memory consumption over 24 hours
            </CardDescription>
          </div>
          <div className="grid grid-cols-2 gap-6 text-right text-xs">
            <div>
              <div className="font-bold text-base">{avgCpu}%</div>
              <p className="text-muted-foreground">Avg CPU</p>
            </div>
            <div>
              <div className="font-bold text-base">{avgMemory}%</div>
              <p className="text-muted-foreground">Avg Memory</p>
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart
            data={data}
            margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
            <XAxis
              dataKey="time"
              stroke="hsl(var(--muted-foreground))"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              interval={3}
            />
            <YAxis
              domain={[0, 100]}
              stroke="hsl(var(--muted-foreground))"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => `${value}%`}
            />
            <Tooltip />
            <Legend iconType="line" />
            <Line
              type="monotone"
              dataKey="cpu"
              stroke="hsl(var(--primary))"
              strokeWidth={2}
              dot={false}
              name="CPU"
            />
            <Line
              type="monotone"
              dataKey="memory"
              stroke="hsl(var(--chart-3))"
              strokeWidth={2}
              dot={false}
              name="Memory"
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
