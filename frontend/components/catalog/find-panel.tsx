"use client"

import NextLink from "next/link"
import { conceptHref } from "@/lib/concept-map"
import { foundKey, summaryLine, type SearchResult } from "@/lib/catalog-search"

/** What a Catalog search found beyond table names: columns, the concepts a business
 *  word names (and the columns and segments bound to them), and metrics. Each group is
 *  a disclosure so the table list stays in view; picking a column or a metric's table
 *  opens that table in the rail. */
export function FindPanel({ result, loading, failed, onPick, canPick }: {
  result: SearchResult | null
  loading: boolean
  failed: boolean
  onPick: (key: string) => void
  /** Whether a table key is in the list the page shows (visible catalogs only). */
  canPick: (key: string) => boolean
}) {
  if (failed) {
    return (
      <p role="status" className="rounded-md border border-[var(--dp-warn)]/40 bg-[var(--dp-warn)]/10 px-3 py-1.5 text-xs">
        Column and business-word search is unavailable right now; table names still match below.
      </p>
    )
  }
  if (!result) {
    return loading ? <p role="status" className="text-xs text-muted-foreground">Searching columns and business words…</p> : null
  }
  const line = summaryLine(result)
  if (!line) {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        No column, concept or metric matches “{result.query}”.
      </p>
    )
  }
  // The label leaves the catalog out to stay short; the full name is the tooltip, since
  // the same namespace.table can exist in two catalogs (a mirror, a source).
  const tableLink = (key: string, label: string, full = key) => canPick(key)
    ? <button type="button" title={full} onClick={() => onPick(key)} className="min-w-0 truncate text-left font-mono text-xs text-primary hover:underline focus-visible:underline focus-visible:outline-none">{label}</button>
    : <span title={full} className="min-w-0 truncate font-mono text-xs">{label}</span>

  return (
    <section aria-label="Search results" className="space-y-1.5 rounded-xl border bg-card px-4 py-3 text-sm">
      <p role="status" className="font-medium">
        Found {line}{loading && <span className="ml-2 text-xs font-normal text-muted-foreground">updating…</span>}
      </p>

      {result.concepts.length > 0 && (
        <details open>
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Concepts</summary>
          <ul className="mt-1 space-y-1.5">
            {result.concepts.map(c => (
              <li key={c.name} className="text-xs">
                <NextLink href={conceptHref(c.name)} className="font-medium text-foreground hover:underline">{c.name}</NextLink>
                {c.pii && <span className="ml-1.5 rounded bg-muted px-1 py-0.5 text-2xs font-medium">PII</span>}
                {c.parent && <span className="ml-1.5 text-muted-foreground">in {c.parent}</span>}
                {c.terms.length > 0 && <span className="ml-1.5 text-muted-foreground">also {c.terms.slice(0, 4).join(", ")}</span>}
                <span className="ml-1.5 text-muted-foreground">
                  · {c.keys.length} key{c.keys.length === 1 ? "" : "s"}, {c.attributes.length} attribute{c.attributes.length === 1 ? "" : "s"}
                  {c.segments ? `, ${c.segments} segment${c.segments === 1 ? "" : "s"}` : ""}
                </span>
                {c.description && <p className="text-muted-foreground">{c.description}</p>}
              </li>
            ))}
          </ul>
          <NextLink href="/metrics?tab=concepts" className="mt-1 inline-block text-xs text-primary hover:underline">Open Concepts</NextLink>
        </details>
      )}

      {result.columns.length > 0 && (
        <details open={result.columns.length <= 12}>
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            Columns{(result.column_total ?? 0) > result.columns.length ? ` (first ${result.columns.length} of ${result.column_total})` : ""}
          </summary>
          <ul className="mt-1 grid gap-x-4 gap-y-0.5 sm:grid-cols-[repeat(2,minmax(0,1fr))]">
            {result.columns.map(c => (
              <li key={`${foundKey(c)}.${c.column}`} className="flex min-w-0 items-baseline gap-1.5">
                {tableLink(foundKey(c), `${c.namespace}.${c.table}.${c.column}`, `${c.catalog}.${c.namespace}.${c.table}.${c.column}`)}
                {c.type && <span className="shrink-0 text-2xs text-muted-foreground">{c.type}</span>}
                {c.why !== "name" && <span className="truncate text-2xs text-muted-foreground">{c.why}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {result.segments.length > 0 && (
        <details>
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Segments</summary>
          <ul className="mt-1 space-y-0.5 text-xs">
            {result.segments.map(s => (
              <li key={`${s.concept}.${foundKey(s)}.${s.filter_sql}`}>
                <NextLink href={conceptHref(s.concept)} className="font-medium hover:underline">{s.concept}</NextLink>
                <span className="text-muted-foreground"> = </span>
                <code className="text-2xs">{s.filter_sql}</code>
                <span className="text-muted-foreground"> on </span>
                {tableLink(foundKey(s), `${s.namespace}.${s.table}`)}
              </li>
            ))}
          </ul>
        </details>
      )}

      {result.metrics.length > 0 && (
        <details>
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Metrics</summary>
          <ul className="mt-1 space-y-0.5 text-xs">
            {result.metrics.map(m => {
              const [cat, ns, tbl] = m.base_table.split(".")
              return (
                <li key={m.name}>
                  <span className="font-medium">{m.label || m.name}</span>
                  <span className="ml-1 font-mono text-2xs text-muted-foreground">{m.name}</span>
                  <span className="text-muted-foreground"> on </span>
                  {tableLink(foundKey({ catalog: cat, namespace: ns, table: tbl }), `${ns}.${tbl}`)}
                </li>
              )
            })}
          </ul>
          <NextLink href="/metrics" className="mt-1 inline-block text-xs text-primary hover:underline">Open Semantic model</NextLink>
        </details>
      )}
    </section>
  )
}
