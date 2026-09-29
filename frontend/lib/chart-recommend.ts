/** Which charts a query result can honestly be drawn as, and which one fits it best.
 *
 *  The form follows the data's job: a measure over time is a line, a measure per
 *  category is a bar, a part of a small whole may be a pie, and anything else — one
 *  row, no measure, free text — stays a table. Types that do not fit are not hidden;
 *  they are disabled with a sentence saying why, so the picker teaches instead of
 *  failing silently.
 *
 *  Column kinds come from the engine (QueryResult.column_types). When a result has
 *  none, roles are read from the values.
 */
import type { ChartType } from "../components/query/chart-renderer"

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
  y: string
  availability: Record<ChartType, Availability>
  xOptions: string[]
  yOptions: string[]
}

// More bars than this cannot be read, and are usually an un-aggregated result.
const MAX_BARS = 50
// A pie compares shares by angle; past a handful of slices nobody can.
const MAX_SLICES = 5

const ISO_DATE = /^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?(Z|[+-]\d{2}:?\d{2})?$/
const ID_NAME = /(^id$|_id$|^id_|uuid)/i

function asNumber(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v)
  return null
}

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

const ONE_ROW = "One row — a chart of a single point says nothing the table does not."
const NO_MEASURE = "Needs a numeric column to plot; this result has none."

/** Whether `type` fits these axes. */
export function assess(type: ChartType, x: ColumnProfile | undefined,
                       y: ColumnProfile | undefined, rowCount: number): Availability {
  if (type === "table") return { ok: true }
  if (rowCount === 0) return { ok: false, reason: "No rows to plot." }
  if (rowCount === 1) return { ok: false, reason: ONE_ROW }
  if (!y || y.role !== "measure") {
    return { ok: false, reason: y ? `Y (${y.name}) is not numeric. Pick a numeric column.` : NO_MEASURE }
  }
  if (!x) return { ok: false, reason: "Pick an X column." }
  if (x.role === "identifier") {
    return { ok: false, reason: `X (${x.name}) is a unique label per row, not something to group by.` }
  }
  if (x.role === "other") return { ok: false, reason: `X (${x.name}) cannot be placed on an axis.` }

  const repeatNote = x.repeats
    ? `X (${x.name}) repeats, so points overlap. Aggregate with GROUP BY ${x.name}.`
    : undefined

  if (type === "line" || type === "area") {
    if (x.role !== "time" && x.role !== "measure") {
      return { ok: false, reason: `${type === "line" ? "Line" : "Area"} needs a date or number on X; ${x.name} is a category — use Bar.` }
    }
    return { ok: true, note: repeatNote }
  }
  if (type === "bar") {
    if (x.distinct > MAX_BARS) {
      return { ok: false, reason: `X (${x.name}) has ${x.distinct} distinct values — too many bars to read. Aggregate or LIMIT to the top ${MAX_BARS}.` }
    }
    return { ok: true, note: repeatNote }
  }
  if (type === "pie") {
    if (x.role !== "category") {
      return { ok: false, reason: `Pie needs categories on X; ${x.name} is ${x.role === "time" ? "a date" : "a number"}.` }
    }
    if (x.distinct > MAX_SLICES) {
      return { ok: false, reason: `Pie reads only up to ${MAX_SLICES} slices; ${x.name} has ${x.distinct}. Use Bar.` }
    }
    if (y.hasNegative) return { ok: false, reason: `Pie cannot show negative values in ${y.name}.` }
    if (x.repeats) return { ok: false, reason: `Each slice must appear once; aggregate with GROUP BY ${x.name}.` }
    return { ok: true }
  }
  return { ok: true }
}

const TYPES: ChartType[] = ["table", "line", "bar", "area", "pie"]

/** The best chart for this result and the axes it would use. `x`/`y` override the
 *  default axes (the user's own choice), and availability is judged on those. */
export function recommend(profiles: ColumnProfile[], rowCount: number,
                          chosen?: { x?: string; y?: string }): Recommendation {
  const byName = new Map(profiles.map(p => [p.name, p]))
  const measures = profiles.filter(p => p.role === "measure")
  const times = profiles.filter(p => p.role === "time")
  const categories = profiles.filter(p => p.role === "category")

  const defaultX = (times[0] ?? categories[0] ?? profiles.find(p => p.role !== "identifier") ?? profiles[0])?.name ?? ""
  const defaultY = (measures.find(p => p.name !== defaultX) ?? measures[0])?.name ?? ""
  const x = chosen?.x && byName.has(chosen.x) ? chosen.x : defaultX
  const y = chosen?.y && byName.has(chosen.y) ? chosen.y : defaultY

  const availability = Object.fromEntries(
    TYPES.map(t => [t, assess(t, byName.get(x), byName.get(y), rowCount)]),
  ) as Record<ChartType, Availability>

  let best: ChartType = "table"
  const xRole = byName.get(x)?.role
  if (xRole === "time" && availability.line.ok) best = "line"
  else if (xRole === "category" && availability.bar.ok) best = "bar"

  return {
    best, x, y, availability,
    xOptions: profiles.filter(p => p.role === "time" || p.role === "category" || p.role === "measure").map(p => p.name),
    yOptions: measures.map(p => p.name),
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
