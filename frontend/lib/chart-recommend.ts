/** Which charts a query result can honestly be drawn as, and which one fits it best.
 *
 *  The form follows the data's job: one row is KPI tiles, a measure over time is a
 *  line, a measure per category is a bar, two measures are a scatter, one measure over
 *  many rows is a histogram, two categories and a measure are a heatmap, a small whole
 *  may be a pie, and anything else — no measure, free text — stays a table. Types that
 *  do not fit are not hidden; they are disabled with a sentence saying why, so the
 *  picker teaches instead of failing silently.
 *
 *  Column kinds come from the engine (QueryResult.column_types). When a result has
 *  none, roles are read from the values.
 */
import {
  AGGREGATE_VERB, MAX_BARS, MAX_HEATMAP, MAX_KPI, MAX_SCATTER_GROUPS,
  MAX_SERIES, MAX_SLICES, MIN_HISTOGRAM_ROWS, asNumber, ISO_DATE, sturgesBins,
  type Aggregate, type ChartType,
} from "./chart-data.ts"

export type { ChartType, Aggregate }

export type ColumnRole = "time" | "measure" | "category" | "identifier" | "other"

export interface ColumnProfile {
  name: string
  role: ColumnRole
  distinct: number
  nonNull: number
  hasNegative: boolean
  repeats: boolean
}

export interface Availability {
  ok: boolean
  reason?: string
  note?: string
}

export interface Recommendation {
  best: ChartType
  x: string
  /** First of `ys`, kept for callers that plot one measure. */
  y: string
  /** The measures plotted (one when the series come from `colorBy`). */
  ys: string[]
  /** The category that splits or colours the chart, "" for none. */
  colorBy: string
  aggregate: Aggregate
  /** Stacking as it will be drawn: what was asked, if it fits. */
  stacked: boolean
  stackedFit: Availability
  /** Whether repeated X values are combined, so the aggregation choice matters. */
  aggregates: boolean
  /** Columns a KPI shows; empty when the result is not a KPI. */
  kpiColumns: string[]
  availability: Record<ChartType, Availability>
  /** The axes to apply when a type is picked: the current ones if they fit, otherwise
   *  the columns that would (a scatter needs two measures, a heatmap two categories),
   *  so those types are reachable from a chart on other axes. */
  axesFor: Record<ChartType, ChartAxes>
  xOptions: string[]
  yOptions: string[]
  colorOptions: string[]
}

export interface ChartAxes { x: string; ys: string[]; colorBy: string }

/** What the person chose in the panel. `colorBy` null/undefined leaves it automatic,
 *  "" turns it off. */
export interface ChartChoice {
  x?: string
  y?: string
  ys?: string[]
  colorBy?: string | null
  aggregate?: Aggregate
  stacked?: boolean
}

/** The measures a saved dashboard plots; a config with only `yAxis` is an older one. */
export function resolveYs(cfg: { yAxes?: string[] | null; yAxis?: string | null }): string[] {
  if (cfg.yAxes && cfg.yAxes.length > 0) return cfg.yAxes
  return cfg.yAxis ? [cfg.yAxis] : []
}

const ID_NAME = /(^id$|_id$|^id_|uuid)/i

function mostly(values: unknown[], test: (v: unknown) => boolean): boolean {
  if (values.length === 0) return false
  return values.filter(test).length / values.length >= 0.9
}

export function profileColumns(columns: string[], rows: unknown[][],
                               kinds?: string[]): ColumnProfile[] {
  return columns.map((name, i) => {
    const values = rows.map(r => r[i]).filter(v => v !== null && v !== undefined && v !== "")
    const distinct = new Set(values.map(v => String(v))).size
    const numbers = values.map(asNumber).filter((n): n is number => n !== null)
    let kind = kinds?.[i] ?? "unknown"
    if (kind === "unknown") {
      if (mostly(values, v => asNumber(v) !== null)) kind = "quantitative"
      else if (mostly(values, v => typeof v === "string" && ISO_DATE.test(v))) kind = "temporal"
      else if (mostly(values, v => typeof v === "boolean")) kind = "boolean"
      else kind = "text"
    }

    let role: ColumnRole
    if (kind === "quantitative") {
      role = ID_NAME.test(name) ? "identifier" : "measure"
    } else if (kind === "temporal") {
      role = "time"
    } else if (kind === "boolean") {
      role = "category"
    } else if (kind === "text") {
      // Not "unique per row means identifier": an aggregated result (GROUP BY region)
      // has one row per category by construction. Too many categories is the bar
      // chart's call to make, with the count in the reason.
      role = ID_NAME.test(name) ? "identifier" : "category"
    } else {
      role = "other"
    }
    return {
      name, role, distinct, nonNull: values.length,
      hasNegative: numbers.some(n => n < 0),
      repeats: distinct < values.length,
    }
  })
}

const ONE_ROW = "One row — a chart of a single point says nothing the table does not. KPI tiles or the table fit it."
const NO_MEASURE = "Needs a numeric column to plot; this result has none."

interface AssessContext {
  /** The category that splits or colours the chart, or a heatmap's second axis. */
  colorBy?: ColumnProfile
  /** Every measure in the result (what a KPI would show). */
  measures?: ColumnProfile[]
  aggregate?: Aggregate
}

const CELL_VERB: Record<Aggregate, string> = {
  sum: "sum", avg: "average", count: "count", min: "minimum", max: "maximum",
}

/** Whether `type` fits these axes. `y` is one measure, or the list plotted. */
export function assess(type: ChartType, x: ColumnProfile | undefined,
                       y: ColumnProfile | ColumnProfile[] | undefined, rowCount: number,
                       ctx: AssessContext = {}): Availability {
  if (type === "table") return { ok: true }
  if (rowCount === 0) return { ok: false, reason: "No rows to plot." }
  const ys = Array.isArray(y) ? y : y ? [y] : []
  const agg = ctx.aggregate ?? "sum"

  if (type === "kpi") {
    const measures = ctx.measures ?? ys.filter(p => p.role === "measure")
    if (rowCount !== 1) {
      return { ok: false, reason: `KPI tiles show one row; this result has ${rowCount}. Aggregate it to a single row first.` }
    }
    if (measures.length === 0) return { ok: false, reason: NO_MEASURE }
    if (measures.length > MAX_KPI) {
      return { ok: false, reason: `KPI shows up to ${MAX_KPI} numbers; this row has ${measures.length}. SELECT fewer columns.` }
    }
    return { ok: true }
  }
  if (rowCount === 1) return { ok: false, reason: ONE_ROW }

  const bad = ys.find(p => p.role !== "measure")
  if (ys.length === 0 || bad) {
    return { ok: false, reason: bad ? `Y (${bad.name}) is not numeric. Pick a numeric column.` : NO_MEASURE }
  }

  if (type === "histogram") {
    if (rowCount < MIN_HISTOGRAM_ROWS) {
      return { ok: false, reason: `A histogram needs at least ${MIN_HISTOGRAM_ROWS} values to bin; this has ${rowCount}.` }
    }
    return { ok: true, note: `${rowCount} values of ${ys[0].name} in ${sturgesBins(rowCount)} equal-width bins.` }
  }

  if (type === "scatter") {
    if (!x || x.role !== "measure") {
      return { ok: false, reason: `Scatter needs a number on X${x ? `; ${x.name} is ${x.role === "time" ? "a date" : "not numeric"}` : ""}. Pick a numeric X.` }
    }
    if (x.name === ys[0].name) {
      return { ok: false, reason: "Scatter compares two different numeric columns. Pick another for Y, or use Histogram." }
    }
    const cb = ctx.colorBy
    if (cb && cb.distinct > MAX_SCATTER_GROUPS) {
      return { ok: true, note: `Colour by ${cb.name} is off: it has ${cb.distinct} values and only ${MAX_SCATTER_GROUPS} stay distinguishable.` }
    }
    return { ok: true }
  }

  if (!x) return { ok: false, reason: "Pick an X column." }
  if (x.role === "identifier") {
    return { ok: false, reason: `X (${x.name}) is a unique label per row, not something to group by.` }
  }
  if (x.role === "other") return { ok: false, reason: `X (${x.name}) cannot be placed on an axis.` }

  if (type === "heatmap") {
    const cb = ctx.colorBy
    if (x.role !== "category") {
      return { ok: false, reason: `Heatmap needs categories on both axes; ${x.name} is ${x.role === "time" ? "a date" : "a number"}.` }
    }
    if (!cb) return { ok: false, reason: "Heatmap needs a second category column for the other axis. Pick one under Series by." }
    if (x.distinct > MAX_HEATMAP || cb.distinct > MAX_HEATMAP) {
      return { ok: false, reason: `Heatmap reads up to ${MAX_HEATMAP} × ${MAX_HEATMAP} cells; ${x.name} has ${x.distinct} and ${cb.name} has ${cb.distinct}. Aggregate or LIMIT first.` }
    }
    return { ok: true, note: `Each cell is the ${CELL_VERB[agg]} of ${ys[0].name} for that pair.` }
  }

  if (type === "pie") {
    if (x.role !== "category") {
      return { ok: false, reason: `Pie needs categories on X; ${x.name} is ${x.role === "time" ? "a date" : "a number"}.` }
    }
    if (x.distinct > MAX_SLICES) {
      return { ok: false, reason: `Pie reads only up to ${MAX_SLICES} slices; ${x.name} has ${x.distinct}. Use Bar.` }
    }
    if (ys[0].hasNegative) return { ok: false, reason: `Pie cannot show negative values in ${ys[0].name}.` }
    if (x.repeats) return { ok: false, reason: `Each slice must appear once; aggregate with GROUP BY ${x.name}.` }
    return { ok: true }
  }

  // line | area | bar
  const cb = ctx.colorBy
  if (ys.length > MAX_SERIES) {
    return { ok: false, reason: `Up to ${MAX_SERIES} series are readable; ${ys.length} measures are selected. Deselect some.` }
  }
  let note: string | undefined
  if (cb && cb.distinct > MAX_SERIES) {
    note = `${cb.name} has ${cb.distinct} values: the top ${MAX_SERIES - 1} are drawn and the rest are combined as "Other".`
  } else if (x.repeats && !cb) {
    note = `X (${x.name}) repeats, so rows with the same ${x.name} are ${AGGREGATE_VERB[agg]}. Change it under Aggregation.`
  }
  if (type === "line" || type === "area") {
    if (x.role !== "time" && x.role !== "measure") {
      return { ok: false, reason: `${type === "line" ? "Line" : "Area"} needs a date or number on X; ${x.name} is a category — use Bar.` }
    }
    return { ok: true, note }
  }
  if (x.distinct > MAX_BARS) {
    return { ok: false, reason: `X (${x.name}) has ${x.distinct} distinct values — too many bars to read. Aggregate or LIMIT to the top ${MAX_BARS}.` }
  }
  return { ok: true, note }
}

const TYPES: ChartType[] = [
  "table", "line", "bar", "area", "pie", "kpi", "scatter", "histogram", "heatmap",
]

/** Whether the series can be stacked into a whole. */
export function assessStacked(seriesCount: number, ys: ColumnProfile[]): Availability {
  if (seriesCount < 2) {
    return { ok: false, reason: "Stacking needs two or more series: select several Y columns or split by a category." }
  }
  const neg = ys.find(p => p.hasNegative)
  if (neg) return { ok: false, reason: `Stacked parts cannot be negative; ${neg.name} has negative values.` }
  return { ok: true }
}

/** The best chart for this result and the axes it would use. What the person chose
 *  overrides the defaults, and availability is judged on those. */
export function recommend(profiles: ColumnProfile[], rowCount: number,
                          chosen: ChartChoice = {}): Recommendation {
  const byName = new Map(profiles.map(p => [p.name, p]))
  const measures = profiles.filter(p => p.role === "measure")
  const times = profiles.filter(p => p.role === "time")
  const categories = profiles.filter(p => p.role === "category")

  const defaultX = (times[0] ?? categories[0] ?? profiles.find(p => p.role !== "identifier") ?? profiles[0])?.name ?? ""
  const defaultY = (measures.find(p => p.name !== defaultX) ?? measures[0])?.name ?? ""
  const x = chosen.x && byName.has(chosen.x) ? chosen.x : defaultX
  const xp = byName.get(x)

  const picked = (chosen.ys && chosen.ys.length > 0 ? chosen.ys : chosen.y ? [chosen.y] : [])
    .filter((n, i, all) => byName.has(n) && all.indexOf(n) === i)
  let ys = picked.length > 0 ? picked : defaultY ? [defaultY] : []

  // One measure split by a category, or several measures, never both.
  const others = categories.filter(c => c.name !== x && !ys.includes(c.name))
  let colorBy = ""
  if (chosen.colorBy === "") colorBy = ""
  else if (chosen.colorBy && others.some(c => c.name === chosen.colorBy)) colorBy = chosen.colorBy
  else if (ys.length === 1 && xp) {
    if ((xp.role === "time" || xp.role === "category") && xp.repeats) {
      colorBy = others.find(c => c.distinct >= 2 && c.distinct <= MAX_HEATMAP)?.name ?? ""
    } else if (xp.role === "measure") {
      colorBy = others.find(c => c.distinct >= 2 && c.distinct <= MAX_SCATTER_GROUPS)?.name ?? ""
    }
  }
  const cbp = colorBy ? byName.get(colorBy) : undefined
  if (cbp && ys.length > 1) ys = [ys[0]]

  const aggregate = chosen.aggregate ?? "sum"
  const ysp = ys.map(n => byName.get(n)).filter((p): p is ColumnProfile => !!p)
  const ctx = { colorBy: cbp, measures, aggregate }
  const current: ChartAxes = { x, ys, colorBy }
  const judge = (t: ChartType, a: ChartAxes): Availability => {
    const cb = a.colorBy ? byName.get(a.colorBy) : undefined
    const yp = a.ys.map(n => byName.get(n)).filter((p): p is ColumnProfile => !!p)
    return assess(t, byName.get(a.x), yp.length ? yp : undefined, rowCount, { ...ctx, colorBy: cb })
  }
  // The columns a type wants, when the current axes are not it.
  const suggest = (t: ChartType): ChartAxes | null => {
    if (t === "scatter" && measures.length >= 2) {
      const sx = xp?.role === "measure" ? x : measures[0].name
      const sy = ys.find(n => n !== sx && byName.get(n)?.role === "measure")
        ?? measures.find(m => m.name !== sx)!.name
      const cb = categories.find(c => c.distinct >= 2 && c.distinct <= MAX_SCATTER_GROUPS)
      return { x: sx, ys: [sy], colorBy: cb?.name ?? "" }
    }
    if (t === "histogram" && measures.length >= 1) {
      const sy = ys.find(n => byName.get(n)?.role === "measure") ?? measures[0].name
      return { x, ys: [sy], colorBy: "" }
    }
    if (t === "heatmap" && categories.length >= 2 && measures.length >= 1) {
      const sx = xp?.role === "category" ? x : categories[0].name
      const cb = (colorBy && colorBy !== sx ? byName.get(colorBy) : undefined)
        ?? categories.find(c => c.name !== sx)!
      const sy = ys.find(n => byName.get(n)?.role === "measure") ?? measures[0].name
      return { x: sx, ys: [sy], colorBy: cb.name }
    }
    return null
  }
  const availability = {} as Record<ChartType, Availability>
  const axesFor = {} as Record<ChartType, ChartAxes>
  for (const t of TYPES) {
    let fit = judge(t, current)
    let axes = current
    if (!fit.ok) {
      const alt = suggest(t)
      if (alt) {
        const altFit = judge(t, alt)
        // Whether or not it fits, the suggestion's reason names the real obstacle.
        fit = altFit
        if (altFit.ok) axes = alt
      }
    }
    availability[t] = fit
    axesFor[t] = axes
  }

  const seriesCount = cbp ? Math.min(cbp.distinct, MAX_SERIES) : ys.length
  const stackedFit = assessStacked(seriesCount, ysp)

  let best: ChartType = "table"
  if (availability.kpi.ok) best = "kpi"
  else if (rowCount >= 2 && xp) {
    if (xp.role === "time" && availability.line.ok) best = "line"
    else if (xp.role === "category") {
      if (cbp && cbp.distinct > MAX_SERIES && availability.heatmap.ok) best = "heatmap"
      else if (availability.bar.ok) best = "bar"
      else if (availability.heatmap.ok) best = "heatmap"
    } else if (xp.role === "measure") {
      if (ys[0] && ys[0] !== x && availability.scatter.ok) best = "scatter"
      else if (measures.length === 1 && availability.histogram.ok) best = "histogram"
    }
  }

  return {
    best, x, y: ys[0] ?? "", ys, colorBy, aggregate,
    stacked: !!chosen.stacked && stackedFit.ok, stackedFit,
    aggregates: !!xp?.repeats,
    kpiColumns: availability.kpi.ok ? measures.map(p => p.name) : [],
    availability, axesFor,
    xOptions: profiles.filter(p => p.role === "time" || p.role === "category" || p.role === "measure").map(p => p.name),
    yOptions: measures.map(p => p.name),
    colorOptions: categories.filter(c => c.name !== x).map(c => c.name),
  }
}

/** The chart as a dashboard stores it and the renderer draws it — one shape, so what
 *  is saved is what was on screen. */
export function chartSpecFor(type: ChartType, rec: Recommendation) {
  const ys = type === "kpi" ? rec.kpiColumns : rec.ys
  const drawsSeries = type === "bar" || type === "area"
  return {
    chartType: type,
    xAxis: rec.x,
    yAxis: ys[0] ?? "",
    yAxes: ys,
    colorBy: rec.colorBy || undefined,
    stacked: drawsSeries && rec.stacked ? true : undefined,
    aggregate: rec.aggregate,
  }
}

/** Row objects for the renderer, with a measure's numeric strings made numbers —
 *  Athena returns decimals as strings, which Recharts would not plot. */
export function toChartRows(columns: string[], rows: unknown[][],
                            profiles: ColumnProfile[]): Record<string, unknown>[] {
  const measure = new Set(profiles.filter(p => p.role === "measure").map(p => p.name))
  return rows.map(row => {
    const obj: Record<string, unknown> = {}
    columns.forEach((col, i) => {
      const v = row[i]
      obj[col] = measure.has(col) ? (asNumber(v) ?? v) : v
    })
    return obj
  })
}
