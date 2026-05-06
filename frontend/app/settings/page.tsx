"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Settings, Server, Package, Database, Activity,
  Cpu, MemoryStick, HardDrive, CheckCircle2,
  ExternalLink, RefreshCw, Copy, Info, ShieldCheck,
  GitBranch, Box, Clock, Layers, AlertCircle,
} from "lucide-react"

interface Service {
  name: string
  status: "healthy" | "unhealthy" | "unknown"
  url?: string
  version?: string
}

interface PlatformInfo {
  services: Service[]
  stats: {
    total_services: number
    healthy_services: number
    unhealthy_services: number
    cpu_usage?: number
    memory_usage?: number
  } | null
}

// Internal service → ingress URL mapping
const SERVICE_URLS: Record<string, string> = {
  jupyterlab:   "/jupyter",
  mlflow:       "/mlflow",
  openmetadata: "/openmetadata",
  seaweedfs:    "/seaweedfs-console",
  airflow:      "/airflow",
}

const SERVICE_META: Record<string, { label: string; desc: string; color: string }> = {
  postgres:     { label: "PostgreSQL 16",        desc: "Shared metadata database",          color: "text-blue-600" },
  mlflow:       { label: "MLflow 2.10",          desc: "ML experiment tracking",            color: "text-orange-500" },
  jupyterlab:   { label: "JupyterLab",           desc: "Interactive notebooks",             color: "text-amber-500" },
  trino:        { label: "Trino 435",            desc: "Distributed SQL query engine",       color: "text-indigo-600" },
  risingwave:   { label: "RisingWave v1.6",      desc: "Streaming SQL database",            color: "text-cyan-600" },
  openmetadata: { label: "OpenMetadata 1.2",     desc: "Data catalog & lineage",            color: "text-purple-600" },
  seaweedfs:    { label: "SeaweedFS",            desc: "S3-compatible object storage",      color: "text-green-600" },
  polaris:      { label: "Apache Polaris",       desc: "Iceberg REST catalog",              color: "text-red-500" },
  valkey:       { label: "Valkey",               desc: "Redis-compatible cache",            color: "text-rose-500" },
}

const PLATFORM_STACK = [
  { layer: "Ingress",    components: ["Traefik"],                                    color: "bg-slate-100 text-slate-700" },
  { layer: "App",        components: ["Frontend (Next.js)", "Backend (FastAPI)", "JupyterLab", "Airflow", "MLflow"], color: "bg-blue-50 text-blue-800" },
  { layer: "Compute",    components: ["Trino (OLAP)", "RisingWave (Streaming)"],     color: "bg-purple-50 text-purple-800" },
  { layer: "Catalog",    components: ["Apache Polaris (Iceberg REST)"],              color: "bg-amber-50 text-amber-800" },
  { layer: "Storage",    components: ["SeaweedFS (S3)", "Apache Iceberg"],           color: "bg-green-50 text-green-800" },
  { layer: "Metadata",   components: ["PostgreSQL", "Valkey"],                       color: "bg-indigo-50 text-indigo-800" },
  { layer: "Observability", components: ["OpenMetadata"],                            color: "bg-rose-50 text-rose-800" },
]

const SMTP_PROVIDERS = [
  {
    name: "Gmail",
    host: "smtp.gmail.com", port: "587", starttls: "True", ssl: "False",
    note: "앱 비밀번호 필요 (Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호)",
  },
  {
    name: "Office 365",
    host: "smtp.office365.com", port: "587", starttls: "True", ssl: "False",
    note: "회사 Microsoft 365 계정 사용",
  },
  {
    name: "AWS SES",
    host: "email-smtp.ap-northeast-2.amazonaws.com", port: "587", starttls: "True", ssl: "False",
    note: "IAM SMTP 자격증명 생성 필요",
  },
  {
    name: "사내 SMTP",
    host: "mail.company.com", port: "25", starttls: "False", ssl: "False",
    note: "IT팀에 SMTP 릴레이 허용 요청",
  },
]

const HELM_COMMANDS = [
  { label: "현재 설정 확인",    cmd: "helm get values datapond -n datapond" },
  { label: "업그레이드",        cmd: "helm upgrade datapond helm/datapond \\\n  --namespace datapond \\\n  --values helm/datapond/values-quicktest.yaml \\\n  --wait=false" },
  { label: "Pod 상태",          cmd: "kubectl get pods -n datapond" },
  { label: "리소스 사용량",     cmd: "kubectl top pods -n datapond" },
  { label: "백엔드 로그",       cmd: "kubectl logs -f deployment/backend -n datapond" },
]

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button
      variant="ghost" size="icon" className="h-6 w-6 shrink-0"
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
    >
      {copied
        ? <CheckCircle2 className="h-3 w-3 text-emerald-500" />
        : <Copy className="h-3 w-3 text-muted-foreground" />}
    </Button>
  )
}

export default function SettingsPage() {
  const [info, setInfo] = useState<PlatformInfo>({ services: [], stats: null })
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const [svcRes, statsRes] = await Promise.all([
        fetch("/api/services"),
        fetch("/api/dashboard/stats"),
      ])
      const services = await svcRes.json()
      const stats = await statsRes.json()
      setInfo({ services: Array.isArray(services) ? services : [], stats })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const healthy = info.services.filter(s => s.status === "healthy").length
  const total   = info.services.length

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">

        {/* ── Header ── */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Platform Settings</h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              DataPond v2.3.0 · K3s cluster · 17 Helm revisions
            </p>
          </div>
          <Button variant="outline" size="sm" className="gap-1.5" onClick={load} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {/* ── Platform Status strip ── */}
        <div className="grid grid-cols-4 gap-3">
          {[
            {
              label: "Services",
              value: loading ? null : `${healthy}/${total}`,
              sub: "all healthy",
              icon: Activity,
              ok: !loading && healthy === total,
            },
            {
              label: "CPU Usage",
              value: loading ? null : `${info.stats?.cpu_usage?.toFixed(0) ?? "—"}%`,
              sub: "cluster total",
              icon: Cpu,
              ok: !loading && (info.stats?.cpu_usage ?? 0) < 90,
            },
            {
              label: "Memory",
              value: loading ? null : `${info.stats?.memory_usage?.toFixed(0) ?? "—"}%`,
              sub: "cluster total",
              icon: MemoryStick,
              ok: !loading && (info.stats?.memory_usage ?? 0) < 90,
            },
            {
              label: "Version",
              value: "2.3.0",
              sub: "Helm revision 17",
              icon: Package,
              ok: true,
            },
          ].map(({ label, value, sub, icon: Icon, ok }) => (
            <Card key={label}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-muted-foreground">{label}</span>
                  <Icon className={`h-3.5 w-3.5 ${ok ? "text-emerald-500" : "text-amber-500"}`} />
                </div>
                {loading
                  ? <Skeleton className="h-7 w-16 mt-1" />
                  : <div className={`text-2xl font-bold ${!ok ? "text-amber-600" : ""}`}>{value}</div>
                }
                <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* ── Section grid ── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* ── Service Health ── */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base flex items-center gap-2">
                    <Server className="h-4 w-4 text-muted-foreground" />
                    Service Health
                  </CardTitle>
                  <CardDescription>실행 중인 플랫폼 서비스 상태</CardDescription>
                </div>
                {!loading && healthy === total && (
                  <Badge className="bg-emerald-500/15 text-emerald-700 border-emerald-200 gap-1">
                    <CheckCircle2 className="h-3 w-3" />All Healthy
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-2">
                {loading
                  ? Array(9).fill(0).map((_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)
                  : info.services.map(svc => {
                      const meta = SERVICE_META[svc.name]
                      const extUrl = SERVICE_URLS[svc.name]
                      return (
                        <div key={svc.name}
                          className="flex items-center gap-3 rounded-lg border p-3 bg-card hover:bg-muted/30 transition-colors">
                          <div className={`shrink-0 ${meta?.color ?? "text-gray-500"}`}>
                            <Database className="h-5 w-5" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="text-xs font-medium truncate">{meta?.label ?? svc.name}</span>
                              <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${
                                svc.status === "healthy" ? "bg-emerald-500" :
                                svc.status === "unhealthy" ? "bg-red-500" : "bg-yellow-400"
                              }`} />
                            </div>
                            <p className="text-[11px] text-muted-foreground truncate">{meta?.desc}</p>
                          </div>
                          {extUrl && (
                            <a href={extUrl} target="_blank" rel="noreferrer"
                              className="shrink-0 text-muted-foreground hover:text-foreground">
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          )}
                        </div>
                      )
                    })}
              </div>
            </CardContent>
          </Card>

          {/* ── Architecture Stack ── */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Layers className="h-4 w-4 text-muted-foreground" />
                Architecture Stack
              </CardTitle>
              <CardDescription>플랫폼 레이어 구조</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {PLATFORM_STACK.map(({ layer, components, color }) => (
                  <div key={layer} className={`rounded-lg px-3 py-2 ${color}`}>
                    <div className="text-[10px] font-semibold uppercase tracking-wider mb-1.5 opacity-70">
                      {layer}
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {components.map(c => (
                        <span key={c} className="text-[11px] font-medium bg-white/60 rounded px-1.5 py-0.5">
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* ── Cluster Info ── */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Box className="h-4 w-4 text-muted-foreground" />
                Cluster Information
              </CardTitle>
              <CardDescription>K3s 클러스터 및 런타임 정보</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-0">
                {[
                  { label: "Platform",        value: "DataPond",                icon: Package },
                  { label: "Version",         value: "v2.3.0",                  icon: GitBranch },
                  { label: "Helm Release",    value: "datapond (rev 17)",        icon: Package },
                  { label: "Kubernetes",      value: "v1.35.4+k3s1 (K3s)",      icon: Server },
                  { label: "Container RT",    value: "containerd 2.2.3-k3s1",   icon: Box },
                  { label: "OS",              value: "Ubuntu 24.04.4 LTS",       icon: HardDrive },
                  { label: "Kernel",          value: "6.17.0-22-generic",        icon: Cpu },
                  { label: "Namespace",       value: "datapond",                 icon: Layers },
                  { label: "Ingress",         value: "Traefik",                  icon: Activity },
                  { label: "Storage",         value: "local-path (K3s default)", icon: HardDrive },
                ].map(({ label, value, icon: Icon }) => (
                  <div key={label}>
                    <div className="flex items-center justify-between py-2.5 text-sm">
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <Icon className="h-3.5 w-3.5 shrink-0" />
                        {label}
                      </div>
                      <span className="font-mono text-xs text-right">{value}</span>
                    </div>
                    <Separator />
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* ── Resource Usage ── */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Cpu className="h-4 w-4 text-muted-foreground" />
                Resource Usage
              </CardTitle>
              <CardDescription>클러스터 리소스 할당 현황</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {[
                { label: "CPU", value: info.stats?.cpu_usage, unit: "%" },
                { label: "Memory", value: info.stats?.memory_usage, unit: "%" },
              ].map(({ label, value, unit }) => (
                <div key={label} className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">{label}</span>
                    {loading
                      ? <Skeleton className="h-4 w-12" />
                      : <span className={`font-semibold tabular-nums ${
                          (value ?? 0) >= 90 ? "text-red-600" :
                          (value ?? 0) >= 75 ? "text-amber-600" : "text-emerald-600"
                        }`}>{value?.toFixed(1)}{unit}</span>
                    }
                  </div>
                  {loading
                    ? <Skeleton className="h-2 w-full" />
                    : <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${
                            (value ?? 0) >= 90 ? "bg-red-500" :
                            (value ?? 0) >= 75 ? "bg-amber-500" : "bg-emerald-500"
                          }`}
                          style={{ width: `${Math.min(value ?? 0, 100)}%` }}
                        />
                      </div>
                  }
                </div>
              ))}

              <Separator />

              <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-800 space-y-1">
                <div className="font-medium flex items-center gap-1.5">
                  <Info className="h-3.5 w-3.5" />
                  리소스 최적화 팁
                </div>
                <ul className="space-y-1 list-disc list-inside text-amber-700">
                  <li>사용하지 않는 서비스는 <code className="bg-amber-100 px-1 rounded">values.yaml</code>에서 비활성화</li>
                  <li>OpenMetadata·Jupyter는 메모리 사용량이 큼 (각 ~1GB)</li>
                  <li>프로덕션은 16GB RAM 이상 권장</li>
                </ul>
              </div>
            </CardContent>
          </Card>

          {/* ── Configuration Management ── */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Settings className="h-4 w-4 text-muted-foreground" />
                Configuration Management
              </CardTitle>
              <CardDescription>Helm 기반 설정 변경 방법</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-lg bg-muted/40 border p-3 text-xs space-y-1.5">
                <p className="font-medium text-foreground">설정 변경 워크플로우</p>
                <ol className="space-y-1 list-decimal list-inside text-muted-foreground">
                  <li><code className="bg-background rounded px-1">helm/datapond/values-quicktest.yaml</code> 편집</li>
                  <li>아래 upgrade 명령 실행</li>
                  <li>Pod 재시작 후 변경사항 반영 확인</li>
                </ol>
              </div>

              <div className="space-y-2">
                {HELM_COMMANDS.map(({ label, cmd }) => (
                  <div key={label} className="rounded-md border overflow-hidden">
                    <div className="flex items-center justify-between px-3 py-1.5 bg-muted/30 border-b">
                      <span className="text-[11px] font-medium text-muted-foreground">{label}</span>
                      <CopyButton text={cmd} />
                    </div>
                    <pre className="px-3 py-2 text-[11px] font-mono text-foreground overflow-x-auto whitespace-pre">
                      {cmd}
                    </pre>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* ── Email Alert (SMTP) ── */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Activity className="h-4 w-4 text-muted-foreground" />
                이메일 알림 (SMTP) 설정
              </CardTitle>
              <CardDescription>
                파이프라인 실패 시 이메일 알림을 받으려면 Airflow SMTP를 설정하세요
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* 현재 상태 */}
              <div className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
                <AlertCircle className="h-4 w-4 text-amber-600 shrink-0" />
                <div className="text-xs text-amber-800">
                  <span className="font-medium">현재 비활성</span> —
                  {" "}SMTP 미설정 상태입니다. 아래 가이드를 따라 설정하세요.
                </div>
              </div>

              {/* 설정 방법 */}
              <div className="space-y-2">
                <p className="text-xs font-medium">Step 1 — SMTP 비밀번호를 K8s Secret에 저장</p>
                <div className="rounded-md border overflow-hidden">
                  <div className="flex items-center justify-between px-3 py-1.5 bg-muted/30 border-b">
                    <span className="text-[11px] text-muted-foreground">kubectl</span>
                    <CopyButton text={`kubectl create secret generic datapond-secrets -n datapond \\\n  --from-literal=AIRFLOW_SMTP_PASSWORD="your-smtp-password" \\\n  --dry-run=client -o yaml | kubectl apply -f -`} />
                  </div>
                  <pre className="px-3 py-2 text-[11px] font-mono overflow-x-auto whitespace-pre">
{`kubectl create secret generic datapond-secrets -n datapond \\
  --from-literal=AIRFLOW_SMTP_PASSWORD="your-smtp-password" \\
  --dry-run=client -o yaml | kubectl apply -f -`}
                  </pre>
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-xs font-medium">Step 2 — values-quicktest.yaml SMTP 활성화</p>
                <div className="rounded-md border overflow-hidden">
                  <div className="flex items-center justify-between px-3 py-1.5 bg-muted/30 border-b">
                    <span className="text-[11px] text-muted-foreground">helm/datapond/values-quicktest.yaml</span>
                    <CopyButton text={`airflow:\n  smtp:\n    enabled: true\n    host: "smtp.gmail.com"\n    port: "587"\n    starttls: "True"\n    ssl: "False"\n    user: "alerts@company.com"\n    mailFrom: "DataPond <alerts@company.com>"`} />
                  </div>
                  <pre className="px-3 py-2 text-[11px] font-mono overflow-x-auto whitespace-pre text-muted-foreground">
{`airflow:
  smtp:
    enabled: true
    host: "smtp.gmail.com"
    port: "587"
    starttls: "True"
    ssl: "False"
    user: "alerts@company.com"
    mailFrom: "DataPond <alerts@company.com>"`}
                  </pre>
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-xs font-medium">Step 3 — Helm 업그레이드</p>
                <div className="rounded-md border overflow-hidden">
                  <div className="flex items-center justify-between px-3 py-1.5 bg-muted/30 border-b">
                    <span className="text-[11px] text-muted-foreground">helm upgrade</span>
                    <CopyButton text="helm upgrade datapond helm/datapond --namespace datapond --values helm/datapond/values-quicktest.yaml --wait=false" />
                  </div>
                  <pre className="px-3 py-2 text-[11px] font-mono overflow-x-auto whitespace-pre">
{`helm upgrade datapond helm/datapond \\
  --namespace datapond \\
  --values helm/datapond/values-quicktest.yaml \\
  --wait=false`}
                  </pre>
                </div>
              </div>

              {/* SMTP 프로바이더 참고 */}
              <div>
                <p className="text-xs font-medium mb-2">SMTP 프로바이더별 설정 참고</p>
                <div className="space-y-1">
                  {SMTP_PROVIDERS.map(p => (
                    <div key={p.name} className="rounded-md border px-3 py-2 text-xs space-y-0.5">
                      <div className="flex items-center gap-3">
                        <span className="font-medium w-24 shrink-0">{p.name}</span>
                        <code className="text-muted-foreground">{p.host}:{p.port}</code>
                      </div>
                      <p className="text-[11px] text-muted-foreground pl-0">{p.note}</p>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* ── Access URLs ── */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <ExternalLink className="h-4 w-4 text-muted-foreground" />
                Access URLs
              </CardTitle>
              <CardDescription>서비스별 접근 주소 및 인증 정보</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-0">
                {[
                  { service: "Frontend",     url: "http://datapond.local",           cred: "" },
                  { service: "Backend API",  url: "http://datapond.local/api",        cred: "" },
                  { service: "JupyterLab",   url: "http://datapond.local/jupyter",    cred: "token: jupyter" },
                  { service: "Airflow",      url: "http://datapond.local/airflow",    cred: "airflow / airflow" },
                  { service: "MLflow",       url: "http://datapond.local/mlflow",     cred: "" },
                  { service: "OpenMetadata", url: "http://datapond.local/openmetadata", cred: "" },
                  { service: "SeaweedFS",    url: "http://datapond.local/seaweedfs-console", cred: "" },
                ].map(({ service, url, cred }) => (
                  <div key={service}>
                    <div className="flex items-center justify-between py-2.5 text-sm gap-2">
                      <span className="text-muted-foreground shrink-0 w-28">{service}</span>
                      <div className="flex items-center gap-1 flex-1 min-w-0">
                        <a href={url} target="_blank" rel="noreferrer"
                          className="text-xs font-mono text-blue-600 hover:underline truncate">
                          {url}
                        </a>
                        <CopyButton text={url} />
                      </div>
                      {cred && (
                        <span className="text-[11px] text-muted-foreground font-mono shrink-0 bg-muted px-1.5 py-0.5 rounded">
                          {cred}
                        </span>
                      )}
                    </div>
                    <Separator />
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* ── Security & Roadmap ── */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-muted-foreground" />
                Security & Planned Features
              </CardTitle>
              <CardDescription>현재 보안 상태 및 향후 구현 예정 기능</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">
                    현재 상태
                  </p>
                  <div className="space-y-2">
                    {[
                      { label: "TLS/HTTPS",           status: "pending",  note: "현재 HTTP" },
                      { label: "인증 시스템",          status: "pending",  note: "미구현" },
                      { label: "RBAC",                 status: "pending",  note: "미구현" },
                      { label: "Secret 암호화",        status: "ok",       note: "K8s Secrets" },
                      { label: "네트워크 격리",        status: "ok",       note: "K8s namespace" },
                      { label: "컨테이너 분리",        status: "ok",       note: "Pod 격리" },
                    ].map(({ label, status, note }) => (
                      <div key={label} className="flex items-center gap-2 text-sm">
                        <span className={`h-2 w-2 rounded-full shrink-0 ${
                          status === "ok" ? "bg-emerald-500" :
                          status === "pending" ? "bg-amber-400" : "bg-red-500"
                        }`} />
                        <span className="flex-1">{label}</span>
                        <span className="text-xs text-muted-foreground">{note}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">
                    향후 계획
                  </p>
                  <div className="space-y-2">
                    {[
                      { label: "LDAP / Active Directory 연동" },
                      { label: "SAML 2.0 / OIDC SSO" },
                      { label: "MFA (Multi-Factor Auth)" },
                      { label: "Row-level Security (RLS)" },
                      { label: "Column Masking" },
                      { label: "Audit Log" },
                      { label: "Prometheus + Grafana 모니터링" },
                    ].map(({ label }) => (
                      <div key={label} className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Clock className="h-3 w-3 shrink-0 text-muted-foreground/50" />
                        {label}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

        </div>
      </div>
    </div>
  )
}
