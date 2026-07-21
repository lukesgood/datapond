// Shared "best value" logic for MLflow run-comparison tables.
//
// Rule: for metrics where lower is better (name contains
// loss / error / rmse / mae / mse, case-insensitive) the best value is the
// minimum; for every other metric the best value is the maximum.
//
// Used by both the Experiments overview compare panel
// (app/experiments/page.tsx) and the experiment detail compare table
// (app/experiments/[id]/page.tsx) so the two agree on what "best" means.

export function metricLowerIsBetter(metricName: string): boolean {
  return /loss|error|rmse|mae|mse/i.test(metricName)
}

/**
 * Return the best numeric value among `values` for the given metric, or
 * `null` when there are no finite numbers. Non-numeric / missing entries are
 * ignored so callers can pass raw `(number | null | undefined)` columns.
 */
export function bestMetricValue(
  values: Array<number | null | undefined>,
  metricName: string,
): number | null {
  const nums = values.filter(
    (v): v is number => typeof v === "number" && Number.isFinite(v),
  )
  if (nums.length === 0) return null
  return metricLowerIsBetter(metricName)
    ? Math.min(...nums)
    : Math.max(...nums)
}
