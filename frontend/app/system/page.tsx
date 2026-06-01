"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Server, Cpu, MemoryStick, HardDrive, Boxes, RefreshCw, Layers, Gauge } from "lucide-react"

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
}

const CMP_STATUS: Record<string, { label: string; cls: string }> = {
  ok:           { label: "권장 충족", cls: "bg-emerald-500/10 text-emerald-600 border-emerald-200" },
  warning:      { label: "권장 미달", cls: "bg-amber-500/10 text-amber-600 border-amber-200" },
  insufficient: { label: "최소 미달", cls: "bg-red-500/10 text-red-600 border-red-200" },
  unknown:      { label: "확인 불가", cls: "bg-muted text-muted-foreground border-transparent" },
}

function Meter({ label, pct, Icon }: { label: string; pct?: number | null; Icon: any }) {
  const v = typeof pct === "number" ? pct : null
  const color = v == null ? "bg-muted-foreground/30" : v > 85 ? "bg-red-500" : v > 60 ? "bg-amber-500" : "bg-emerald-500"
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

  const load = async () => {
    try {
      const res = await fetch("/api/system/info")
      if (res.ok) setInfo(await res.json())
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 15000)  // 15s 주기 갱신
    return () => clearInterval(t)
  }, [])

  const n = info?.node ?? {}
  const c = info?.cluster ?? {}

  return (
    <div className="p-6 space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/dashboard">Dashboard</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>System</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2"><Server className="h-6 w-6" />System</h1>
          <p className="text-muted-foreground text-sm">서버 시스템 정보 · 구성 사양</p>
        </div>
        <Button variant="outline" size="sm" onClick={load}><RefreshCw className="h-4 w-4 mr-1.5" />새로고침</Button>
      </div>

      {loading && !info ? (
        <div className="grid gap-4 md:grid-cols-2"><Skeleton className="h-48" /><Skeleton className="h-48" /></div>
      ) : (
      <>
        <div className="grid gap-4 md:grid-cols-2">
          {/* 노드 사양 */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2"><Cpu className="h-4 w-4" />서버 사양</CardTitle>
              <CardDescription>{n.name ?? "node"}</CardDescription>
            </CardHeader>
            <CardContent>
              <Spec label="CPU" value={n.cpu_cores ? `${n.cpu_cores} vCPU` : undefined} />
              <Spec label="메모리" value={n.memory_gb ? `${n.memory_gb} GB` : undefined} />
              <Spec label="디스크" value={n.ephemeral_storage_gb ? `${n.ephemeral_storage_gb} GB` : undefined} />
              <Spec label="할당 가능 CPU/메모리" value={n.allocatable_cpu_cores != null ? `${n.allocatable_cpu_cores} vCPU / ${n.allocatable_memory_gb} GB` : undefined} />
              <Spec label="아키텍처" value={n.arch} />
              <Spec label="OS" value={n.os} />
              <Spec label="커널" value={n.kernel} />
              <Spec label="컨테이너 런타임" value={n.container_runtime} />
              <Spec label="Kubernetes" value={c.kubernetes ?? n.kubelet} />
              <Spec label="최대 Pod" value={n.max_pods} />
              <div className="flex justify-between gap-3 py-1.5 text-sm">
                <span className="text-muted-foreground">노드 상태</span>
                <span className="flex gap-1.5">
                  <Badge variant="outline" className={`text-[10px] ${n.ready ? "text-emerald-600 border-emerald-200" : "text-red-600 border-red-200"}`}>{n.ready ? "Ready" : "NotReady"}</Badge>
                  {n.memory_pressure && <Badge variant="outline" className="text-[10px] text-amber-600 border-amber-200">MemPressure</Badge>}
                  {n.disk_pressure && <Badge variant="outline" className="text-[10px] text-amber-600 border-amber-200">DiskPressure</Badge>}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* 사용량 + Pod 요약 */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2"><MemoryStick className="h-4 w-4" />실시간 사용량</CardTitle>
              <CardDescription>15초 주기 갱신</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Meter label="CPU" pct={info?.usage?.cpu_percent} Icon={Cpu} />
              <Meter label="메모리" pct={info?.usage?.memory_percent} Icon={MemoryStick} />
              <div className="flex items-center justify-between pt-2 border-t text-sm">
                <span className="flex items-center gap-1.5 text-muted-foreground"><Boxes className="h-3.5 w-3.5" />실행 Pod</span>
                <Badge variant="secondary" className="font-mono">{c.pods_running ?? "—"} / {c.pods_total ?? "—"}</Badge>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* 사양 비교: 필요(요청 합) vs 권장 vs 실제 */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2"><Gauge className="h-4 w-4" />사양 비교</CardTitle>
            <CardDescription>
              필요(배포 리소스 요청 합) · 권장(DATAPOND_REC_*) · 실제(현재 노드) — 환경에 무관하게 현재 클러스터 기준으로 자동 계산
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 gap-y-1 text-sm">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">리소스</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">필요(최소)</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">권장</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">실제</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">판정</div>
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

        {/* 구성 컴포넌트 */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2"><Layers className="h-4 w-4" />구성 컴포넌트 ({info?.components?.length ?? 0})</CardTitle>
            <CardDescription>배포된 컴포넌트 · 이미지 · 리소스 요청/제한 (CPU · 메모리)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-[1fr_1.5fr_auto_auto_auto] gap-x-4 gap-y-1 text-sm">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">컴포넌트</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">이미지</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">CPU 요청/제한</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">메모리 요청/제한</div>
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

        {/* 영속 스토리지 */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2"><HardDrive className="h-4 w-4" />영속 스토리지 ({info?.storage?.length ?? 0})</CardTitle>
            <CardDescription>PVC (PersistentVolumeClaim)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-[1.5fr_auto_auto_1fr] gap-x-4 gap-y-1 text-sm">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">이름</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium text-right">용량</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">상태</div>
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
      )}
    </div>
  )
}
