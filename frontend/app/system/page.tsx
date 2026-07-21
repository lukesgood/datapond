"use client"

import { useCallback, useEffect, useState, type ComponentType } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorBox } from "@/components/ui/error-box"
import {
  Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Server, Cpu, MemoryStick, HardDrive, Boxes, RefreshCw, Layers, Gauge, Cloud } from "lucide-react"

interface CompareRow {
  resource: string; unit: string; required: number; recommended: number
  actual: number | null; status: "ok" | "warning" | "insufficient" | "unknown"
}
interface SystemInfo {
  node: {
    name?: string; os?: string; kernel?: string; arch?: string
    container_runtime?: string; kubelet?: string
    cpu_cores?: number; memory_gb?: number; ephemeral_storage_gb?: number; max_pods?: number
    allocatable_cpu_cores?: number; allocatable_memory_gb?: number
    ready?: boolean; memory_pressure?: boolean; disk_pressure?: boolean
  }
  cluster: { kubernetes?: string; pods_running?: number; pods_total?: number }
  components: { name: string; kind: string; image: string; replicas: string
    cpu_request?: string; mem_request?: string; cpu_limit?: string; mem_limit?: string }[]
  storage: { name: string; capacity: string; status: string; storage_class?: string }[]
  usage: { cpu_percent?: number | null; memory_percent?: number | null }
  requirements: { cpu_cores?: number; memory_gb?: number; disk_gb?: number }
  recommended: { cpu_cores?: number; memory_gb?: number; disk_gb?: number }
  comparison: CompareRow[]
  cloud?: {
    provider?: string; name?: string | null; instance_id?: string; instance_type?: string
    lifecycle?: string | null; ami_id?: string; region?: string; availability_zone?: string
    private_ip?: string | null; public_ip?: string | null; private_hostname?: string | null
    security_groups?: string[]
  } | null
}

const CMP_STATUS: Record<string, { label: string; cls: string }> = {
  ok:           { label: "Meets recommended", cls: "bg-[var(--dp-good)]/10 text-[var(--dp-good)] border-[var(--dp-good)]/30" },
  warning:      { label: "Below recommended", cls: "bg-[var(--dp-warn)]/10 text-[var(--dp-warn)] border-[var(--dp-warn)]/30" },
  insufficient: { label: "Below minimum", cls: "bg-destructive/10 text-destructive border-destructive/30" },
  unknown:      { label: "Unknown", cls: "bg-muted text-muted-foreground border-transparent" },
}

function Meter({ label, pct, Icon }: { label: string; pct?: number | null; Icon: ComponentType<{ className?: string }> }) {
  const v = typeof pct === "number" ? pct : null
  const color = v == null ? "bg-muted-foreground/30" : v > 85 ? "bg-destructive" : v > 60 ? "bg-[var(--dp-warn)]" : "bg-[var(--dp-good)]"
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="flex items-center gap-1.5 text-muted-foreground"><Icon className="h-3.5 w-3.5" />{label}</span>
        <span className="font-mono font-medium">{v == null ? "—" : `${v}%`}</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${v ?? 0}%` }} />
      </div>
    </div>
  )
}

function Spec({ label, value }: { label: string; value?: string | number }) {
  return (
    <div className="flex justify-between gap-3 py-1.5 border-b last:border-0 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-right truncate">{value ?? "—"}</span>
    </div>
  )
}

export default function SystemPage() {
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch("/api/system/info")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setInfo(await res.json())
    } catch (requestError) {
      setInfo(null)
      setError(requestError instanceof Error ? `Failed to load system information (${requestError.message})` : "Failed to load system information")
    } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0)
    const interval = window.setInterval(() => void load(), 15000)
    return () => { window.clearTimeout(initial); window.clearInterval(interval) }
  }, [load])

  const n = info?.node ?? {}
  const c = info?.cluster ?? {}

  return (
    <div className="p-6 space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/dashboard">Overview</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>System</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2"><Server className="h-6 w-6" />System</h1>
          <p className="text-muted-foreground text-sm">Server system information · configuration specs</p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-1.5 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Refreshing" : "Refresh"}
        </Button>
      </div>

      {error ? (
        <div role="alert" aria-live="polite"><ErrorBox msg={error} action={<Button size="sm" variant="outline" onClick={load}>Retry</Button>} /></div>
      ) : loading && !info ? (
        <div className="grid gap-4 md:grid-cols-2" aria-busy="true"><Skeleton className="h-48" /><Skeleton className="h-48" /></div>
      ) : info ? (
      <>
        <div className="grid gap-4 md:grid-cols-2">
          {/* Node specs */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2"><Cpu className="h-4 w-4" />Server Specs</CardTitle>
              <CardDescription>{n.name ?? "node"}</CardDescription>
            </CardHeader>
            <CardContent>
              <Spec label="CPU" value={n.cpu_cores ? `${n.cpu_cores} vCPU` : undefined} />
              <Spec label="Memory" value={n.memory_gb ? `${n.memory_gb} GB` : undefined} />
              <Spec label="Disk" value={n.ephemeral_storage_gb ? `${n.ephemeral_storage_gb} GB` : undefined} />
              <Spec label="Allocatable CPU/Memory" value={n.allocatable_cpu_cores != null ? `${n.allocatable_cpu_cores} vCPU / ${n.allocatable_memory_gb} GB` : undefined} />
              <Spec label="Architecture" value={n.arch} />
              <Spec label="OS" value={n.os} />
              <Spec label="Kernel" value={n.kernel} />
              <Spec label="Container Runtime" value={n.container_runtime} />
              <Spec label="Kubernetes" value={c.kubernetes ?? n.kubelet} />
              <Spec label="Max Pods" value={n.max_pods} />
              <div className="flex justify-between gap-3 py-1.5 text-sm">
                <span className="text-muted-foreground">Node Status</span>
                <span className="flex gap-1.5">
                  <Badge variant="outline" className={`text-[10px] ${n.ready === true ? "text-[var(--dp-good)] border-[var(--dp-good)]/30" : n.ready === false ? "text-destructive border-destructive/30" : "text-muted-foreground"}`}>{n.ready === true ? "Ready" : n.ready === false ? "NotReady" : "Unknown"}</Badge>
                  {n.memory_pressure && <Badge variant="outline" className="text-[10px] text-[var(--dp-warn)] border-[var(--dp-warn)]/30">MemPressure</Badge>}
                  {n.disk_pressure && <Badge variant="outline" className="text-[10px] text-[var(--dp-warn)] border-[var(--dp-warn)]/30">DiskPressure</Badge>}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* Usage + Pod summary */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2"><MemoryStick className="h-4 w-4" />Live Usage</CardTitle>
              <CardDescription>Refreshes every 15s</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Meter label="CPU" pct={info?.usage?.cpu_percent} Icon={Cpu} />
              <Meter label="Memory" pct={info?.usage?.memory_percent} Icon={MemoryStick} />
              <div className="flex items-center justify-between pt-2 border-t text-sm">
                <span className="flex items-center gap-1.5 text-muted-foreground"><Boxes className="h-3.5 w-3.5" />Running Pods</span>
                <Badge variant="secondary" className="font-mono">{c.pods_running ?? "—"} / {c.pods_total ?? "—"}</Badge>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* AWS EC2 instance details — shown only when running on AWS (IMDS reachable) */}
        {info.cloud?.provider === "aws" && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2"><Cloud className="h-4 w-4" />AWS EC2 Instance</CardTitle>
              <CardDescription>Underlying cloud compute resource · live EC2 instance metadata</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-x-10 md:grid-cols-2">
              <div>
                {info.cloud.name && <Spec label="Name" value={info.cloud.name} />}
                <Spec label="Instance ID" value={info.cloud.instance_id} />
                <Spec label="Instance Type" value={info.cloud.instance_type} />
                <Spec label="Lifecycle" value={info.cloud.lifecycle ?? "on-demand"} />
                <Spec label="AMI" value={info.cloud.ami_id} />
              </div>
              <div>
                <Spec label="Region" value={info.cloud.region} />
                <Spec label="Availability Zone" value={info.cloud.availability_zone} />
                <Spec label="Private IP" value={info.cloud.private_ip ?? undefined} />
                <Spec label="Public IP" value={info.cloud.public_ip ?? undefined} />
                <Spec label="Security Groups" value={info.cloud.security_groups?.length ? info.cloud.security_groups.join(", ") : undefined} />
              </div>
            </CardContent>
          </Card>
        )}

        {/* Spec comparison: required (sum of requests) vs recommended vs actual */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2"><Gauge className="h-4 w-4" />Spec Comparison</CardTitle>
            <CardDescription>
              Required (sum of deployment resource requests) · Recommended (DATAPOND_REC_*) · Actual (current node) — computed automatically from the current cluster, regardless of environment
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 gap-y-1 text-sm">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">Resource</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">Required (min)</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">Recommended</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">Actual</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">Status</div>
              {(info?.comparison ?? []).map((r) => {
                const st = CMP_STATUS[r.status] ?? CMP_STATUS.unknown
                return (
                  <div key={r.resource} className="contents">
                    <div className="py-1.5 font-medium border-t">{r.resource} <span className="text-[10px] text-muted-foreground">({r.unit})</span></div>
                    <div className="py-1.5 font-mono text-right text-muted-foreground border-t">{r.required}</div>
                    <div className="py-1.5 font-mono text-right text-muted-foreground border-t">{r.recommended}</div>
                    <div className="py-1.5 font-mono text-right font-semibold border-t">{r.actual ?? "—"}</div>
                    <div className="py-1.5 text-right border-t"><Badge variant="outline" className={`text-[10px] ${st.cls}`}>{st.label}</Badge></div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>

        {/* Deployed Components */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2"><Layers className="h-4 w-4" />Deployed Components ({info?.components?.length ?? 0})</CardTitle>
            <CardDescription>Deployed components · image · resource requests/limits (CPU · memory)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-[1fr_1.5fr_auto_auto_auto] gap-x-4 gap-y-1 text-sm">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">Component</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">Image</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">CPU Req/Limit</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">Memory Req/Limit</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">Ready</div>
              {(info?.components ?? []).map((co) => (
                <div key={co.name} className="contents">
                  <div className="py-1 font-medium truncate border-t">{co.name}<span className="ml-1.5 text-[10px] text-muted-foreground">{co.kind}</span></div>
                  <div className="py-1 font-mono text-xs text-muted-foreground truncate border-t">{co.image}</div>
                  <div className="py-1 font-mono text-xs text-right text-muted-foreground border-t">{co.cpu_request ?? "-"}/{co.cpu_limit ?? "-"}</div>
                  <div className="py-1 font-mono text-xs text-right text-muted-foreground border-t">{co.mem_request ?? "-"}/{co.mem_limit ?? "-"}</div>
                  <div className="py-1 font-mono text-xs text-right border-t">{co.replicas}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Persistent Storage */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2"><HardDrive className="h-4 w-4" />Persistent Storage ({info?.storage?.length ?? 0})</CardTitle>
            <CardDescription>PVC (PersistentVolumeClaim)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-[1.5fr_auto_auto_1fr] gap-x-4 gap-y-1 text-sm">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">Name</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">Capacity</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">Status</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">StorageClass</div>
              {(info?.storage ?? []).map((s) => (
                <div key={s.name} className="contents">
                  <div className="py-1 font-mono text-xs truncate border-t">{s.name}</div>
                  <div className="py-1 font-mono text-right border-t">{s.capacity}</div>
                  <div className="py-1 border-t"><Badge variant={s.status === "Bound" ? "secondary" : "destructive"} className="text-[10px]">{s.status}</Badge></div>
                  <div className="py-1 text-xs text-muted-foreground truncate border-t">{s.storage_class ?? "-"}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </>
      ) : null}
    </div>
  )
}
