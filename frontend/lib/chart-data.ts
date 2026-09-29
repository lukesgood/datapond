/** Turning result rows into what each chart form draws.
 *
 *  Pure and framework-free: the renderer only lays out what `shapeChart` returns, and
 *  the rules that decide which form fits live in ./chart-recommend.ts. Everything a
 *  chart does to the rows — combine repeated X values, split one measure into a series
 *  per category, fold a long tail into "Other", bin a measure, lay out a matrix — is
 *  here so it can be tested without a browser.
 */

export type ChartType =
  | "table" | "line" | "bar" | "area" | "pie"
  | "kpi" | "scatter" | "histogram" | "heatmap"

export type Aggregate = "sum" | "avg" | "count" | "min" | "max"
export const AGGREGATES: Aggregate[] = ["sum", "avg", "count", "min", "max"]
export const AGGREGATE_LABEL: Record<Aggregate, string> = {
  sum: "Sum", avg: "Average", count: "Count", min: "Minimum", max: "Maximum",
}
/** How each aggregation reads in a sentence ("combined by summing"). */
export const AGGREGATE_VERB: Record<Aggregate, string> = {
  sum: "summed", avg: "averaged", count: "counted", min: "reduced to their minimum",
  max: "reduced to their maximum",
}

// More bars than this cannot be read, and are usually an un-aggregated result.
export const MAX_BARS = 50
// A pie compares shares by angle; past a handful of slices nobody can.
export const MAX_SLICES = 5
// Five categorical hues are distinguishable; beyond that the tail is folded.
export const MAX_SERIES = 5
export const MAX_KPI = 4
export const MAX_SCATTER_GROUPS = 3
export const MAX_HEATMAP = 30
export const MIN_HISTOGRAM_ROWS = 20
const MAX_BINS = 20
const MIN_BINS = 5
// Category labels longer than this, or more categories than this, read better as
// horizontal bars than as slanted tick text.
export const LONG_LABEL = 12
export const MANY_CATEGORIES = 12
export const OTHER = "Other"

export const ISO_DATE = /^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?(Z|[+-]\d{2}:?\d{2})?$/

export function asNumber(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v)
  return null
}

type Row = Record<string, unknown>
export type XKind = "time" | "measure" | "category"

/** What an X column holds, read from its values (a saved dashboard has no profile). */
export function xKindOf(values: unknown[]): XKind {
  const present = values.filter(v => v !== null && v !== undefined && v !== "")
  if (present.length === 0) return "category"
  const share = (test: (v: unknown) => boolean) => present.filter(test).length / present.length
  if (share(v => typeof v === "string" && ISO_DATE.test(v)) >= 0.9) return "time"
  if (share(v => typeof v === "number") >= 0.9) return "measure"
  return "category"
}

export function sturgesBins(n: number): number {
  if (n < 2) return 1
  return Math.min(MAX_BINS, Math.max(MIN_BINS, Math.ceil(Math.log2(n)) + 1))
}

function reduceValues(agg: Aggregate, vals: number[]): number | null {
  if (agg === "count") return vals.length
  if (vals.length === 0) return null
  switch (agg) {
    case "sum": return vals.reduce((a, b) => a + b, 0)
    case "avg": return vals.reduce((a, b) => a + b, 0) / vals.length
    case "min": return Math.min(...vals)
    case "max": return Math.max(...vals)
  }
}

interface Group { key: string; raw: unknown; rows: Row[] }

function groupBy(rows: Row[], field: string): Group[] {
  const groups = new Map<string, Group>()
  for (const row of rows) {
    const key = String(row[field] ?? "")
    let g = groups.get(key)
    if (!g) { g = { key, raw: row[field], rows: [] }; groups.set(key, g) }
    g.rows.push(row)
  }
  return [...groups.values()]
}

function numbersOf(rows: Row[], field: string): number[] {
  return rows.map(r => asNumber(r[field])).filter((n): n is number => n !== null)
}

export interface Bin { label: string; from: number; to: number; count: number }

/** Equal-width bins over the values, Sturges' count unless one is given. The last bin
 *  includes the maximum. */
export function histogramBins(values: number[], count?: number): Bin[] {
  if (values.length === 0) return []
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  if (lo === hi) return [{ label: fmt(lo), from: lo, to: hi, count: values.length }]
  const k = count ?? sturgesBins(values.length)
  const width = (hi - lo) / k
  const bins: Bin[] = Array.from({ length: k }, (_, i) => {
    const from = lo + i * width
    const to = i === k - 1 ? hi : lo + (i + 1) * width
    return { label: `${fmt(from)}–${fmt(to)}`, from, to, count: 0 }
  })
  for (const v of values) {
    const idx = Math.min(k - 1, Math.floor((v - lo) / width))
    bins[idx].count += 1
  }
  return bins
}

function fmt(n: number): string {
  if (Number.isInteger(n)) return String(n)
  return Math.abs(n) >= 100 ? n.toFixed(0) : Math.abs(n) >= 1 ? n.toFixed(1) : n.toPrecision(2)
}

export interface ChartSpec {
  type: ChartType
  x: string
  ys: string[]
  /** A category column: one series per value (long format), a scatter's colour, or a
   *  heatmap's second axis. */
  colorBy?: string
  stacked?: boolean
  aggregate?: Aggregate
  /** Bars only. Left undefined, long labels or many categories decide. */
  horizontal?: boolean
  xKind?: XKind
}

export type Shaped =
  | { kind: "empty"; reason: string }
  | { kind: "kpi"; tiles: { name: string; value: number | string | null }[] }
  | {
      kind: "cartesian"; type: "line" | "area" | "bar"; xKey: string; data: Row[]
      series: string[]; stacked: boolean; horizontal: boolean; yLabel: string
    }
  | {
      kind: "scatter"; xKey: string; yKey: string
      groups: { name: string; points: { x: number; y: number }[] }[]
    }
  | { kind: "histogram"; column: string; bins: Bin[] }
  | {
      kind: "heatmap"; xKey: string; yKey: string; valueLabel: string
      xs: string[]; ys: string[]; cells: (number | null)[][]; min: number; max: number
    }
  | { kind: "pie"; data: Row[]; xKey: string; yKey: string }

/** Rows of one measure per (x, category) pair, with the categories beyond the palette
 *  folded into "Other" so the chart never needs a sixth hue. */
export function foldCategories(rows: Row[], colorBy: string, y: string,
                               max = MAX_SERIES): { rows: Row[]; categories: string[] } {
  const groups = groupBy(rows, colorBy)
  const total = (g: Group) => numbersOf(g.rows, y).reduce((a, b) => a + Math.abs(b), 0)
  const ranked = [...groups].sort((a, b) => total(b) - total(a))
  if (ranked.length <= max) {
    return { rows, categories: ranked.map(g => g.key) }
  }
  const keep = new Set(ranked.slice(0, max - 1).map(g => g.key))
  return {
    rows: rows.map(r => keep.has(String(r[colorBy] ?? "")) ? r : { ...r, [colorBy]: OTHER }),
    categories: [...ranked.slice(0, max - 1).map(g => g.key), OTHER],
  }
}

export function shapeChart(spec: ChartSpec, data: Row[]): Shaped {
  if (!data || data.length === 0) return { kind: "empty", reason: "No data to visualize" }
  const agg = spec.aggregate ?? "sum"
  const { type, x } = spec

  if (type === "kpi") {
    const names = spec.ys.length > 0 ? spec.ys
      : Object.keys(data[0]).filter(k => asNumber(data[0][k]) !== null)
    return {
      kind: "kpi",
      tiles: names.slice(0, MAX_KPI).map(name => ({
        name, value: asNumber(data[0][name]) ?? (data[0][name] as string | null) ?? null,
      })),
    }
  }

  const y = spec.ys[0]
  if (type === "histogram") {
    if (!y) return { kind: "empty", reason: "Pick a numeric column." }
    return { kind: "histogram", column: y, bins: histogramBins(numbersOf(data, y)) }
  }

  if (type === "scatter") {
    if (!y) return { kind: "empty", reason: "Pick a numeric column for Y." }
    const cb = spec.colorBy
    const names = cb ? [...new Set(data.map(r => String(r[cb] ?? "")))] : []
    const colour = cb !== undefined && names.length >= 2 && names.length <= MAX_SCATTER_GROUPS
    const groups = new Map<string, { x: number; y: number }[]>()
    for (const r of data) {
      const px = asNumber(r[x]); const py = asNumber(r[y])
      if (px === null || py === null) continue
      const g = colour ? String(r[cb!] ?? "") : ""
      if (!groups.has(g)) groups.set(g, [])
      groups.get(g)!.push({ x: px, y: py })
    }
    return {
      kind: "scatter", xKey: x, yKey: y,
      groups: [...groups.entries()].map(([name, points]) => ({ name, points })),
    }
  }

  if (type === "pie") {
    return { kind: "pie", data, xKey: x, yKey: y ?? "" }
  }

  if (type === "heatmap") {
    const cb = spec.colorBy
    if (!y || !cb) return { kind: "empty", reason: "A heatmap needs two category columns and a measure." }
    const xGroups = groupBy(data, x)
    const yGroups = groupBy(data, cb)
    const cells = yGroups.map(yg => xGroups.map(xg => {
      const vals = numbersOf(xg.rows.filter(r => String(r[cb] ?? "") === yg.key), y)
      return vals.length === 0 ? null : reduceValues(agg, vals)
    }))
    const present = cells.flat().filter((v): v is number => v !== null)
    return {
      kind: "heatmap", xKey: x, yKey: cb,
      valueLabel: agg === "sum" ? y : `${agg}(${y})`,
      xs: xGroups.map(g => g.key), ys: yGroups.map(g => g.key), cells,
      min: present.length ? Math.min(...present) : 0,
      max: present.length ? Math.max(...present) : 0,
    }
  }

  // line | area | bar
  if (spec.ys.length === 0) return { kind: "empty", reason: "Pick a numeric column for Y." }
  const xKind = spec.xKind ?? xKindOf(data.map(r => r[x]))
  const colorBy = spec.colorBy && spec.colorBy !== x ? spec.colorBy : undefined
  const measures = colorBy ? [spec.ys[0]] : spec.ys.slice(0, MAX_SERIES)

  let source = data
  let series: string[]
  if (colorBy) {
    const folded = foldCategories(data, colorBy, measures[0])
    source = folded.rows
    series = folded.categories
  } else {
    series = measures
  }

  const grouped = groupBy(source, x)
  let out: Row[] = grouped.map(g => {
    const row: Row = { [x]: g.raw }
    if (colorBy) {
      for (const cat of series) {
        const vals = numbersOf(g.rows.filter(r => String(r[colorBy] ?? "") === cat), measures[0])
        row[cat] = vals.length === 0 ? null : reduceValues(agg, vals)
      }
    } else {
      for (const m of measures) row[m] = reduceValues(agg, numbersOf(g.rows, m))
    }
    return row
  })

  const rowTotal = (r: Row) => series.reduce((s, k) => s + (asNumber(r[k]) ?? 0), 0)
  if (xKind === "time") {
    out = out.sort((a, b) => String(a[x]).localeCompare(String(b[x])))
  } else if (xKind === "measure") {
    out = out.sort((a, b) => (asNumber(a[x]) ?? 0) - (asNumber(b[x]) ?? 0))
  } else if (type === "bar") {
    out = out.sort((a, b) => rowTotal(b) - rowTotal(a)).slice(0, MAX_BARS)
  }

  const labels = out.map(r => String(r[x] ?? ""))
  const avgLen = labels.length ? labels.reduce((s, l) => s + l.length, 0) / labels.length : 0
  const horizontal = type === "bar" && xKind === "category"
    && (spec.horizontal ?? (avgLen > LONG_LABEL || labels.length > MANY_CATEGORIES))

  const nonNegative = out.every(r => series.every(k => (asNumber(r[k]) ?? 0) >= 0))
  const stacked = !!spec.stacked && (type === "bar" || type === "area")
    && series.length >= 2 && nonNegative

  const applied = agg !== "sum" && grouped.some(g => g.rows.length > 1)
  const base = colorBy ? measures[0] : series.length === 1 ? series[0] : ""
  return {
    kind: "cartesian", type: type as "line" | "area" | "bar", xKey: x, data: out, series, stacked, horizontal,
    yLabel: base && applied ? `${agg}(${base})` : base,
  }
}
