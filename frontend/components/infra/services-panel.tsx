"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { ExternalLink, RefreshCw } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { InfraTabs } from "@/components/infra/infra-tabs"
import { useCapabilities, type Capabilities } from "@/lib/capabilities"
import { useConfirm } from "@/lib/confirm"
import { usePermissions } from "@/lib/permissions"
import { useToast } from "@/lib/toast"
import { responseErrorMessage } from "@/lib/auth"
import { formatUsage } from "@/lib/infra-usage"
import { healthCounts, healthDetail, healthDotClass, parseCatalogHealth, type CatalogHealth } from "@/lib/catalog-health"

interface Service {
  name: string
  status: "healthy" | "unhealthy" | "unknown" | "managed"
  url?: string
  description?: string
  ready?: number | null
  replicas?: number | null
  cpu_m?: number | null
  memory_mi?: number | null
}
interface Pod { name: string; phase: string; ready: boolean; restarts: number; age: string; image?: string | null; cpu_m?: number | null; memory_mi?: number | null }

// Internal K8s DNS → browser-accessible ingress path
const EXTERNAL_URLS: Record<string, string> = {
  jupyterlab: "/jupyter", mlflow: "/mlflow", trino: "/api/trino", openmetadata: "/openmetadata",
  minio: "/storage", airflow: "/airflow",
}
// MLflow has no authentication, so a deployment can run it with its UI kept off the
// ingress; then /mlflow is not there to open. mlflow_ui says whether it is.
function externalUrl(name: string, caps: Capabilities): string | null {
  if (name === "mlflow" && caps.mlflow_ui !== true) return null
  return EXTERNAL_URLS[name] ?? null
}

const STATE: Record<Service["status"], { label: string; cls: string }> = {
  healthy: { label: "Healthy", cls: "text-[var(--dp-good-text)] font-semibold" },
  unhealthy: { label: "Unhealthy", cls: "text-destructive font-semibold" },
  unknown: { label: "No pods", cls: "text-[var(--dp-warn-text)] font-semibold" },
  managed: { label: "Configured", cls: "text-muted-foreground" },
}

type Filter = "all" | "issues" | "managed"

export function ServicesPanel() {
  const caps = useCapabilities()
  const [services, setServices] = useState<Service[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState<Filter>("all")
  const [selected, setSelected] = useState<string | null>(null)

  const fetchServices = useCallback(async () => {
    try {
      setLoading(true)
      const res = await fetch("/api/services")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setServices(Array.isArray(data) ? data : []); setError(null); setCheckedAt(new Date())
    } catch (e) {
      // Don't render a stale/empty list as if everything is fine — surface it.
      setError(e instanceof Error ? e.message : "Failed to load services")
    } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => void fetchServices(), 0)
    const interval = window.setInterval(() => void fetchServices(), 30000)
    return () => { window.clearTimeout(initial); window.clearInterval(interval) }
  }, [fetchServices])

  // Data catalogs: one status per enabled catalog the caller may use. Only where the
  // catalog capability is on; a failed read hides the group rather than the page.
  const catalogsOn = caps.catalog === true
  const [catalogHealth, setCatalogHealth] = useState<CatalogHealth[]>([])
  const fetchCatalogHealth = useCallback(async () => {
    if (!catalogsOn) return
    try {
      const r = await fetch("/api/catalogs/health")
      setCatalogHealth(r.ok ? parseCatalogHealth(await r.json()) : [])
    } catch { setCatalogHealth([]) }
  }, [catalogsOn])
  useEffect(() => {
    if (!catalogsOn) return
    const initial = window.setTimeout(() => void fetchCatalogHealth(), 0)
    const interval = window.setInterval(() => void fetchCatalogHealth(), 30000)
    return () => { window.clearTimeout(initial); window.clearInterval(interval) }
  }, [catalogsOn, fetchCatalogHealth])

  const workloads = services.filter(s => s.status !== "managed")
  const adapters = services.filter(s => s.status === "managed")
  const issues = workloads.filter(s => s.status !== "healthy")
  const healthy = workloads.length - issues.length
  const q = search.trim().toLowerCase()
  const shown = (filter === "issues" ? issues : filter === "managed" ? adapters : services)
    .filter(s => !q || s.name.toLowerCase().includes(q) || (s.description ?? "").toLowerCase().includes(q))
  const current = services.find(s => s.name === selected) ?? null

  return (
    <div className="flex flex-col" style={{ minHeight: "calc(100vh - 56px)" }}>
      <div className="flex h-11 shrink-0 items-center gap-1.5 border-b bg-background px-3">
        <InfraTabs active="services" />
        <div className="ml-auto flex items-center gap-3">
          {checkedAt && (
            <span className="hidden text-xs text-muted-foreground md:inline">
              {healthy} of {workloads.length} healthy · checked {checkedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" disabled={loading}
                  onClick={() => { void fetchServices(); void fetchCatalogHealth() }}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span className="hidden md:inline">Refresh</span>
          </Button>
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1400px] flex-1 space-y-5 p-8 pt-6">
        <p className="text-sm text-muted-foreground">The workloads this deployment runs, and the external adapters it is configured to use.</p>
        {error && services.length > 0 && (
          <RailAttention title="Showing the last known state">Refresh failed ({error}).</RailAttention>
        )}
        <div className="flex flex-wrap items-start gap-5">
          <section className="min-w-0 flex-[3_1_560px] overflow-hidden rounded-xl border bg-card">
            <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
              <Input aria-label="Search services" placeholder="Search services" value={search} onChange={e => setSearch(e.target.value)} className="h-8 w-52" />
              <div role="group" aria-label="Filter services" className="flex gap-1">
                {([["all", "All", services.length], ["issues", "Issues", issues.length], ["managed", "Adapters", adapters.length]] as const).map(([k, label, n]) => (
                  <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}
                          className={`rounded-md border px-2.5 py-1 text-xs font-medium ${filter === k ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted"}`}>
                    {label} <span className="tabular-nums">{n}</span>
                  </button>
                ))}
              </div>
            </div>
            {loading && services.length === 0 ? (
              <div className="space-y-2 p-4">{[0, 1, 2, 3, 4].map(i => <Skeleton key={i} className="h-9 w-full" />)}</div>
            ) : error && services.length === 0 ? (
              <div className="p-6 text-sm"><p className="font-medium text-destructive">Could not load services</p><p className="text-muted-foreground">{error}</p>
                <Button size="sm" variant="outline" className="mt-2" onClick={() => void fetchServices()}>Retry</Button></div>
            ) : shown.length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">{q || filter !== "all" ? (filter === "issues" && !q ? "No issues: every workload is healthy." : "No services match.") : "No services are reporting yet."}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-sm">
                  <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                    <tr><th scope="col" className="px-4 py-2 font-medium">Service</th><th scope="col" className="px-3 py-2 font-medium">State</th><th scope="col" className="px-3 py-2 font-medium">Ready</th><th scope="col" className="px-3 py-2 font-medium">CPU · Memory</th></tr>
                  </thead>
                  <tbody>
                    {shown.map(s => {
                      const on = s.name === selected
                      const st = STATE[s.status] ?? STATE.unknown
                      return (
                        <tr key={s.name} className={`border-t ${on ? "bg-primary/10" : "hover:bg-muted/40"}`}>
                          <td className="px-4 py-2">
                            <button aria-pressed={on} className="text-left" onClick={() => setSelected(on ? null : s.name)}>
                              <span className="font-semibold">{s.name}</span>
                              <span className="block text-xs text-muted-foreground">{s.description ?? "DataPond service"}</span>
                            </button>
                          </td>
                          <td className={`px-3 py-2 ${st.cls}`}>{st.label}</td>
                          <td className="px-3 py-2 tabular-nums">{s.status === "managed" ? <span className="text-muted-foreground">—</span> : s.replicas != null ? `${s.ready ?? 0} / ${s.replicas}` : "—"}</td>
                          <td className="px-3 py-2 tabular-nums text-muted-foreground">{s.status === "managed" ? "—" : formatUsage(s.cpu_m, s.memory_mi)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          {current ? <ServiceRail key={current.name} service={current} caps={caps} onChanged={() => void fetchServices()} /> : (
            <ExplainRail label="About infrastructure">
              <RailSection title="Pick a service">See its pods, image and usage, open its logs, restart it or change its replicas.</RailSection>
              <RailSection title="States">
                <ul className="space-y-0.5 text-xs">
                  <li><strong className="text-foreground">Healthy</strong>: every serving pod is running and ready.</li>
                  <li><strong className="text-foreground">Unhealthy</strong>: at least one serving pod is not ready.</li>
                  <li><strong className="text-foreground">No pods</strong>: nothing is running for it.</li>
                  <li><strong className="text-foreground">Configured</strong>: an external adapter (Aurora, S3, Bedrock, Glue). Configured means set up, not checked: verify it in the provider&apos;s console.</li>
                </ul>
              </RailSection>
              <RailSection title="CPU and memory">From metrics-server, summed over a service&apos;s pods. &ldquo;—&rdquo; when it is not installed.</RailSection>
            </ExplainRail>
          )}
        </div>

        {catalogsOn && catalogHealth.length > 0 && (
          <section aria-labelledby="data-catalogs-heading" className="space-y-2">
            <div className="flex items-baseline gap-2">
              <h2 id="data-catalogs-heading" className="text-sm font-semibold">Data catalogs</h2>
              <span className="text-xs text-muted-foreground">{healthCounts(catalogHealth).reachable} of {catalogHealth.length} reachable · checked at most once a minute</span>
            </div>
            <ul className="grid gap-2 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {catalogHealth.map(c => (
                <li key={c.name} className="flex items-start gap-2.5 rounded-md border bg-card px-3 py-2">
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${healthDotClass(c)}`} role="img" aria-label={c.status === "reachable" ? "Reachable" : "Error"} />
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-sm font-medium"><span className="truncate">{c.name}</span>{c.is_default && <span className="text-xs font-normal text-muted-foreground">default</span>}</div>
                    <p className={`break-words text-xs ${c.status === "reachable" ? "text-muted-foreground" : "text-[var(--dp-bad)]"}`} title={healthDetail(c)}>{healthDetail(c)}</p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}

function ServiceRail({ service, caps, onChanged }: { service: Service; caps: Capabilities; onChanged: () => void }) {
  const { role } = usePermissions()
  // Restart, scale and pod delete are require_admin on the backend.
  const isAdmin = role === "admin"
  const confirm = useConfirm()
  const { toast } = useToast()
  const managed = service.status === "managed"
  const [pods, setPods] = useState<Pod[] | null>(null)
  const [replicas, setReplicas] = useState(service.replicas ?? 1)
  const [busy, setBusy] = useState(false)

  const loadPods = useCallback(async () => {
    if (managed) return
    try {
      const r = await fetch(`/api/services/${encodeURIComponent(service.name)}/pods`)
      setPods(r.ok ? await r.json() : [])
    } catch { setPods([]) }
  }, [managed, service.name])
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void loadPods() }, [loadPods])

  const restart = async () => {
    if (!(await confirm({ title: `Restart ${service.name}`, message: "Pods are replaced one at a time. With one replica the service is briefly unavailable.", confirmText: "Restart", destructive: true }))) return
    setBusy(true)
    try {
      const r = await fetch(`/api/services/${encodeURIComponent(service.name)}/restart`, { method: "POST" })
      if (!r.ok) throw new Error(await responseErrorMessage(r, "Restart failed"))
      toast(`Restart of ${service.name} started`, "success")
      window.setTimeout(() => { void loadPods(); onChanged() }, 3000)
    } catch (e) { toast(e instanceof Error ? e.message : "Restart failed", "error") }
    finally { setBusy(false) }
  }
  const scale = async () => {
    const zero = replicas === 0
    if (!(await confirm({
      title: `Scale ${service.name}`,
      message: zero ? "Set replicas to 0? This takes the service offline." : `Run ${replicas} replica${replicas === 1 ? "" : "s"} of ${service.name}?`,
      confirmText: "Scale", destructive: zero,
    }))) return
    setBusy(true)
    try {
      const r = await fetch(`/api/services/${encodeURIComponent(service.name)}/scale`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ replicas }),
      })
      if (!r.ok) throw new Error(await responseErrorMessage(r, "Scale failed"))
      toast(`${service.name} scaled to ${replicas}`, "success")
      window.setTimeout(() => { void loadPods(); onChanged() }, 3000)
    } catch (e) { toast(e instanceof Error ? e.message : "Scale failed", "error") }
    finally { setBusy(false) }
  }

  const st = STATE[service.status] ?? STATE.unknown
  const url = externalUrl(service.name, caps)
  const image = pods?.find(p => p.image)?.image

  return (
    <ExplainRail label={`${service.name} details`}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-foreground">{service.name}</h3>
        <span className={st.cls}>{st.label}</span>
      </div>
      {managed ? (
        <RailSection title="Configured adapter">
          It is set up in this deployment profile. DataPond does not run a live health check on it, and pods, restarts and replicas do not apply. Check it in the provider&apos;s console.
        </RailSection>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <Link href={`/services/${encodeURIComponent(service.name)}`} className={buttonVariants({ size: "sm", variant: "outline" })}>Logs and events</Link>
            {url && <a href={url} target="_blank" rel="noreferrer" className={buttonVariants({ size: "sm", variant: "outline" })}>Open <ExternalLink className="ml-1 h-3 w-3" /></a>}
            {isAdmin && <Button size="sm" variant="outline" disabled={busy} onClick={() => void restart()}>Restart…</Button>}
          </div>
          {isAdmin && (
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-sm font-semibold text-foreground">Replicas
                <Input type="number" min={0} max={10} value={replicas} className="h-8 w-20" onChange={e => setReplicas(Math.max(0, Math.min(10, Number(e.target.value) || 0)))} />
              </label>
              <Button size="sm" variant="outline" disabled={busy || replicas === service.replicas} onClick={() => void scale()}>Scale…</Button>
              <span className="pb-1.5 text-xs">0 takes it offline (asks first).</span>
            </div>
          )}
          <RailSection title="Pods">
            {pods === null ? <Skeleton className="h-12 w-full" /> : pods.length === 0 ? <p>No pods are running.</p> : (
              <table className="w-full text-xs text-foreground">
                <tbody>
                  {pods.map(p => (
                    <tr key={p.name} className="border-t first:border-t-0">
                      <td className="max-w-[9rem] truncate py-1.5 pr-2 font-mono" title={p.name}>{p.name}</td>
                      <td className="py-1.5 pr-2 tabular-nums">{formatUsage(p.cpu_m, p.memory_mi)}</td>
                      <td className={`py-1.5 text-right ${p.ready ? "text-muted-foreground" : "text-destructive"}`}>{p.ready ? `${p.restarts} restart${p.restarts === 1 ? "" : "s"}` : p.phase}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </RailSection>
          {image && <RailSection title="Image"><span className="break-all font-mono text-xs">{image}</span></RailSection>}
          {!isAdmin && <p className="text-xs">Restarting and scaling need an administrator.</p>}
        </>
      )}
    </ExplainRail>
  )
}
