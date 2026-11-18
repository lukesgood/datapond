"use client"

import Link from "next/link"
import { formatUsd } from "@/lib/format-usd"
import { totalSpendLabel } from "@/lib/spend-summary"
import { lastCallLabel } from "@/lib/overview"
import type { ActivityTotals, ActorSummary } from "@/lib/dashboard-activity"

export type GlobalBudget = { spend: number; max_budget: number; pct: number; alert: boolean } | null
export type TodayActor = ActorSummary & { refused?: number; last_call?: string | null }

const CALLERS_SHOWN = 8

function Tile({ label, value, sub, warn, title, href }: {
  label: string; value: string; sub: string; warn?: boolean; title?: string; href?: string
}) {
  return (
    <div className="rounded-lg border px-3.5 py-3">
      {href
        ? <Link href={href} className="text-xs text-muted-foreground hover:text-primary hover:underline">{label}</Link>
        : <p className="text-xs text-muted-foreground">{label}</p>}
      <p className={`dp-num mt-0.5 text-2xl font-bold leading-tight${warn ? " text-[var(--dp-warn-text)]" : ""}`} title={title}>{value}</p>
      <p className="text-xs text-muted-foreground">{sub}</p>
    </div>
  )
}

/** Today's tool calls and model spend. Each part shows only for a viewer allowed its source. */
export function TodayCard({ canAudit, canSpend, actors, totals, spend, budget }: {
  canAudit: boolean
  canSpend: boolean
  actors: TodayActor[] | null
  totals: ActivityTotals | null
  spend: unknown
  budget: GlobalBudget
}) {
  if (!canAudit && !canSpend) return null
  const now = new Date()
  const refused = actors ? actors.reduce((n, a) => n + (a.refused ?? 0), 0) : null
  const spendLabel = totalSpendLabel(spend)
  const spendSub = !spendLabel.measured
    ? "not measured"
    : budget ? `all time · ${budget.pct}% of ${formatUsd(budget.max_budget)} budget` : "all time · no global budget"
  const n = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("en-US"))

  return (
    <section aria-label="Today" className="space-y-3.5 rounded-xl border bg-card p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-base font-semibold">Today</h3>
        {canAudit && <Link href="/governance" className="text-sm text-primary hover:underline">All tool calls in Governance</Link>}
      </div>
      <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        {canAudit && (
          <>
            <Tile label="Tool calls" value={n(totals?.calls)}
                  sub={totals ? `${totals.callers} caller${totals.callers === 1 ? "" : "s"}` : "not measured"} />
            <Tile label="Refused" value={n(refused)} warn={!!totals && totals.errors > 0}
                  sub={totals ? (totals.errors ? `${totals.errors} error${totals.errors === 1 ? "" : "s"}` : "no errors") : "not measured"} />
            <Tile label="PII masked" value={n(totals?.piiMasked)} sub={totals ? "across today's calls" : "not measured"} />
          </>
        )}
        {canSpend && (
          <Tile label="Model spend" value={spendLabel.text} title={spendLabel.title} sub={spendSub}
                warn={!!budget?.alert} href="/ai" />
        )}
      </div>

      {canAudit && (actors === null ? (
        <p className="text-sm text-muted-foreground">Caller activity could not be loaded.</p>
      ) : actors.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No tool calls yet today. <Link href="/help/integrate" className="text-primary hover:underline">Connect an agent</Link>
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="bg-muted/40 text-left text-muted-foreground">
                <th scope="col" className="px-3 py-2 font-medium">Caller</th>
                <th scope="col" className="px-3 py-2 font-medium">Kind</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Calls</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Refused</th>
                <th scope="col" className="px-3 py-2 font-medium">Last call</th>
              </tr>
            </thead>
            <tbody>
              {actors.slice(0, CALLERS_SHOWN).map(a => (
                <tr key={`${a.actor_id ?? ""}-${a.actor_username}-${a.actor_kind}`} className="border-t">
                  <td className="px-3 py-2">
                    {a.actor_kind === "service" && a.actor_id
                      ? <Link href={`/agents/${encodeURIComponent(a.actor_id)}`} className="text-primary hover:underline">{a.actor_username}</Link>
                      : a.actor_username}
                  </td>
                  <td className="px-3 py-2">{a.actor_kind === "service" ? "agent" : a.actor_kind === "human" ? "person" : a.actor_kind}</td>
                  <td className="dp-num px-3 py-2 text-right">{n(a.calls ?? 0)}</td>
                  <td className={`dp-num px-3 py-2 text-right${(a.refused ?? 0) > 0 ? " text-[var(--dp-warn-text)]" : ""}`}>{a.refused ?? 0}</td>
                  <td className="px-3 py-2 text-muted-foreground">{lastCallLabel(a.last_call, now)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {actors.length > CALLERS_SHOWN && (
            <p className="border-t px-3 py-2 text-xs text-muted-foreground">+{actors.length - CALLERS_SHOWN} more in Governance</p>
          )}
        </div>
      ))}
    </section>
  )
}
