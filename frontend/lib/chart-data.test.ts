/** What each chart form draws (./chart-data.ts): aggregation of repeated X, the pivot
 *  of a long result into series, the fold into "Other", top-down bars, binning, the
 *  heatmap matrix — and that a dashboard saved before multi-series still shapes.
 */
import assert from "node:assert/strict"
import { test } from "node:test"
import { foldCategories, histogramBins, shapeChart, sturgesBins, xKindOf } from "./chart-data.ts"
import { resolveYs } from "./chart-recommend.ts"

type Row = Record<string, unknown>

const sales: Row[] = [
  { day: "2026-09-02", region: "Seoul", n: 4 },
  { day: "2026-09-01", region: "Seoul", n: 1 },
  { day: "2026-09-01", region: "Busan", n: 2 },
  { day: "2026-09-02", region: "Busan", n: 6 },
]

function cartesian(spec: Parameters<typeof shapeChart>[0], data: Row[]) {
  const s = shapeChart(spec, data)
  assert.equal(s.kind, "cartesian")
  if (s.kind !== "cartesian") throw new Error("unreachable")
  return s
}

test("repeated X is summed by default, and the other aggregations apply", () => {
  const by = (aggregate: "sum" | "avg" | "count" | "min" | "max") =>
    cartesian({ type: "bar", x: "region", ys: ["n"], aggregate }, sales)
      .data.find(r => r.region === "Seoul")?.n
  assert.equal(by("sum"), 5)
  assert.equal(by("avg"), 2.5)
  assert.equal(by("count"), 2)
  assert.equal(by("min"), 1)
  assert.equal(by("max"), 4)
})

test("a time X is sorted ascending whatever order the rows came in", () => {
  const s = cartesian({ type: "line", x: "day", ys: ["n"] }, sales)
  assert.deepEqual(s.data.map(r => r.day), ["2026-09-01", "2026-09-02"])
  assert.deepEqual(s.data.map(r => r.n), [3, 10])
})

test("a categorical X is sorted descending by value", () => {
  const rows = [{ c: "a", v: 1 }, { c: "b", v: 9 }, { c: "c", v: 5 }]
  const s = cartesian({ type: "bar", x: "c", ys: ["v"] }, rows)
  assert.deepEqual(s.data.map(r => r.c), ["b", "c", "a"])
})

test("long format pivots into one series per category", () => {
  const s = cartesian({ type: "line", x: "day", ys: ["n"], colorBy: "region" }, sales)
  assert.deepEqual([...s.series].sort(), ["Busan", "Seoul"])
  const d2 = s.data.find(r => r.day === "2026-09-02")
  assert.equal(d2?.Seoul, 4)
  assert.equal(d2?.Busan, 6)
})

test("a missing pair is a gap, not a zero", () => {
  const s = cartesian({ type: "line", x: "day", ys: ["n"], colorBy: "region" },
    sales.filter(r => !(r.day === "2026-09-01" && r.region === "Busan")))
  assert.equal(s.data.find(r => r.day === "2026-09-01")?.Busan, null)
})

test("up to five categories are all kept", () => {
  const rows = ["a", "b", "c", "d", "e"].map((c, i) => ({ day: "d1", c, v: i + 1 }))
  const f = foldCategories(rows, "c", "v")
  assert.equal(f.categories.length, 5)
  assert.ok(!f.categories.includes("Other"))
})

test("beyond five categories the top four stay and the rest become Other", () => {
  const rows = Array.from({ length: 8 }, (_, i) => ({ day: "d1", c: `c${i}`, v: i + 1 }))
  const s = cartesian({ type: "bar", x: "day", ys: ["v"], colorBy: "c" }, rows)
  assert.equal(s.series.length, 5)
  assert.deepEqual(s.series.slice(0, 4), ["c7", "c6", "c5", "c4"])
  assert.equal(s.series[4], "Other")
  // c0..c3 = 1+2+3+4
  assert.equal(s.data[0].Other, 10)
})

test("several measures become several series", () => {
  const rows = [{ d: "2026-09-01", a: 1, b: 2 }, { d: "2026-09-02", a: 3, b: 4 }]
  const s = cartesian({ type: "line", x: "d", ys: ["a", "b"] }, rows)
  assert.deepEqual(s.series, ["a", "b"])
  assert.equal(s.yLabel, "")
})

test("no more than five measures are drawn", () => {
  const row = { d: "2026-09-01", a: 1, b: 1, c: 1, e: 1, f: 1, g: 1 }
  const s = cartesian({ type: "line", x: "d", ys: ["a", "b", "c", "e", "f", "g"] }, [row])
  assert.equal(s.series.length, 5)
})

test("stacking applies to bar and area with two series and no negatives only", () => {
  const rows = [{ d: "x", a: 1, b: 2 }, { d: "y", a: 3, b: 4 }]
  assert.equal(cartesian({ type: "bar", x: "d", ys: ["a", "b"], stacked: true }, rows).stacked, true)
  assert.equal(cartesian({ type: "area", x: "d", ys: ["a", "b"], stacked: true }, rows).stacked, true)
  assert.equal(cartesian({ type: "line", x: "d", ys: ["a", "b"], stacked: true }, rows).stacked, false)
  assert.equal(cartesian({ type: "bar", x: "d", ys: ["a"], stacked: true }, rows).stacked, false)
  const neg = [{ d: "x", a: 1, b: -2 }, { d: "y", a: 3, b: 4 }]
  assert.equal(cartesian({ type: "bar", x: "d", ys: ["a", "b"], stacked: true }, neg).stacked, false)
})

test("bars turn horizontal for long labels or many categories, and can be forced", () => {
  const short = Array.from({ length: 5 }, (_, i) => ({ c: `k${i}`, v: i }))
  assert.equal(cartesian({ type: "bar", x: "c", ys: ["v"] }, short).horizontal, false)
  const longLabels = Array.from({ length: 5 }, (_, i) => ({ c: `a very long label ${i}`, v: i }))
  assert.equal(cartesian({ type: "bar", x: "c", ys: ["v"] }, longLabels).horizontal, true)
  const many = Array.from({ length: 13 }, (_, i) => ({ c: `k${i}`, v: i }))
  assert.equal(cartesian({ type: "bar", x: "c", ys: ["v"] }, many).horizontal, true)
  assert.equal(cartesian({ type: "bar", x: "c", ys: ["v"], horizontal: false }, many).horizontal, false)
  const time = Array.from({ length: 20 }, (_, i) => ({ d: `2026-09-${String(i + 1).padStart(2, "0")}`, v: i }))
  assert.equal(cartesian({ type: "bar", x: "d", ys: ["v"] }, time).horizontal, false)
})

test("bars are capped at fifty", () => {
  const rows = Array.from({ length: 80 }, (_, i) => ({ c: `k${i}`, v: i }))
  assert.equal(cartesian({ type: "bar", x: "c", ys: ["v"] }, rows).data.length, 50)
})

test("a KPI is one tile per measure of the single row", () => {
  const s = shapeChart({ type: "kpi", x: "", ys: ["revenue", "orders"] }, [{ revenue: 1200, orders: "7" }])
  assert.equal(s.kind, "kpi")
  if (s.kind === "kpi") {
    assert.deepEqual(s.tiles, [{ name: "revenue", value: 1200 }, { name: "orders", value: 7 }])
  }
})

test("a scatter has one group, or one per category up to three", () => {
  const rows = [{ a: 1, b: 2, g: "x" }, { a: 2, b: 3, g: "y" }, { a: 3, b: 4, g: "x" }]
  const plain = shapeChart({ type: "scatter", x: "a", ys: ["b"] }, rows)
  assert.equal(plain.kind === "scatter" && plain.groups.length, 1)
  const coloured = shapeChart({ type: "scatter", x: "a", ys: ["b"], colorBy: "g" }, rows)
  assert.equal(coloured.kind === "scatter" && coloured.groups.length, 2)
  const four = shapeChart({ type: "scatter", x: "a", ys: ["b"], colorBy: "g" },
    ["p", "q", "r", "s"].map((g, i) => ({ a: i, b: i, g })))
  assert.equal(four.kind === "scatter" && four.groups.length, 1)
})

test("Sturges' rule picks the bin count, clamped to 5..20", () => {
  assert.equal(sturgesBins(20), 6)
  assert.equal(sturgesBins(100), 8)
  assert.equal(sturgesBins(1_000_000_000), 20)
  assert.equal(sturgesBins(4), 5)
})

test("histogram bins cover every value, the maximum in the last bin", () => {
  const values = Array.from({ length: 100 }, (_, i) => i)
  const bins = histogramBins(values)
  assert.equal(bins.length, 8)
  assert.equal(bins.reduce((s, b) => s + b.count, 0), 100)
  assert.equal(bins[bins.length - 1].to, 99)
  assert.ok(bins[bins.length - 1].count >= 1)
})

test("a constant column is one bin", () => {
  assert.equal(histogramBins([3, 3, 3]).length, 1)
  assert.deepEqual(histogramBins([]), [])
})

test("the heatmap is a matrix of aggregated cells, with gaps for absent pairs", () => {
  const rows = [
    { r: "Seoul", p: "A", v: 1 }, { r: "Seoul", p: "A", v: 2 },
    { r: "Seoul", p: "B", v: 5 }, { r: "Busan", p: "A", v: 7 },
  ]
  const s = shapeChart({ type: "heatmap", x: "r", ys: ["v"], colorBy: "p" }, rows)
  assert.equal(s.kind, "heatmap")
  if (s.kind !== "heatmap") return
  assert.deepEqual(s.xs, ["Seoul", "Busan"])
  assert.deepEqual(s.ys, ["A", "B"])
  assert.deepEqual(s.cells, [[3, 7], [5, null]])
  assert.equal(s.min, 3)
  assert.equal(s.max, 7)
  const avg = shapeChart({ type: "heatmap", x: "r", ys: ["v"], colorBy: "p", aggregate: "avg" }, rows)
  assert.equal(avg.kind === "heatmap" && avg.cells[0][0], 1.5)
})

test("X kind is read from the values for a config that carries no profile", () => {
  assert.equal(xKindOf(["2026-09-01", "2026-09-02"]), "time")
  assert.equal(xKindOf([1, 2, 3]), "measure")
  assert.equal(xKindOf(["a", "b"]), "category")
})

test("a dashboard saved before multi-series (chartType, xAxis, yAxis) still shapes", () => {
  const legacy = { chartType: "bar" as const, xAxis: "region", yAxis: "n" }
  const s = cartesian(
    { type: legacy.chartType, x: legacy.xAxis, ys: resolveYs(legacy) }, sales)
  assert.deepEqual(s.series, ["n"])
  assert.equal(s.data.length, 2)
  const pie = shapeChart({ type: "pie", x: "region", ys: resolveYs({ yAxis: "n" }) }, sales)
  assert.equal(pie.kind, "pie")
})

test("no rows shapes as empty rather than throwing", () => {
  assert.equal(shapeChart({ type: "line", x: "a", ys: ["b"] }, []).kind, "empty")
})
