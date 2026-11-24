"use client"

/** Profile tab of a catalog table: the table's own statistics (no scan), its recent
 *  Iceberg snapshots, and the keys its source database declares. */
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorBox } from "@/components/ui/error-box"
import { tableHref } from "@/lib/relationship-view"
import {
  distinctLabel, nullPct, snapshotLabel, type TableKeys, type TableProfile,
} from "@/lib/table-profile"

export function TableProfileView({ profile, error, keys, onColumn, drilled }: {
  profile: TableProfile | null
  error: string | null
  keys: TableKeys | null
  /** Open a column's values (the column drill-down); the link is left out without it. */
  onColumn?: (name: string) => void
  /** The column whose drill-down is open, so its row shows as selected. */
  drilled?: string | null
}) {
  if (error) return <ErrorBox msg={error} />
  if (!profile) {
    return <div className="space-y-2"><Skeleton className="h-24 w-full" /><Skeleton className="h-48 w-full" /></div>
  }
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Columns</CardTitle>
          <p className="text-xs text-muted-foreground">
            From the table&apos;s statistics, without reading its rows: distinct counts are estimates.
            {profile.rows != null && <> {profile.rows.toLocaleString("en-US")} rows.</>}
          </p>
        </CardHeader>
        <CardContent>
          {profile.restricted ? (
            <p className="text-sm text-muted-foreground">{profile.note}</p>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50 text-left">
                    <th className="p-2.5 font-medium">Column</th>
                    <th className="p-2.5 text-right font-medium">Empty</th>
                    <th className="p-2.5 text-right font-medium">Distinct</th>
                    <th className="p-2.5 font-medium">Range</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.columns.map(c => (
                    <tr key={c.name} className={`border-b last:border-b-0 ${drilled === c.name ? "bg-primary/5" : ""}`}>
                      <td className="p-2.5 font-mono text-xs">
                        {c.name}
                        {onColumn && (
                          <button type="button" onClick={() => onColumn(c.name)} aria-label={`Values of ${c.name}`}
                                  className="ml-2 font-sans text-2xs text-primary hover:underline">values ›</button>
                        )}
                      </td>
                      <td className="p-2.5 text-right tabular-nums">{nullPct(c.nulls)}</td>
                      <td className="p-2.5 text-right tabular-nums">{distinctLabel(c.distinct)}</td>
                      <td className="p-2.5 font-mono text-xs text-muted-foreground">
                        {c.hidden ? <span className="font-sans italic">hidden (masked or personal data)</span>
                          : c.low != null || c.high != null ? `${c.low ?? "?"} … ${c.high ?? "?"}` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {keys && (keys.primary.length > 0 || keys.foreign.length > 0 || keys.referenced_by.length > 0) && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Keys</CardTitle>
            <p className="text-xs text-muted-foreground">Declared in the source database (for a synced table, on the table it comes from).</p>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {keys.primary.length > 0 && (
              <p>Primary key: <span className="font-mono text-xs">{keys.primary.join(", ")}</span></p>
            )}
            {keys.foreign.map(f => (
              <p key={`${f.column}-${f.ref_table}`}>
                <span className="font-mono text-xs">{f.column}</span> refers to{" "}
                <Link href={tableHref(f.ref_table)} className="font-mono text-xs text-primary hover:underline">{f.ref_table}.{f.ref_column}</Link>
              </p>
            ))}
            {keys.referenced_by.map(r => (
              <p key={`${r.table}-${r.column}`}>
                <Link href={tableHref(r.table)} className="font-mono text-xs text-primary hover:underline">{r.table}.{r.column}</Link>
                {" "}refers to <span className="font-mono text-xs">{r.ref_column}</span>
              </p>
            ))}
          </CardContent>
        </Card>
      )}

      {profile.snapshots.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Recent changes</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm">
              {profile.snapshots.map(s => (
                <li key={s.at} className="flex justify-between gap-4">
                  <span className="text-muted-foreground">{new Date(s.at).toLocaleString()}</span>
                  <span className="tabular-nums">{snapshotLabel(s)}
                    {s.total_records != null && <span className="text-muted-foreground"> · {s.total_records.toLocaleString("en-US")} total</span>}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
