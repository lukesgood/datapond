"use client"

import {
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts"

export type ChartType = "line" | "bar" | "area" | "pie" | "table"

interface ChartRendererProps {
  data: any[]
  chartType: ChartType
  xAxis: string
  yAxis: string
  chartConfig?: {
    colors?: string[]
    showGrid?: boolean
    showLegend?: boolean
  }
}

// Draw from the design-system chart ramp (deep-pond tokens) so query
// visualizations stay cohesive with the rest of the console. The ramp has
// five stops; series beyond that wrap back through it.
const DEFAULT_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
]
const GRID_STROKE = "var(--border)"
const AXIS_STROKE = "var(--muted-foreground)"

export function ChartRenderer({
  data,
  chartType,
  xAxis,
  yAxis,
  chartConfig = {},
}: ChartRendererProps) {
  const { colors = DEFAULT_COLORS, showGrid = true, showLegend = true } = chartConfig

  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[400px] text-muted-foreground">
        No data to visualize
      </div>
    )
  }

  const commonProps = {
    data,
    margin: { top: 10, right: 30, left: 0, bottom: 0 },
  }

  if (chartType === "line") {
    return (
      <ResponsiveContainer width="100%" height={400}>
        <LineChart {...commonProps}>
          {showGrid && <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />}
          <XAxis
            dataKey={xAxis}
            stroke={AXIS_STROKE}
            fontSize={12}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            stroke={AXIS_STROKE}
            fontSize={12}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--popover)",
              border: "1px solid var(--border)",
              color: "var(--popover-foreground)",
              borderRadius: "6px",
              boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)",
            }}
          />
          {showLegend && <Legend />}
          <Line
            type="monotone"
            dataKey={yAxis}
            stroke={colors[0]}
            strokeWidth={2}
            dot={{ fill: colors[0], r: 4 }}
            activeDot={{ r: 6 }}
          />
        </LineChart>
      </ResponsiveContainer>
    )
  }

  if (chartType === "bar") {
    return (
      <ResponsiveContainer width="100%" height={400}>
        <BarChart {...commonProps}>
          {showGrid && <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />}
          <XAxis
            dataKey={xAxis}
            stroke={AXIS_STROKE}
            fontSize={12}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            stroke={AXIS_STROKE}
            fontSize={12}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--popover)",
              border: "1px solid var(--border)",
              color: "var(--popover-foreground)",
              borderRadius: "6px",
              boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)",
            }}
          />
          {showLegend && <Legend />}
          <Bar dataKey={yAxis} fill={colors[0]} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    )
  }

  if (chartType === "area") {
    return (
      <ResponsiveContainer width="100%" height={400}>
        <AreaChart {...commonProps}>
          {showGrid && <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />}
          <XAxis
            dataKey={xAxis}
            stroke={AXIS_STROKE}
            fontSize={12}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            stroke={AXIS_STROKE}
            fontSize={12}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--popover)",
              border: "1px solid var(--border)",
              color: "var(--popover-foreground)",
              borderRadius: "6px",
              boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)",
            }}
          />
          {showLegend && <Legend />}
          <Area
            type="monotone"
            dataKey={yAxis}
            stroke={colors[0]}
            fill={colors[0]}
            fillOpacity={0.2}
          />
        </AreaChart>
      </ResponsiveContainer>
    )
  }

  if (chartType === "pie") {
    return (
      <ResponsiveContainer width="100%" height={400}>
        <PieChart>
          <Pie
            data={data}
            dataKey={yAxis}
            nameKey={xAxis}
            cx="50%"
            cy="50%"
            outerRadius={120}
            label={({ name, percent }) =>
              `${name}: ${percent ? (percent * 100).toFixed(0) : 0}%`
            }
          >
            {data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={colors[index % colors.length]} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--popover)",
              border: "1px solid var(--border)",
              color: "var(--popover-foreground)",
              borderRadius: "6px",
              boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)",
            }}
          />
          {showLegend && <Legend />}
        </PieChart>
      </ResponsiveContainer>
    )
  }

  return null
}
