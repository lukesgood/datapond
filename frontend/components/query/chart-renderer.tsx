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
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts"
import { shapeChart, type Aggregate, type ChartType, type Shaped } from "@/lib/chart-data"
import { resolveYs } from "@/lib/chart-recommend"

export type { ChartType }

interface ChartRendererProps {
  data: Record<string, unknown>[]
  chartType: ChartType
  xAxis: string
  /** One measure; older saved dashboards store only this. */
  yAxis?: string
  /** The measures plotted. Wins over `yAxis` when both are given. */
  yAxes?: string[]
  /** Series per value (line/area/bar), colour (scatter) or second axis (heatmap). */
  colorBy?: string
  stacked?: boolean
  aggregate?: Aggregate
  /** Bars only; left unset, long labels or many categories switch it on. */
  horizontal?: boolean
  chartConfig?: {
    colors?: string[]
    showGrid?: boolean
    showLegend?: boolean
  }
}

// Draw from the design-system chart ramp (deep-pond tokens) so query
// visualizations stay cohesive with the rest of the console. The ramp has
// five stops; more series than that are folded into "Other" before they get here.
// recharts 3.8.1 renders an animated <Bar> or <Pie> as nothing at all — no element
// in the DOM, or one frozen at its first frame, which is what Analytics was showing:
// axes, grid and legend correct, the series absent. Reproduced outside this app, with
// no ResponsiveContainer, no margin, no CSS variables: animation on gives zero bars,
// animation off gives three with the right geometry. Line was hit too: on the live
// Analytics page (2026-09-29) a 111-point daily series showed its dots and no line —
// the stroke frozen at its first frame. So every series renders without animation.
//
// Turning it off is the fix rather than pinning a different recharts, because these
// charts read better without the animation anyway and the dependency scan is a merge
// gate — a version change here is a decision, not a workaround.
const ANIMATE = false
const MAX_DOTS = 40

const DEFAULT_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
]
const GRID_STROKE = "var(--border)"
const AXIS_STROKE = "var(--muted-foreground)"
const TOOLTIP_STYLE = {
  backgroundColor: "var(--popover)",
  border: "1px solid var(--border)",
  color: "var(--popover-foreground)",
  borderRadius: "6px",
  boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)",
}

const axisLabel = (value: string, extra: object = {}) => ({
  value, fill: AXIS_STROKE, fontSize: 12, ...extra,
})

function formatValue(v: number | string | null): string {
  if (typeof v !== "number") return v === null ? "—" : String(v)
  return Math.abs(v) >= 1000 ? v.toLocaleString() : String(Number(v.toPrecision(6)))
}

export function ChartRenderer({
  data,
  chartType,
  xAxis,
  yAxis,
  yAxes,
  colorBy,
  stacked,
  aggregate,
  horizontal,
  chartConfig = {},
}: ChartRendererProps) {
  const { colors = DEFAULT_COLORS, showGrid = true, showLegend = true } = chartConfig
  const ys = resolveYs({ yAxes, yAxis })
  const color = (i: number) => colors[i % colors.length]

  const shaped: Shaped = chartType === "table"
    ? { kind: "empty", reason: "No data to visualize" }
    : shapeChart({ type: chartType, x: xAxis, ys, colorBy, stacked, aggregate, horizontal }, data)

  if (shaped.kind === "empty") {
    return (
      <div className="flex items-center justify-center h-[400px] text-muted-foreground">
        {shaped.reason}
      </div>
    )
  }

  // Room for the axis names below and to the left.
  const margin = { top: 10, right: 30, left: 12, bottom: 24 }
  const grid = showGrid && <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} strokeOpacity={0.6} />

  if (shaped.kind === "kpi") {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" role="group" aria-label="Key figures">
        {shaped.tiles.map(t => (
          <div key={t.name} className="rounded-lg border bg-card p-4">
            <div className="text-3xl font-semibold tabular-nums tracking-tight">{formatValue(t.value)}</div>
            <div className="mt-1 truncate text-xs text-muted-foreground" title={t.name}>{t.name}</div>
          </div>
        ))}
      </div>
    )
  }

  if (shaped.kind === "cartesian") {
    const { type, series, data: rows, xKey, yLabel } = shaped
    const many = series.length >= 2
    const legend = showLegend && many && <Legend verticalAlign="top" height={28} />
    const tooltip = <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => formatValue(v as number)} />
    const stackId = shaped.stacked ? "stack" : undefined
    const barLayout = shaped.horizontal
    const labelWidth = Math.min(
      180, Math.max(60, 7 * Math.max(0, ...rows.map(r => String(r[xKey] ?? "").length))))
    const height = barLayout ? Math.max(400, rows.length * 26 + 60) : 400

    const xAxisEl = barLayout ? (
      <XAxis type="number" stroke={AXIS_STROKE} fontSize={12} tickLine={false} axisLine={false}
             label={yLabel ? axisLabel(yLabel, { position: "insideBottom", offset: -16 }) : undefined} />
    ) : (
      <XAxis dataKey={xKey} stroke={AXIS_STROKE} fontSize={12} tickLine={false} axisLine={false}
             label={axisLabel(xKey, { position: "insideBottom", offset: -16 })} />
    )
    const yAxisEl = barLayout ? (
      <YAxis type="category" dataKey={xKey} width={labelWidth} stroke={AXIS_STROKE} fontSize={12}
             tickLine={false} axisLine={false} interval={0} />
    ) : (
      <YAxis stroke={AXIS_STROKE} fontSize={12} tickLine={false} axisLine={false}
             label={yLabel ? axisLabel(yLabel, { angle: -90, position: "insideLeft", style: { textAnchor: "middle" } }) : undefined} />
    )

    return (
      <ResponsiveContainer width="100%" height={height}>
        {type === "line" ? (
          <LineChart data={rows} margin={margin}>
            {grid}{xAxisEl}{yAxisEl}{tooltip}{legend}
            {series.map((s, i) => (
              <Line
                key={s}
                type="monotone"
                dataKey={s}
                stroke={color(i)}
                strokeWidth={2}
                // Markers on every point bury a long series; past a few dozen points the
                // line carries the shape and the hover dot marks the value.
                dot={rows.length <= MAX_DOTS ? { fill: color(i), r: 3 } : false}
                activeDot={{ r: 5 }}
                isAnimationActive={ANIMATE}
              />
            ))}
          </LineChart>
        ) : type === "area" ? (
          <AreaChart data={rows} margin={margin}>
            {grid}{xAxisEl}{yAxisEl}{tooltip}{legend}
            {series.map((s, i) => (
              <Area
                key={s}
                type="monotone"
                dataKey={s}
                stackId={stackId}
                stroke={color(i)}
                strokeWidth={2}
                fill={color(i)}
                fillOpacity={stackId ? 0.55 : 0.2}
                isAnimationActive={ANIMATE}
              />
            ))}
          </AreaChart>
        ) : (
          <BarChart data={rows} margin={barLayout ? { ...margin, left: 4 } : margin}
                    layout={barLayout ? "vertical" : "horizontal"} barCategoryGap="20%">
            {grid}{xAxisEl}{yAxisEl}{tooltip}{legend}
            {series.map((s, i) => (
              <Bar
                key={s}
                dataKey={s}
                stackId={stackId}
                fill={color(i)}
                radius={stackId ? 0 : barLayout ? [0, 3, 3, 0] : [3, 3, 0, 0]}
                isAnimationActive={ANIMATE}
              />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    )
  }

  if (shaped.kind === "scatter") {
    const { groups, xKey, yKey } = shaped
    return (
      <ResponsiveContainer width="100%" height={400}>
        <ScatterChart margin={margin}>
          {grid}
          <XAxis type="number" dataKey="x" name={xKey} stroke={AXIS_STROKE} fontSize={12}
                 tickLine={false} axisLine={false} domain={["auto", "auto"]}
                 label={axisLabel(xKey, { position: "insideBottom", offset: -16 })} />
          <YAxis type="number" dataKey="y" name={yKey} stroke={AXIS_STROKE} fontSize={12}
                 tickLine={false} axisLine={false} domain={["auto", "auto"]}
                 label={axisLabel(yKey, { angle: -90, position: "insideLeft", style: { textAnchor: "middle" } })} />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ strokeDasharray: "3 3" }} />
          {showLegend && groups.length >= 2 && <Legend verticalAlign="top" height={28} />}
          {groups.map((g, i) => (
            <Scatter key={g.name || "points"} name={g.name || yKey} data={g.points}
                     fill={color(i)} fillOpacity={0.7} isAnimationActive={ANIMATE} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    )
  }

  if (shaped.kind === "histogram") {
    const { bins, column } = shaped
    return (
      <ResponsiveContainer width="100%" height={400}>
        <BarChart data={bins} margin={margin} barCategoryGap={1}>
          {grid}
          <XAxis dataKey="label" stroke={AXIS_STROKE} fontSize={11} tickLine={false} axisLine={false}
                 interval="preserveStartEnd" minTickGap={24}
                 label={axisLabel(column, { position: "insideBottom", offset: -16 })} />
          <YAxis stroke={AXIS_STROKE} fontSize={12} tickLine={false} axisLine={false} allowDecimals={false}
                 label={axisLabel("rows", { angle: -90, position: "insideLeft", style: { textAnchor: "middle" } })} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Bar dataKey="count" name="rows" fill={color(0)} radius={[2, 2, 0, 0]} isAnimationActive={ANIMATE} />
        </BarChart>
      </ResponsiveContainer>
    )
  }

  if (shaped.kind === "heatmap") {
    return <Heatmap shaped={shaped} />
  }

  // pie
  const pieData = shaped.data
  return (
    <ResponsiveContainer width="100%" height={400}>
      <PieChart>
        <Pie
          data={pieData}
          dataKey={shaped.yKey}
          nameKey={shaped.xKey}
          cx="50%"
          cy="50%"
          outerRadius={120}
          isAnimationActive={ANIMATE}
          label={({ name, percent }) =>
            `${name}: ${percent ? (percent * 100).toFixed(0) : 0}%`
          }
        >
          {pieData.map((_, index) => (
            <Cell key={`cell-${index}`} fill={color(index)} />
          ))}
        </Pie>
        <Tooltip contentStyle={TOOLTIP_STYLE} />
        {showLegend && <Legend verticalAlign="top" height={28} />}
      </PieChart>
    </ResponsiveContainer>
  )
}

/** Two categories and a measure as a grid of cells: one hue, light to dark, so the
 *  eye reads magnitude and nothing else. A plain grid rather than a library — it is
 *  a table with a background. */
function Heatmap({ shaped }: { shaped: Extract<Shaped, { kind: "heatmap" }> }) {
  const { xs, ys, cells, min, max, valueLabel, xKey, yKey } = shaped
  const span = max - min
  const showNumbers = xs.length <= 10 && ys.length <= 16
  return (
    <div className="overflow-auto" role="img"
         aria-label={`Heatmap of ${valueLabel} by ${xKey} and ${yKey}`}>
      <div className="inline-grid gap-px text-2xs"
           style={{ gridTemplateColumns: `minmax(72px, auto) repeat(${xs.length}, minmax(28px, 1fr))` }}>
        <div className="p-1 text-muted-foreground">{yKey} \ {xKey}</div>
        {xs.map(x => (
          <div key={x} className="truncate p-1 text-center text-muted-foreground" title={x}>{x}</div>
        ))}
        {ys.map((y, r) => (
          <div key={y} className="contents">
            <div className="truncate p-1 pr-2 text-right text-muted-foreground" title={y}>{y}</div>
            {xs.map((x, c) => {
              const v = cells[r][c]
              const t = v === null ? 0 : span === 0 ? 0.6 : (v - min) / span
              return (
                <div
                  key={x}
                  title={`${yKey}: ${y} · ${xKey}: ${x} · ${valueLabel}: ${v === null ? "no data" : formatValue(v)}`}
                  className="flex h-8 items-center justify-center tabular-nums"
                  style={{
                    background: v === null
                      ? "var(--muted)"
                      : `color-mix(in oklab, var(--chart-1) ${Math.round(12 + t * 88)}%, var(--card))`,
                    color: t > 0.55 ? "#fff" : "var(--foreground)",
                  }}
                >
                  {showNumbers && v !== null ? formatValue(v) : ""}
                </div>
              )
            })}
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-2 text-2xs text-muted-foreground">
        <span className="tabular-nums">{formatValue(min)}</span>
        <span className="h-2 w-24 rounded-sm"
              style={{ background: "linear-gradient(to right, color-mix(in oklab, var(--chart-1) 12%, var(--card)), var(--chart-1))" }} />
        <span className="tabular-nums">{formatValue(max)}</span>
        <span>{valueLabel}</span>
      </div>
    </div>
  )
}
