"use client"

import { useCallback, useEffect, useState } from "react"
import { RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { SourceState } from "@/components/ui/source-state"
import { RailAttention } from "@/components/ui/explain-rail"
import { InfraTabs } from "@/components/infra/infra-tabs"
import { AuroraCapacityCard, ScheduleCard } from "@/components/infra/aws-controls"
import { readJson, sourceStatus } from "@/lib/source-state"
import { acu, missingSentence, money, stopsToday, type AwsSnapshot } from "@/lib/aws-infra"

const fmtTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"

function Spark({ points }: { points: { at: string; pct: number }[] }) {
  if (points.length < 2) return <div className="h-12 text-xs text-muted-foreground">No CPU data in the last 24 h.</div>
  const w = 260, h = 48
  const t0 = new Date(points[0].at).getTime(), t1 = new Date(points[points.length - 1].at).getTime()
  const x = (at: string) => ((new Date(at).getTime() - t0) / Math.max(t1 - t0, 1)) * w
  const y = (p: number) => h - (Math.min(p, 100) / 100) * h
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(p.at).toFixed(1)},${y(p.pct).toFixed(1)}`).join(" ")
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-12 w-full" role="img"
         aria-label={`CPU over the last 24 hours, ${points.length} hourly points`}>
      <line x1="0" x2={w} y1={h - 0.5} y2={h - 0.5} stroke="var(--border)" />
      <path d={d} fill="none" stroke="var(--series-1)" strokeWidth="2" strokeLinejoin="round" />
      {points.map(p => (
        <circle key={p.at} cx={x(p.at)} cy={y(p.pct)} r="6" fill="transparent">
          <title>{`${fmtTime(p.at)} · ${p.pct}%`}</title>
        </circle>
      ))}
    </svg>
  )
}

function State({ ok, children }: { ok: boolean | null; children: React.ReactNode }) {
  const cls = ok == null ? "text-muted-foreground" : ok ? "text-[var(--dp-good-text)]" : "text-[var(--dp-warn-text)]"
  return <span className={`font-medium ${cls}`}>{children}</span>
}

export function AwsPanel() {
  const [data, setData] = useState<AwsSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (refresh = false) => {
    setLoading(true); setError(null)
    try {
      setData(await readJson<AwsSnapshot>(await fetch(`/api/infra/aws${refresh ? "?refresh=true" : ""}`)))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setLoading(false) }
  }, [])
  useEffect(() => { const t = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(t) }, [load])

  const status = sourceStatus({ loading: loading && !data, error, empty: false, hasData: !!data })
  const n = data?.node, a = data?.aurora
  const inAlarm = data?.alarms.filter(x => x.state === "ALARM").length ?? 0
  const stops = data ? stopsToday(data.schedule) : null
  const missing = data ? missingSentence(data.missing) : null

  return (
    <div className="flex flex-col" style={{ minHeight: "calc(100vh - 56px)" }}>
      <div className="flex h-11 shrink-0 items-center gap-1.5 border-b bg-background px-3">
        <InfraTabs active="aws" />
        <div className="ml-auto flex items-center gap-3">
          {data && (
            <span className="hidden text-xs text-muted-foreground md:inline">
              {data.account ? `Account ${data.account} · ` : ""}{data.region} · read {fmtTime(data.read_at)}
            </span>
          )}
          <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" disabled={loading} onClick={() => void load(true)}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span className="hidden md:inline">Refresh</span>
          </Button>
        </div>
      </div>

      <div className="p-4">
      <SourceState status={status} what="AWS resources" error={error} onRetry={() => void load(true)}>
        {data && n && a && (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="min-w-0 space-y-4">
              {missing && <RailAttention title="Some AWS reads are not allowed yet">{missing}</RailAttention>}

              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Tile label="Alarms" value={inAlarm ? `${inAlarm} in alarm` : "None in alarm"} sub={`of ${data.alarms.length}`} warn={inAlarm > 0} />
                <Tile label="Node" value={n.state ?? "—"} sub={stops ? `stops today ${stops}` : data.schedule.enabled === false ? "runs 24/7" : n.lifecycle ?? ""} />
                <Tile label="Aurora" value={a.acu_now != null ? `${acu(a.acu_now)} ACU` : a.status ?? "—"} sub={a.min_acu != null ? `range ${a.min_acu}–${a.max_acu}` : ""} />
                <Tile label="Data bucket" value={data.s3.size_gb != null ? `${(data.s3.size_gb * 1000).toFixed(1)} MB` : "—"}
                      sub={data.s3.objects != null ? `${data.s3.objects.toLocaleString("en-US")} objects` : "measured daily by S3"} />
              </div>

              <section className="overflow-hidden rounded-xl border bg-card">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                    <tr><th className="px-3 py-2 font-medium">Resource</th><th className="px-3 py-2 font-medium">State</th><th className="px-3 py-2 font-medium">Last 24 h</th></tr>
                  </thead>
                  <tbody>
                    <tr className="border-t align-top">
                      <td className="px-3 py-2.5"><div className="font-medium">EC2 node</div><div className="font-mono text-xs text-muted-foreground">{n.instance_id} · {n.instance_type}{n.lifecycle === "spot" ? " Spot" : ""}</div></td>
                      <td className="px-3 py-2.5"><State ok={n.state ? n.state === "running" : null}>{n.state ?? "—"}</State>{n.launched_at && <div className="text-xs text-muted-foreground">since {fmtTime(n.launched_at)}</div>}</td>
                      <td className="px-3 py-2.5 text-xs">CPU {n.cpu_avg_24h ?? "—"}% avg · {n.cpu_peak_24h ?? "—"}% peak<div className="text-muted-foreground">volume {n.volume_gb ?? "—"} GB {n.volume_type ?? ""}</div></td>
                    </tr>
                    <tr className="border-t align-top">
                      <td className="px-3 py-2.5"><div className="font-medium">Aurora PostgreSQL</div><div className="font-mono text-xs text-muted-foreground">{a.cluster} · Serverless v2{a.engine_version ? ` · ${a.engine_version}` : ""}</div></td>
                      <td className="px-3 py-2.5"><State ok={a.status ? a.status === "available" : null}>{a.status ?? "—"}</State></td>
                      <td className="px-3 py-2.5 text-xs">{acu(a.acu_now)} ACU now · {acu(a.acu_peak_24h)} peak<div className="text-muted-foreground">{a.connections_peak_24h ?? "—"} connections peak · {a.storage_gb ?? "—"} GB</div></td>
                    </tr>
                    <tr className="border-t align-top">
                      <td className="px-3 py-2.5"><div className="font-medium">S3 data bucket</div><div className="font-mono text-xs text-muted-foreground">{data.s3.bucket ?? "—"}</div></td>
                      <td className="px-3 py-2.5"><State ok={data.s3.size_gb != null ? true : null}>{data.s3.size_gb != null ? "OK" : "—"}</State></td>
                      <td className="px-3 py-2.5 text-xs">{data.s3.size_gb != null ? `${(data.s3.size_gb * 1000).toFixed(1)} MB` : "—"}<div className="text-muted-foreground">size is measured once a day by S3</div></td>
                    </tr>
                  </tbody>
                </table>
              </section>

              <section className="overflow-hidden rounded-xl border bg-card">
                <div className="flex items-center justify-between px-3 py-2.5">
                  <h2 className="text-sm font-semibold">Alarms</h2>
                  {data.dashboards[0] && (
                    <a className="text-xs text-primary hover:underline" target="_blank" rel="noreferrer"
                       href={`https://${data.region}.console.aws.amazon.com/cloudwatch/home?region=${data.region}#dashboards/dashboard/${encodeURIComponent(data.dashboards[0])}`}>
                      Open CloudWatch dashboard
                    </a>
                  )}
                </div>
                {data.alarms.length === 0
                  ? <p className="border-t px-3 py-3 text-xs text-muted-foreground">No alarms named {data.missing.includes("cloudwatch:DescribeAlarms") ? "(not readable yet)" : "for this deployment"}.</p>
                  : (
                    <table className="w-full text-sm">
                      <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                        <tr><th className="px-3 py-2 font-medium">Alarm</th><th className="px-3 py-2 font-medium">State</th><th className="px-3 py-2 font-medium">Watches</th><th className="px-3 py-2 font-medium">Last change</th></tr>
                      </thead>
                      <tbody>
                        {data.alarms.map(al => (
                          <tr key={al.name} className="border-t">
                            <td className="px-3 py-2 font-mono text-xs">{al.name}</td>
                            <td className="px-3 py-2"><State ok={al.state === "OK" ? true : al.state === "ALARM" ? false : null}>{al.state === "INSUFFICIENT_DATA" ? "No data" : al.state}</State></td>
                            <td className="px-3 py-2 text-xs">{al.watches}</td>
                            <td className="px-3 py-2 text-xs text-muted-foreground">{fmtTime(al.changed_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
              </section>
            </div>

            <div className="space-y-4">
              <AuroraCapacityCard key={`${a.min_acu}-${a.max_acu}`} aurora={a} onSaved={() => void load(true)} />
              <section className="rounded-xl border bg-card p-4">
                <div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-semibold">EC2 node</h2><State ok={n.state ? n.state === "running" : null}>{n.state ?? "—"}</State></div>
                <div className="text-xs text-muted-foreground">CPU, last 24 h</div>
                <Spark points={n.cpu_24h ?? []} />
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                  <dt className="text-muted-foreground">Type</dt><dd>{n.instance_type ?? "—"} · {n.lifecycle === "spot" ? "Spot" : "On-demand"}</dd>
                  {n.lifecycle === "spot" && <><dt className="text-muted-foreground">Spot price</dt><dd>{money(n.spot_price_now ?? n.hourly_price, 4)}/h{n.on_demand_hourly ? ` (on-demand ${money(n.on_demand_hourly, 4)})` : ""}</dd></>}
                  <dt className="text-muted-foreground">Zone</dt><dd>{n.zone ?? "—"}</dd>
                  <dt className="text-muted-foreground">Volume</dt><dd>{n.volume_gb ?? "—"} GB {n.volume_type ?? ""}</dd>
                </dl>
              </section>
              <ScheduleCard key={`${data.schedule.start_expression}-${data.schedule.stop_expression}-${data.schedule.enabled}`}
                            schedule={data.schedule} hourly={n.hourly_price} onSaved={() => void load(true)} />
              <section className="rounded-xl border border-dashed p-4 text-xs leading-relaxed text-muted-foreground">
                <div className="mb-1 font-semibold text-foreground">Not here, on purpose</div>
                Stop now, change instance type, delete or resize volumes. Stopping takes this console offline with it; the rest replace the node. Those stay in Terraform.
              </section>
            </div>
          </div>
        )}
      </SourceState>
      </div>
    </div>
  )
}

function Tile({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div className="rounded-xl border bg-card px-3 py-2.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-0.5 text-base font-semibold first-letter:uppercase ${warn ? "text-[var(--dp-warn-text)]" : ""}`}>{value}</div>
      {sub && <div className="truncate text-xs text-muted-foreground">{sub}</div>}
    </div>
  )
}
