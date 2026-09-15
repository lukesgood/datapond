"use client"

import Link from "next/link"
import { ArrowRight } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { formatUsd } from "@/lib/format-usd"
import { totalSpendLabel } from "@/lib/spend-summary"
import type { ActivityTotals, ActorSummary } from "@/lib/dashboard-activity"

export type GlobalBudget = { spend: number; max_budget: number; pct: number; alert: boolean } | null

const CALLERS_SHOWN = 5

function Metric({ label, value, sub, warn, title }: { label: string; value: string; sub?: string; warn?: boolean; title?: string }) {
  return (
    <div className="border-b px-5 py-4 last:border-b-0 sm:[&:nth-child(odd)]:border-r lg:border-b-0 lg:border-r lg:last:border-r-0">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className={`dp-num mt-1 text-3xl font-semibold tracking-tight${warn ? " text-[var(--dp-warn-text)]" : ""}`} title={title}>{value}</p>
      {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}

/** Today's tool calls and model spend — the part of the Overview that answers the question.
 *  Each metric appears only for a caller whose permissions let them read its source. */
export function ActivityPanel({ canAudit, canSpend, actors, totals, spend, budget }: {
  canAudit: boolean
  canSpend: boolean
  actors: ActorSummary[] | null
  totals: ActivityTotals | null
  spend: unknown
  budget: GlobalBudget
}) {
  if (!canAudit && !canSpend) return null
  const spendLabel = totalSpendLabel(spend)
  const spendSub = !spendLabel.measured
    ? "Not measured"
    : budget
      ? `lifetime · ${budget.pct}% of ${formatUsd(budget.max_budget)} budget`
      : "lifetime · no global budget"

  return (
    <Card>
      <CardContent className="p-0">
        <div className="grid sm:grid-cols-2 lg:grid-cols-4">
          {canAudit && (
            <>
              <Metric label="Tool calls today" value={totals ? totals.calls.toLocaleString("en-US") : "—"}
                      sub={totals ? `${totals.callers} caller${totals.callers === 1 ? "" : "s"}` : "Not measured"} />
              <Metric label="Errors" value={totals ? totals.errors.toLocaleString("en-US") : "—"}
                      sub={totals ? `${totals.degraded} degraded` : "Not measured"} warn={!!totals && totals.errors > 0} />
              <Metric label="PII values masked" value={totals ? totals.piiMasked.toLocaleString("en-US") : "—"}
                      sub={totals ? "across today's calls" : "Not measured"} />
            </>
          )}
          {canSpend && (
            <Metric label="Model spend" value={spendLabel.text} title={spendLabel.title} sub={spendSub} warn={!!budget?.alert} />
          )}
        </div>

        {canAudit && (
          <div className="border-t px-5 py-4">
            <div className="mb-2 flex items-baseline justify-between gap-2">
              <h2 className="text-sm font-semibold">Callers today</h2>
              <Link href="/governance" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                Audit log <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            {actors === null ? (
              <p className="text-sm text-muted-foreground">Caller activity could not be loaded.</p>
            ) : actors.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No tool calls yet today. <Link href="/connect" className="text-primary hover:underline">Connect an agent</Link>
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="pb-1.5 font-medium">Caller</th>
                    <th className="pb-1.5 text-right font-medium">Calls</th>
                    <th className="pb-1.5 text-right font-medium">Errors</th>
                    <th className="pb-1.5 text-right font-medium">PII masked</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {actors.slice(0, CALLERS_SHOWN).map((a) => (
                    <tr key={`${a.actor_id ?? ""}-${a.actor_username}-${a.actor_kind}`}>
                      <td className="py-1.5">
                        <span className="font-medium">{a.actor_username}</span>
                        <span className="ml-2 text-xs text-muted-foreground">{a.actor_kind}</span>
                      </td>
                      <td className="dp-num py-1.5 text-right">{(a.calls ?? 0).toLocaleString("en-US")}</td>
                      <td className={`dp-num py-1.5 text-right${(a.error ?? 0) > 0 ? " text-[var(--dp-warn-text)]" : ""}`}>{a.error ?? 0}</td>
                      <td className="dp-num py-1.5 text-right">{a.pii_masked ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {actors && actors.length > CALLERS_SHOWN && (
              <p className="mt-2 text-xs text-muted-foreground">+{actors.length - CALLERS_SHOWN} more in the audit log</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
