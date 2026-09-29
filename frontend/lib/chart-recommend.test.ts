/** Which charts a result can honestly be drawn as (./chart-recommend.ts).
 *
 *  The Analytics chart picker offered the same five types for every result and put the
 *  first column on X and the second on Y. A text second column drew an empty chart, a
 *  date was treated like any label, and a pie of forty slices was one click away. These
 *  tests pin the rules that replace that: roles come from the engine's column kinds (or
 *  the values, when the engine said nothing), unsuitable types are disabled with a
 *  reason, and the first result is shown as the chart that fits it.
 */
import assert from "node:assert/strict"
import { test } from "node:test"
import { assess, profileColumns, recommend, toChartRows } from "./chart-recommend.ts"

const daily = {
  columns: ["day", "orders"],
  kinds: ["temporal", "quantitative"],
  rows: [["2026-09-01", 3], ["2026-09-02", 5], ["2026-09-03", 4]],
}

const byRegion = {
  columns: ["region", "revenue"],
  kinds: ["text", "quantitative"],
  rows: [["Seoul", 10], ["Busan", 7], ["Daegu", 3]],
}

test("roles come from the engine's kinds", () => {
  const p = profileColumns(daily.columns, daily.rows, daily.kinds)
  assert.deepEqual(p.map(c => c.role), ["time", "measure"])
})

test("without kinds, roles are read from the values", () => {
  const p = profileColumns(["day", "n", "city"],
    [["2026-09-01", "3", "Seoul"], ["2026-09-02", "5", "Busan"], ["2026-09-03", "4", "Seoul"]])
  assert.deepEqual(p.map(c => c.role), ["time", "measure", "category"])
})

test("an id column is neither a measure nor a category", () => {
  const rows = Array.from({ length: 30 }, (_, i) => [i + 1, `u-${i}`, i % 3])
  const p = profileColumns(["customer_id", "order_uuid", "bucket"], rows,
    ["quantitative", "text", "quantitative"])
  assert.deepEqual(p.map(c => c.role), ["identifier", "identifier", "measure"])
})

test("an aggregated result's unique categories are still categories", () => {
  const p = profileColumns(byRegion.columns, byRegion.rows, byRegion.kinds)
  assert.equal(p[0].role, "category")
})

test("time and a measure are shown as a line", () => {
  const r = recommend(profileColumns(daily.columns, daily.rows, daily.kinds), daily.rows.length)
  assert.equal(r.best, "line")
  assert.equal(r.x, "day")
  assert.equal(r.y, "orders")
})

test("a category and a measure are shown as bars", () => {
  const r = recommend(profileColumns(byRegion.columns, byRegion.rows, byRegion.kinds), 3)
  assert.equal(r.best, "bar")
  assert.equal(r.x, "region")
  assert.equal(r.y, "revenue")
})

test("a result with no measure stays a table, and says why charts are off", () => {
  const p = profileColumns(["name", "city"], [["a", "Seoul"], ["b", "Busan"]], ["text", "text"])
  const r = recommend(p, 2)
  assert.equal(r.best, "table")
  assert.equal(r.availability.bar.ok, false)
  assert.match(r.availability.bar.reason ?? "", /numeric/i)
})

test("one row is KPI tiles, not a one-bar chart", () => {
  const p = profileColumns(["total"], [[42]], ["quantitative"])
  const r = recommend(p, 1)
  assert.equal(r.best, "kpi")
  assert.equal(r.availability.bar.ok, false)
  assert.equal(r.availability.table.ok, true)
})

test("a line needs time or numbers on X", () => {
  const p = profileColumns(byRegion.columns, byRegion.rows, byRegion.kinds)
  const a = assess("line", p[0], p[1], 3)
  assert.equal(a.ok, false)
  assert.match(a.reason ?? "", /Bar/)
})

test("a pie needs a few categories and no negative values", () => {
  const p = profileColumns(byRegion.columns, byRegion.rows, byRegion.kinds)
  assert.equal(assess("pie", p[0], p[1], 3).ok, true)

  const many = Array.from({ length: 12 }, (_, i) => [`c${i}`, i + 1])
  const pm = profileColumns(["c", "v"], many, ["text", "quantitative"])
  const tooMany = assess("pie", pm[0], pm[1], 12)
  assert.equal(tooMany.ok, false)
  assert.match(tooMany.reason ?? "", /12/)

  const neg = profileColumns(["c", "v"], [["a", 3], ["b", -1]], ["text", "quantitative"])
  assert.equal(assess("pie", neg[0], neg[1], 2).ok, false)
})

test("too many bars to read is refused with the count", () => {
  const rows = Array.from({ length: 80 }, (_, i) => [`sku-${i % 70}`, i])
  const p = profileColumns(["sku", "units"], rows, ["text", "quantitative"])
  const a = assess("bar", p[0], p[1], rows.length)
  assert.equal(a.ok, false)
  assert.match(a.reason ?? "", /70/)
})

test("a repeated X is allowed but flagged", () => {
  const rows = [["Seoul", 1], ["Seoul", 2], ["Busan", 3]]
  const p = profileColumns(["city", "n"], rows, ["text", "quantitative"])
  const a = assess("bar", p[0], p[1], 3)
  assert.equal(a.ok, true)
  assert.match(a.note ?? "", /summed/)
  const avg = assess("bar", p[0], p[1], 3, { aggregate: "avg" })
  assert.match(avg.note ?? "", /averaged/)
})

test("the table is always available", () => {
  const r = recommend([], 0)
  assert.equal(r.availability.table.ok, true)
  assert.equal(r.best, "table")
})

test("chart rows turn numeric strings of a measure into numbers", () => {
  const p = profileColumns(["d", "v"], [["2026-09-01", "1.5"], ["2026-09-02", "2"]],
    ["temporal", "quantitative"])
  const out = toChartRows(["d", "v"], [["2026-09-01", "1.5"], ["2026-09-02", "2"]], p)
  assert.deepEqual(out, [{ d: "2026-09-01", v: 1.5 }, { d: "2026-09-02", v: 2 }])
})
