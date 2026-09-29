/** The forms added beyond line/bar/area/pie (./chart-recommend.ts): KPI tiles, several
 *  series, stacking, scatter, histogram and heatmap — which result each is recommended
 *  for, and when it is refused with a reason.
 */
import assert from "node:assert/strict"
import { test } from "node:test"
import {
  assess, assessStacked, chartSpecFor, profileColumns, recommend, resolveYs,
} from "./chart-recommend.ts"

const Q = "quantitative"
const names = (n: number) => Array.from({ length: n }, (_, i) => `m${i}`)

test("a one-row result with one to four measures is KPI tiles", () => {
  for (const n of [1, 4]) {
    const p = profileColumns(names(n), [names(n).map(() => 5)], names(n).map(() => Q))
    const r = recommend(p, 1)
    assert.equal(r.best, "kpi")
    assert.equal(r.kpiColumns.length, n)
  }
})

test("a one-row result with five measures is not a KPI, and says how many", () => {
  const p = profileColumns(names(5), [[1, 2, 3, 4, 5]], names(5).map(() => Q))
  const r = recommend(p, 1)
  assert.equal(r.best, "table")
  assert.equal(r.availability.kpi.ok, false)
  assert.match(r.availability.kpi.reason ?? "", /5/)
})

test("KPI needs exactly one row", () => {
  const p = profileColumns(["n"], [[1], [2]], [Q])
  assert.equal(recommend(p, 2).availability.kpi.ok, false)
})

const wide = (n: number) => {
  const cols = ["day", ...names(n)]
  const rows = [["2026-09-01", ...names(n).map(() => 1)], ["2026-09-02", ...names(n).map(() => 2)]]
  return profileColumns(cols, rows, ["temporal", ...names(n).map(() => Q)])
}

test("line, area and bar take up to five measures; six is refused with a reason", () => {
  const five = recommend(wide(5), 2, { ys: names(5) })
  assert.equal(five.availability.line.ok, true)
  assert.equal(five.availability.bar.ok, true)
  const six = recommend(wide(6), 2, { ys: names(6) })
  for (const t of ["line", "area", "bar"] as const) {
    assert.equal(six.availability[t].ok, false)
    assert.match(six.availability[t].reason ?? "", /5 series/)
  }
})

test("several measures are drawn together, but never chosen by default", () => {
  assert.deepEqual(recommend(wide(3), 2).ys, ["m0"])
  assert.deepEqual(recommend(wide(3), 2, { ys: ["m0", "m2"] }).ys, ["m0", "m2"])
})

test("a legacy single y still works", () => {
  assert.deepEqual(recommend(wide(3), 2, { y: "m1" }).ys, ["m1"])
  assert.deepEqual(resolveYs({ yAxis: "orders" }), ["orders"])
  assert.deepEqual(resolveYs({ yAxes: ["a", "b"], yAxis: "a" }), ["a", "b"])
  assert.deepEqual(resolveYs({}), [])
})

const long = () => {
  const rows: unknown[][] = []
  for (const d of ["2026-09-01", "2026-09-02", "2026-09-03"]) {
    for (const c of ["a", "b", "c"]) rows.push([d, c, 1])
  }
  return { cols: ["day", "channel", "orders"], rows, kinds: ["temporal", "text", Q] }
}

test("time + category + measure splits into one series per category", () => {
  const { cols, rows, kinds } = long()
  const r = recommend(profileColumns(cols, rows, kinds), rows.length)
  assert.equal(r.best, "line")
  assert.equal(r.x, "day")
  assert.equal(r.colorBy, "channel")
  assert.deepEqual(r.ys, ["orders"])
})

test("more than five categories note the Other fold", () => {
  const rows: unknown[][] = []
  for (const d of ["2026-09-01", "2026-09-02"]) {
    for (let i = 0; i < 8; i++) rows.push([d, `c${i}`, i])
  }
  const r = recommend(profileColumns(["day", "c", "n"], rows, ["temporal", "text", Q]), rows.length)
  assert.equal(r.availability.line.ok, true)
  assert.match(r.availability.line.note ?? "", /top 4.*Other/)
})

test("splitting by a category and plotting several measures do not combine", () => {
  const rows = [["2026-09-01", "a", 1, 2], ["2026-09-01", "b", 1, 2],
    ["2026-09-02", "a", 1, 2], ["2026-09-02", "b", 1, 2]]
  const p = profileColumns(["day", "c", "m0", "m1"], rows, ["temporal", "text", Q, Q])
  const r = recommend(p, 4, { ys: ["m0", "m1"], colorBy: "c" })
  assert.deepEqual(r.ys, ["m0"])
  const auto = recommend(p, 4, { ys: ["m0", "m1"] })
  assert.equal(auto.colorBy, "")
  assert.deepEqual(auto.ys, ["m0", "m1"])
})

test("stacking needs two series and no negative parts", () => {
  const p = profileColumns(["d", "a", "b"], [["2026-09-01", 1, -2], ["2026-09-02", 2, 3]],
    ["temporal", Q, Q])
  assert.equal(assessStacked(1, [p[1]]).ok, false)
  assert.equal(assessStacked(2, [p[1], p[2]]).ok, false)
  assert.match(assessStacked(2, [p[1], p[2]]).reason ?? "", /negative/)
  assert.equal(assessStacked(2, [p[1]]).ok, true)
  assert.equal(recommend(p, 2, { ys: ["a", "b"], stacked: true }).stacked, false)
  assert.equal(recommend(p, 2, { ys: ["a"], stacked: true }).stacked, false)
  const ok = profileColumns(["d", "a", "b"], [["2026-09-01", 1, 2], ["2026-09-02", 2, 3]],
    ["temporal", Q, Q])
  assert.equal(recommend(ok, 2, { ys: ["a", "b"], stacked: true }).stacked, true)
})

test("a bar asked to stack is saved as stacked, a line never is", () => {
  const ok = profileColumns(["d", "a", "b"], [["2026-09-01", 1, 2], ["2026-09-02", 2, 3]],
    ["temporal", Q, Q])
  const rec = recommend(ok, 2, { ys: ["a", "b"], stacked: true })
  assert.equal(chartSpecFor("bar", rec).stacked, true)
  assert.equal(chartSpecFor("line", rec).stacked, undefined)
  assert.deepEqual(chartSpecFor("bar", rec).yAxes, ["a", "b"])
})

const twoMeasures = () => {
  const rows = Array.from({ length: 10 }, (_, i) => [i, i * 2])
  return profileColumns(["height", "weight"], rows, [Q, Q])
}

test("two measures and nothing else are a scatter", () => {
  const r = recommend(twoMeasures(), 10)
  assert.equal(r.best, "scatter")
  assert.equal(r.x, "height")
  assert.deepEqual(r.ys, ["weight"])
})

test("a scatter needs a numeric X different from Y", () => {
  const p = profileColumns(["day", "n"], [["2026-09-01", 1], ["2026-09-02", 2]], ["temporal", Q])
  assert.equal(assess("scatter", p[0], p[1], 2).ok, false)
  const m = twoMeasures()
  assert.equal(assess("scatter", m[0], m[0], 10).ok, false)
})

test("scatter colour is kept up to three categories and dropped beyond", () => {
  const rows = Array.from({ length: 12 }, (_, i) => [i, i * 2, `g${i % 4}`])
  const p = profileColumns(["a", "b", "g"], rows, [Q, Q, "text"])
  const four = assess("scatter", p[0], p[1], 12, { colorBy: p[2] })
  assert.equal(four.ok, true)
  assert.match(four.note ?? "", /Colour by g is off/)
  const rows3 = Array.from({ length: 12 }, (_, i) => [i, i * 2, `g${i % 3}`])
  const p3 = profileColumns(["a", "b", "g"], rows3, [Q, Q, "text"])
  assert.equal(assess("scatter", p3[0], p3[1], 12, { colorBy: p3[2] }).note, undefined)
  const r3 = recommend(p3, 12, { x: "a", y: "b" })
  assert.equal(r3.colorBy, "g")
  assert.equal(r3.best, "scatter")
})

test("one measure over many rows is a histogram, needing at least 20", () => {
  const rows = (n: number) => Array.from({ length: n }, (_, i) => [i])
  const r = recommend(profileColumns(["amount"], rows(20), [Q]), 20)
  assert.equal(r.best, "histogram")
  assert.match(r.availability.histogram.note ?? "", /20 values.*bins/)
  const few = recommend(profileColumns(["amount"], rows(19), [Q]), 19)
  assert.equal(few.availability.histogram.ok, false)
  assert.match(few.availability.histogram.reason ?? "", /20/)
  assert.notEqual(few.best, "histogram")
})

test("a histogram is reachable from a chart drawn on other axes", () => {
  const rows = Array.from({ length: 30 }, (_, i) => ["2026-09-01", i])
  const r = recommend(profileColumns(["day", "amount"], rows, ["temporal", Q]), 30)
  assert.equal(r.availability.histogram.ok, true)
  assert.deepEqual(r.axesFor.histogram.ys, ["amount"])
})

test("a scatter is reachable from a time chart when two measures exist", () => {
  const rows = [["2026-09-01", 1, 2], ["2026-09-02", 2, 3], ["2026-09-03", 3, 5]]
  const r = recommend(profileColumns(["day", "a", "b"], rows, ["temporal", Q, Q]), 3)
  assert.equal(r.best, "line")
  assert.equal(r.availability.scatter.ok, true)
  assert.equal(r.axesFor.scatter.x, "a")
  assert.deepEqual(r.axesFor.scatter.ys, ["b"])
})

const grid = (nx: number, ny: number) => {
  const rows: unknown[][] = []
  for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) rows.push([`x${i}`, `y${j}`, i + j])
  return { rows, p: profileColumns(["x", "y", "v"], rows, ["text", "text", Q]) }
}

test("two categories and a measure are a heatmap when the second has many values", () => {
  const { rows, p } = grid(8, 8)
  const r = recommend(p, rows.length)
  assert.equal(r.best, "heatmap")
  assert.equal(r.colorBy, "y")
})

test("two categories with a small second one stay a bar, with the heatmap available", () => {
  const { rows, p } = grid(8, 3)
  const r = recommend(p, rows.length)
  assert.equal(r.best, "bar")
  assert.equal(r.availability.heatmap.ok, true)
})

test("a heatmap is limited to 30 by 30 cells", () => {
  const ok = grid(30, 30)
  assert.equal(recommend(ok.p, ok.rows.length).availability.heatmap.ok, true)
  const big = grid(31, 5)
  const a = recommend(big.p, big.rows.length).availability.heatmap
  assert.equal(a.ok, false)
  assert.match(a.reason ?? "", /30 × 30.*31/)
})

test("a heatmap needs a second category", () => {
  const rows = [["Seoul", 10], ["Busan", 7], ["Daegu", 3]]
  const a = recommend(profileColumns(["region", "revenue"], rows, ["text", Q]), 3).availability.heatmap
  assert.equal(a.ok, false)
  assert.match(a.reason ?? "", /second category/)
})

test("the pie keeps its strict rules alongside the new forms", () => {
  const p = profileColumns(["region", "revenue"], [["Seoul", 10], ["Busan", 7]], ["text", Q])
  assert.equal(recommend(p, 2).availability.pie.ok, true)
  const rp = profileColumns(["c", "v"], [["a", 1], ["a", 2], ["b", 3]], ["text", Q])
  assert.equal(recommend(rp, 3).availability.pie.ok, false)
})

test("an aggregation choice reaches the note, and only shows when X repeats", () => {
  const rows = [["Seoul", 1], ["Seoul", 2], ["Busan", 3]]
  const r = recommend(profileColumns(["city", "n"], rows, ["text", Q]), 3, { aggregate: "max" })
  assert.equal(r.aggregates, true)
  assert.match(r.availability.bar.note ?? "", /maximum/)
  const flat = recommend(profileColumns(["city", "n"], [["a", 1], ["b", 2]], ["text", Q]), 2)
  assert.equal(flat.aggregates, false)
})
