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

/** The metric keys most runs logged, most common first (ties by name), at most `max`:
 *  the columns the runs table shows. */
export function metricColumns(runs: { data: { metrics: { key: string }[] } }[], max = 3): string[] {
  const count = new Map<string, number>()
  for (const r of runs) for (const k of new Set(r.data.metrics.map(m => m.key))) count.set(k, (count.get(k) ?? 0) + 1)
  return [...count.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, max).map(([k]) => k)
}

/** What an MLflow request failure means, in words — never a bare status code. */
export function mlflowErrorText(status: number, what: string): string {
  if (status === 401 || status === 403) return `You may not ${what}.`
  if (status === 404) return `MLflow could not find that. It may have been deleted.`
  if (status === 502 || status === 503 || status === 504) return "MLflow is not reachable. Check Infrastructure."
  return `Could not ${what} (MLflow answered ${status}).`
}
