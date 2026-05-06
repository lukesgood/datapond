"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts"
import { format, subDays } from "date-fns"

interface ServiceHealthChartProps {
  className?: string
}

// Generate 7 days of mock service health data
const generateHealthData = () => {
  return Array.from({ length: 7 }, (_, i) => {
    const date = subDays(new Date(), 6 - i)
    // Base uptime around 98-100%
    const baseUptime = 97 + Math.random() * 3
    // Occasional dips
    const uptime = i === 2 ? 95.5 : i === 4 ? 96.8 : baseUptime

    return {
      date: format(date, "MMM dd"),
      uptime: Number(uptime.toFixed(1)),
      incidents: i === 2 || i === 4 ? 1 : 0
    }
  })
}

export function ServiceHealthChart({ className }: ServiceHealthChartProps) {
  const data = generateHealthData()
  const avgUptime = (data.reduce((sum, d) => sum + d.uptime, 0) / data.length).toFixed(2)

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Service Health</CardTitle>
            <CardDescription>
              Platform uptime over the last 7 days
            </CardDescription>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold">{avgUptime}%</div>
            <p className="text-xs text-muted-foreground">Average uptime</p>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart
            data={data}
            margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
            <XAxis
              dataKey="date"
              stroke="hsl(var(--muted-foreground))"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              domain={[90, 100]}
              stroke="hsl(var(--muted-foreground))"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => `${value}%`}
            />
            <Tooltip />
            <Area
              type="monotone"
              dataKey="uptime"
              stroke="hsl(var(--primary))"
              fill="hsl(var(--primary))"
              fillOpacity={0.2}
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
