"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"
import { RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { SourceState } from "@/components/ui/source-state"
import { RailAttention } from "@/components/ui/explain-rail"
import { InfraTabs } from "@/components/infra/infra-tabs"
import { readJson, sourceStatus } from "@/lib/source-state"
import { useToast } from "@/lib/toast"
import { dayTotal, missingSentence, money, niceMax, share, type CostDay, type CostReport } from "@/lib/aws-infra"

const SERIES = [
  { key: "aurora", label: "Aurora", color: "var(--series-1)" },
  { key: "ec2", label: "EC2 node", color: "var(--series-2)" },
  { key: "other", label: "Everything else", color: "var(--series-3)" },
] as const

const shortDay = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })

function DailyChart({ days }: { days: CostDay[] }) {
  const [hover, setHover] = useState<CostDay | null>(null)
  const w = 640, h = 160, pad = 28
  const top = niceMax(days.map(dayTotal))
  const slot = (w - pad) / Math.max(days.length, 1)
  const bw = Math.max(slot - 3, 2)
  const y = (v: number) => (v / top) * (h - 18)
  return (
    <div className="relative">
      <div className="mb-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        {SERIES.map(s => (
          <span key={s.key} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />{s.label}</span>
        ))}
        <span>· paler = forecast</span>
      </div>
      <svg viewBox={`0 0 ${w} ${h + 18}`} className="w-full" role="img" aria-label="Cost per day this month, stacked by Aurora, EC2 node and everything else; the table below lists the same totals by service.">
        {[0, top / 2, top].map(v => (
          <g key={v}>
            <line x1={pad} x2={w} y1={h - y(v)} y2={h - y(v)} stroke="var(--border)" strokeDasharray={v ? "2 3" : undefined} />
            <text x={pad - 4} y={h - y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted-foreground)">${v % 1 ? v.toFixed(1) : v}</text>
          </g>
        ))}
        {days.map((d, i) => {
          const x = pad + i * slot + 1.5
          let base = h
          return (
            <g key={d.day} opacity={d.forecast ? 0.38 : 1} onMouseEnter={() => setHover(d)} onMouseLeave={() => setHover(null)}>
              {SERIES.map(s => {
                const v = d[s.key]
                const bh = y(v)
                if (bh <= 0) return null
                base -= bh
                // 2px surface gap between stacked segments
                return <rect key={s.key} x={x} y={base + 1} width={bw} height={Math.max(bh - 2, 1)} rx="1.5" fill={s.color} />
              })}
              <rect x={pad + i * slot} y={0} width={slot} height={h} fill="transparent" />
              {(i === 0 || (i + 1) % 7 === 1) && (
                <text x={x + bw / 2} y={h + 13} textAnchor="middle" fontSize="10" fill="var(--muted-foreground)">{shortDay(d.day)}</text>
              )}
            </g>
          )
        })}
      </svg>
      {hover && (
        <div className="pointer-events-none absolute right-0 top-0 rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-sm">
          <div className="font-medium">{shortDay(hover.day)}{hover.forecast ? " · forecast" : ""} · {money(dayTotal(hover))}</div>
          {SERIES.map(s => <div key={s.key} className="text-muted-foreground">{s.label} {money(hover[s.key])}</div>)}
        </div>
      )}
    </div>
  )
}

function Tile({ label, value, sub, warn }: { label: string; value: string; sub?: React.ReactNode; warn?: boolean }) {
  return (
    <div className="rounded-xl border bg-card px-3 py-2.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-0.5 text-xl font-semibold tabular-nums ${warn ? "text-[var(--dp-warn-text)]" : ""}`}>{value}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  )
}

function BudgetForm({ current, onSaved }: { current: number | null; onSaved: () => void }) {
  const { toast } = useToast()
  const [value, setValue] = useState(current != null ? String(current) : "")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const n = value.trim() === "" ? null : Number(value)
  const bad = n != null && (!Number.isFinite(n) || n <= 0)
  const save = async () => {
    setBusy(true); setError(null)
    try {
      await readJson(await fetch("/api/infra/budget", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ usd: n }) }))
      toast(n == null ? "Budget cleared" : `Budget set to ${money(n, 0)} a month`, "success")
      onSaved()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <section className="rounded-xl border bg-card p-4">
      <h2 className="mb-2 text-sm font-semibold">Monthly budget</h2>
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">$</span>
        <input inputMode="decimal" value={value} onChange={e => setValue(e.target.value)} aria-label="Monthly budget in US dollars"
               placeholder="none" className="h-8 w-28 rounded-md border bg-background px-2 text-sm" />
        <span className="text-xs text-muted-foreground">USD</span>
        <Button size="sm" disabled={busy || bad || n === current} onClick={() => void save()}>{busy ? "Saving…" : "Save"}</Button>
      </div>
      {bad && <p className="mt-1.5 text-xs text-destructive">A budget is a positive number of dollars.</p>}
      {error && <p className="mt-1.5 text-xs text-destructive">{error}</p>}
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">When the forecast passes it, Overview lists it under Needs attention.</p>
    </section>
  )
}

export function CostPanel() {
  const [data, setData] = useState<CostReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (refresh = false) => {
    setLoading(true); setError(null)
    try {
      setData(await readJson<CostReport>(await fetch(`/api/infra/cost${refresh ? "?refresh=true" : ""}`)))
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setLoading(false) }
  }, [])
  useEffect(() => { const t = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(t) }, [load])

  const status = sourceStatus({ loading: loading && !data, error, empty: false, hasData: !!data })
  const start = data ? new Date(data.period.start) : null
  const monthName = start?.toLocaleDateString("en-US", { month: "long", timeZone: "UTC" })
  const ai = data?.services.find(s => s.key === "bedrock")
  const aurora = data?.services.find(s => s.key === "aurora")
  const sv = data?.savings
  const missing = data ? missingSentence(data.missing) : null

  return (
    <div className="flex flex-col" style={{ minHeight: "calc(100vh - 56px)" }}>
      <div className="flex h-11 shrink-0 items-center gap-1.5 border-b bg-background px-3">
        <InfraTabs active="cost" />
        <div className="ml-auto flex items-center gap-3">
          {data && start && (
            <span className="hidden text-xs text-muted-foreground md:inline">
              {monthName} 1–{data.period.days_elapsed} · us-east-1 list prices · read {new Date(data.read_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" disabled={loading} onClick={() => void load(true)}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span className="hidden md:inline">Refresh</span>
          </Button>
        </div>
      </div>

      <div className="p-4">
        <SourceState status={status} what="AWS cost" error={error} onRetry={() => void load(true)}>
          {data && (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
              <div className="min-w-0 space-y-4">
                {missing && <RailAttention title="Some usage could not be read">{missing} Those services show $0 until then.</RailAttention>}
                <div className="rounded-xl border bg-muted/30 px-3 py-2 text-xs leading-relaxed">
                  {data.actual.active
                    ? <><span className="font-semibold">Actual</span> — Cost Explorer reports {money(data.actual.total)} billed this month for resources tagged Project. The estimate below shows where it comes from.</>
                    : <><span className="font-semibold">Estimated</span> from what each resource used (CloudWatch) times AWS list and Spot prices. Actual billed amounts appear here once the Project cost tag is active.</>}
                </div>

                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  <Tile label="Month to date" value={money(data.actual.active ? data.actual.total : data.total.mtd)}
                        sub={`${data.period.days_elapsed} days · ${data.actual.active ? "billed" : "est."}`} />
                  <Tile label={`${monthName} forecast`} value={money(data.total.forecast)} sub="at the current schedule" />
                  <Tile label="Budget" value={data.budget ? `${data.budget.pct}%` : "Not set"} warn={data.budget?.over}
                        sub={data.budget ? `forecast of ${money(data.budget.budget, 0)} / month` : "set one on the right"} />
                  <Tile label="AI models (in the total)" value={money(ai?.mtd)} sub={<Link className="text-primary hover:underline" href="/ai?tab=spend">by caller in AI Gateway</Link>} />
                </div>

                <section className="rounded-xl border bg-card p-4">
                  <h2 className="mb-2 text-sm font-semibold">Cost per day</h2>
                  <DailyChart days={data.daily} />
                </section>

                <section className="overflow-hidden rounded-xl border bg-card">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 font-medium">Service</th>
                        <th className="px-3 py-2 text-right font-medium">Month to date</th>
                        <th className="px-3 py-2 text-right font-medium">Forecast</th>
                        <th className="hidden px-3 py-2 font-medium md:table-cell">How it is measured</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.services.map(s => (
                        <tr key={s.key} className="border-t">
                          <td className="px-3 py-2">{s.label}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{money(s.mtd)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{money(s.forecast)}</td>
                          <td className="hidden px-3 py-2 text-xs text-muted-foreground md:table-cell">{s.how}</td>
                        </tr>
                      ))}
                      <tr className="border-t font-semibold">
                        <td className="px-3 py-2">Total</td>
                        <td className="px-3 py-2 text-right tabular-nums">{money(data.total.mtd)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{money(data.total.forecast)}</td>
                        <td className="hidden md:table-cell" />
                      </tr>
                    </tbody>
                  </table>
                  <p className="border-t px-3 py-2 text-xs text-muted-foreground">Not counted: {data.not_counted.join(", ")}. Actual billing includes them.</p>
                </section>

                {data.actual.active && data.actual.services && (
                  <section className="overflow-hidden rounded-xl border bg-card">
                    <h2 className="px-3 py-2.5 text-sm font-semibold">Billed by Cost Explorer</h2>
                    <table className="w-full text-sm"><tbody>
                      {data.actual.services.map(s => (
                        <tr key={s.label} className="border-t"><td className="px-3 py-2">{s.label}</td><td className="px-3 py-2 text-right tabular-nums">{money(s.mtd)}</td></tr>
                      ))}
                    </tbody></table>
                  </section>
                )}
              </div>

              <div className="space-y-4">
                <section className="rounded-xl border bg-card p-4 text-xs leading-relaxed">
                  <h2 className="mb-2 text-sm font-semibold">Where it can go down</h2>
                  <ul className="space-y-2.5">
                    {aurora && sv?.aurora_min_acu != null && sv.aurora_min_acu > 0 && (
                      <li>
                        Aurora is {share(aurora.forecast, data.total.forecast)}% of the bill. A {sv.aurora_min_acu} ACU minimum keeps it billing about {money(sv.aurora_idle_floor, 0)} a month even idle, every night and weekend.{" "}
                        <Link className="text-primary hover:underline" href="/services?tab=aws">Aurora capacity</Link>
                      </li>
                    )}
                    {sv?.spot_vs_on_demand != null && (
                      <li>Spot saves about {money(sv.spot_vs_on_demand, 0)} a month against on-demand ({money(sv.on_demand_hourly, 4)}/h) at this schedule.</li>
                    )}
                    {sv?.schedule_saves != null && sv.hours_per_week < 168 && (
                      <li>
                        The schedule saves about {money(sv.schedule_saves, 0)} a month: {sv.hours_per_week} of 168 hours a week.{" "}
                        <Link className="text-primary hover:underline" href="/services?tab=aws">When the node runs</Link>
                      </li>
                    )}
                    {sv?.hours_per_week === 168 && <li>The node runs all week. A working-hours schedule would cut its compute cost by roughly two thirds.</li>}
                  </ul>
                </section>
                <BudgetForm key={String(data.budget_usd)} current={data.budget_usd} onSaved={() => void load()} />
                {!data.actual.active && (
                  <section className="rounded-xl border border-dashed p-4 text-xs leading-relaxed">
                    <h2 className="mb-2 text-sm font-semibold">Turn on actual costs</h2>
                    <ol className="list-decimal space-y-1.5 pl-4 text-muted-foreground">
                      <li>Terraform tags every resource Project=datapond (provider default tags).</li>
                      <li>In the billing account, activate the Project cost allocation tag. It takes up to 24 h.</li>
                      <li>This page then reads Cost Explorer once every 6 hours ($0.01 a read).</li>
                    </ol>
                    {data.actual.blocked === "payer"
                      ? <p className="mt-2 text-foreground">This account is a member of an AWS organization, and its payer account does not share Cost Explorer with member accounts yet. Whoever owns billing turns that on in the payer account (Billing and Cost Management › Cost Management preferences › member account access), along with step 2.</p>
                      : <p className="mt-2 text-muted-foreground">On an MSP or organization account, step 2 is done by whoever owns billing.</p>}
                  </section>
                )}
              </div>
            </div>
          )}
        </SourceState>
      </div>
    </div>
  )
}
