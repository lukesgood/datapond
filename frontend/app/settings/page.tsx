"use client"

import { useEffect, useState, useCallback } from "react"
import { useToast } from "@/lib/toast"
import { ErrorBox } from "@/components/ui/error-box"
import { useConfirm } from "@/lib/confirm"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import {
  Settings, Server, Package, Database, Activity, Cpu, HardDrive,
  CheckCircle2, ExternalLink, RefreshCw, Copy, Info, ShieldCheck,
  GitBranch, Box, Clock, Layers, AlertCircle, Users, Plus, Trash2,
  Eye, EyeOff, UserPlus, KeyRound, Shield, UserX, UserCheck, SlidersHorizontal,
  Link, Terminal,
} from "lucide-react"
import { getUser } from "@/lib/auth"
import { PasskeyManager } from "@/components/passkey-manager"
import { useCapabilityStrict, useCapability } from "@/lib/capabilities"

// ── Constants ──────────────────────────────────────────────────────────────────

const SERVICE_META: Record<string, { label: string; desc: string; color: string; url?: string }> = {
  postgres:     { label: "PostgreSQL 16",     desc: "Shared metadata database",      color: "text-blue-600" },
  mlflow:       { label: "MLflow",            desc: "ML experiment tracking",         color: "text-orange-500", url: "/mlflow/" },
  jupyterlab:   { label: "JupyterLab",        desc: "Interactive notebooks",          color: "text-amber-500",  url: "/jupyter" },
  trino:        { label: "Trino 435",         desc: "Distributed SQL query engine",   color: "text-indigo-600" },
  risingwave:   { label: "RisingWave v1.6",   desc: "Streaming SQL database",         color: "text-cyan-600" },
  openmetadata: { label: "OpenMetadata",      desc: "Data catalog & lineage",         color: "text-purple-600", url: "/openmetadata" },
  seaweedfs:    { label: "SeaweedFS",         desc: "S3-compatible object storage",   color: "text-green-600",  url: "/seaweedfs-console" },
  polaris:      { label: "Apache Polaris",    desc: "Iceberg REST catalog",           color: "text-red-500" },
  valkey:       { label: "Valkey",            desc: "Redis-compatible cache",         color: "text-rose-500" },
  airflow:      { label: "Airflow",           desc: "Pipeline orchestration",         color: "text-sky-600",    url: "/airflow/" },
  // AWS-managed foundation services (names match /api/services display names)
  "Amazon S3":      { label: "Amazon S3",      desc: "Object storage",              color: "text-green-600" },
  "Amazon Aurora":  { label: "Amazon Aurora",  desc: "Postgres + pgvector",         color: "text-blue-600" },
  "Amazon Bedrock": { label: "Amazon Bedrock", desc: "LLM / embeddings",            color: "text-purple-600" },
  "AWS Glue":       { label: "AWS Glue",       desc: "Iceberg Data Catalog",        color: "text-orange-600" },
  "Amazon Athena":  { label: "Amazon Athena",  desc: "Serverless SQL query engine", color: "text-indigo-600" },
  // Lowercase aliases (in case the API keys by short name)
  s3:           { label: "Amazon S3",         desc: "Object storage",                 color: "text-green-600" },
  aurora:       { label: "Amazon Aurora",     desc: "Postgres + pgvector",            color: "text-blue-600" },
  bedrock:      { label: "Amazon Bedrock",    desc: "LLM / embeddings",               color: "text-purple-600" },
  glue:         { label: "AWS Glue",          desc: "Iceberg Data Catalog",           color: "text-orange-600" },
  athena:       { label: "Amazon Athena",     desc: "Serverless SQL query engine",    color: "text-indigo-600" },
  // In-cluster pods
  backend:      { label: "Backend API",       desc: "FastAPI application",            color: "text-slate-600" },
  frontend:     { label: "Frontend",          desc: "Management UI (Next.js)",        color: "text-slate-500" },
  litellm:      { label: "LiteLLM",           desc: "AI model gateway (→ Bedrock)",   color: "text-fuchsia-600" },
}

// Access URLs (path-hosted services). OpenMetadata / SeaweedFS / Trino are NOT
// listed: their web UIs don't support sub-path hosting, so they 404 under /<svc>
// on every profile — use a subdomain or port-forward for those admin UIs.
// MLflow/Airflow paths keep a trailing slash: their gunicorn frontend emits a
// 308 add-slash redirect with an absolute http:// URL (the proxy hop drops
// X-Forwarded-Proto), which downgrades the click to http. Linking the slashed
// form skips that redirect — /mlflow/ → 200, /airflow/ → relative 302.
// `cap` gates a row behind a platform capability — dead links for disabled
// components (Jupyter/Airflow/MLflow on the AWS foundation profile) are hidden.
const ACCESS_URL_DEFS = [
  { service: "Management UI",  path: "",                  cred: undefined },
  { service: "Backend API",    path: "/api/health",       cred: undefined },
  { service: "JupyterLab",     path: "/jupyter",          cred: "token: jupyter",   cap: "notebooks" },
  { service: "Airflow",        path: "/airflow/",         cred: "airflow / airflow", cap: "pipelines" },
  { service: "MLflow",         path: "/mlflow/",          cred: undefined,          cap: "experiments" },
]

const HELM_CMDS = [
  { label: "Check current values",  cmd: "helm get values datapond -n datapond" },
  { label: "Upgrade (single-node)", cmd: "helm upgrade datapond helm/datapond \\\n  --namespace datapond \\\n  --values helm/datapond/values-prod-single.yaml \\\n  --wait=false" },
  { label: "Pod status",            cmd: "kubectl get pods -n datapond" },
  { label: "Resource usage",        cmd: "kubectl top pods -n datapond" },
  { label: "Backend logs",          cmd: "kubectl logs -f deployment/backend -n datapond" },
]

// ── Helpers ────────────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0"
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}>
      {copied ? <CheckCircle2 className="h-3 w-3 text-green-600" /> : <Copy className="h-3 w-3 text-muted-foreground" />}
    </Button>
  )
}

function CodeBlock({ label, code }: { label: string; code: string }) {
  return (
    <div className="rounded-md border overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 bg-muted/40 border-b">
        <span className="text-[11px] text-muted-foreground font-medium">{label}</span>
        <CopyButton text={code} />
      </div>
      <pre className="px-3 py-2.5 text-[11px] font-mono overflow-x-auto whitespace-pre leading-relaxed">{code}</pre>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  // Fail-closed: only render passkey management when the backend explicitly
  // reports webauthn=true. A /api/capabilities fetch error must not show the
  // secure-context-sensitive passkey UI (mirrors the login page's strict gate).
  const webauthnEnabled = useCapabilityStrict("webauthn")
  // Fail-closed like webauthn above — only claim SSO is active when the backend
  // confirms it (EE image + OIDC_ENABLED). Avoids the Security Status card
  // asserting a state we haven't verified.
  const ssoEnabled = useCapabilityStrict("sso")
  // Capability gates for profile-dependent access URLs / cards
  const notebooksEnabled = useCapability("notebooks")
  const pipelinesEnabled = useCapability("pipelines")
  const experimentsEnabled = useCapability("experiments")
  const [services, setServices] = useState<any[]>([])
  const [stats, setStats]       = useState<any>(null)
  const [loading, setLoading]   = useState(true)
  // mounted guard — render browser-only values (window.location) after mount to
  // avoid SSR/client hydration mismatch (React #418).
  const [mounted, setMounted]   = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [svcRes, statRes] = await Promise.all([
        fetch("/api/services"),
        fetch("/api/dashboard/stats"),
      ])
      if (svcRes.ok)  setServices(await svcRes.json())
      if (statRes.ok) setStats(await statRes.json())
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { setMounted(true) }, [])

  const healthy = services.filter(s => ["healthy", "managed"].includes(s.status)).length

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto px-6 py-6 space-y-5">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Settings</h2>
            <p className="text-sm text-muted-foreground mt-0.5">DataPond platform configuration and administration</p>
          </div>
          <Button variant="outline" size="sm" className="gap-1.5" onClick={load} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {/* Status strip */}
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Services",   value: loading ? null : `${healthy}/${services.length}`,        sub: "healthy",         ok: !loading && healthy === services.length },
            { label: "CPU",        value: loading ? null : stats?.cpu_usage != null ? `${stats.cpu_usage.toFixed(0)}%` : "—",
              sub: "cluster",    ok: !loading && (stats?.cpu_usage ?? 0) < 90,   warn: (stats?.cpu_usage ?? 0) >= 90 },
            { label: "Memory",     value: loading ? null : stats?.memory_usage != null ? `${stats.memory_usage.toFixed(0)}%` : "—",
              sub: "cluster",    ok: !loading && (stats?.memory_usage ?? 0) < 90, warn: (stats?.memory_usage ?? 0) >= 90 },
            { label: "Version",    value: "2.3.0",            sub: "DataPond",      ok: true },
          ].map(({ label, value, sub, ok, warn }: any) => (
            <Card key={label}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-muted-foreground">{label}</span>
                  <span className={`h-2 w-2 rounded-full ${ok ? "bg-green-500" : warn ? "bg-red-500" : "bg-amber-400"}`} />
                </div>
                {loading && value === null
                  ? <Skeleton className="h-7 w-16 mt-1" />
                  : <div className={`text-2xl font-bold ${warn ? "text-destructive" : ""}`}>{value}</div>}
                <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Tabs */}
        <Tabs defaultValue="overview">
          <TabsList className="h-9">
            <TabsTrigger value="overview"  className="text-xs">Overview</TabsTrigger>
            <TabsTrigger value="users"     className="text-xs">Users</TabsTrigger>
            <TabsTrigger value="security"  className="text-xs">Security</TabsTrigger>
            <TabsTrigger value="system"    className="text-xs">System</TabsTrigger>
          </TabsList>

          {/* ── Overview ── */}
          <TabsContent value="overview" className="mt-5 space-y-5">
            {/* Service Health */}
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base flex items-center gap-2">
                      <Server className="h-4 w-4 text-muted-foreground" />Service Health
                    </CardTitle>
                    <CardDescription>Running platform services</CardDescription>
                  </div>
                  {!loading && healthy === services.length && services.length > 0 && (
                    <Badge className="bg-green-500/10 text-green-700 border-green-200 gap-1">
                      <CheckCircle2 className="h-3 w-3" />All Healthy
                    </Badge>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                  {loading
                    ? Array(9).fill(0).map((_,i) => <Skeleton key={i} className="h-16 rounded-lg" />)
                    : services.map(svc => {
                        const meta = SERVICE_META[svc.name]
                        return (
                          <div key={svc.name}
                            className="flex items-center gap-3 rounded-lg border p-3 bg-card hover:bg-muted/30 transition-colors">
                            <span className={`shrink-0 ${meta?.color ?? "text-muted-foreground"}`}>
                              <Database className="h-4 w-4" />
                            </span>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="text-xs font-medium truncate">{meta?.label ?? svc.name}</span>
                                <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${
                                  svc.status === "healthy" ? "bg-green-500" :
                                  svc.status === "unhealthy" ? "bg-red-500" : "bg-amber-400"}`} />
                              </div>
                              <p className="text-[11px] text-muted-foreground truncate">{meta?.desc}</p>
                            </div>
                            {meta?.url && (
                              <a href={meta.url} target="_blank" rel="noreferrer"
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

            {/* Access URLs */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Link className="h-4 w-4 text-muted-foreground" />Access URLs
                </CardTitle>
                <CardDescription>Service endpoints and credentials</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="divide-y">
                  {ACCESS_URL_DEFS.filter(({ cap }) =>
                    cap === "notebooks" ? notebooksEnabled :
                    cap === "pipelines" ? pipelinesEnabled :
                    cap === "experiments" ? experimentsEnabled : true
                  ).map(({ service, path, cred }) => {
                    const url = mounted
                      ? `${window.location.protocol}//${window.location.host}${path}`
                      : path
                    return (
                      <div key={service} className="flex items-center gap-3 py-2.5 text-sm">
                        <span className="text-muted-foreground w-28 shrink-0 text-xs">{service}</span>
                        <div className="flex items-center gap-1 flex-1 min-w-0">
                          <a href={url} target="_blank" rel="noreferrer"
                            className="text-xs font-mono text-primary hover:underline truncate">{url}</a>
                          <CopyButton text={url} />
                        </div>
                        {cred && (
                          <code className="text-[11px] text-muted-foreground shrink-0 bg-muted px-1.5 py-0.5 rounded">{cred}</code>
                        )}
                      </div>
                    )
                  })}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── Users ── */}
          <TabsContent value="users" className="mt-5">
            <UserManagement />
          </TabsContent>

          {/* ── AI ── */}

          {/* ── Security ── */}
          <TabsContent value="security" className="mt-5 space-y-5">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-muted-foreground" />Security Status
                </CardTitle>
                <CardDescription>Current security configuration</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="divide-y">
                  {[
                    { label: "Authentication",       status: "ok",      note: "JWT-based login enabled" },
                    { label: "Role-based Access",    status: "ok",      note: "admin / viewer roles" },
                    { label: "API Protection",       status: "ok",      note: "Bearer token required" },
                    { label: "Password Hashing",     status: "ok",      note: "bcrypt (rounds=12)" },
                    { label: "Session Expiry",       status: "ok",      note: "24h JWT expiry" },
                    { label: "First-login Policy",   status: "ok",      note: "Forced password change" },
                    // TLS is derived from the actual page origin (not hardcoded) so this
                    // row can't drift from reality — the live deployment terminates TLS
                    // via cert-manager/Let's Encrypt (values-prod-single.yaml), but a
                    // port-forward or misconfigured ingress would correctly show HTTP.
                    !mounted ? { label: "TLS/HTTPS", status: "ok", note: "Checking…" }
                      : window.location.protocol === "https:"
                        ? { label: "TLS/HTTPS", status: "ok",      note: "HTTPS — cert-manager (Let's Encrypt)" }
                        : { label: "TLS/HTTPS", status: "pending", note: "HTTP only — configure cert-manager" },
                    // LDAP/AD + OIDC SSO both ship in the image; gate the "Active" claim
                    // on the real /api/capabilities flag (mirrors PasskeyManager below)
                    // rather than asserting a state that may not be configured on every
                    // install. Never falls back to "planned" — the feature is built.
                    ssoEnabled
                      ? { label: "LDAP / SSO", status: "ok",        note: "OIDC SSO active (LDAP/AD also available)" }
                      : { label: "LDAP / SSO", status: "available", note: "Shipped — LDAP/AD + OIDC SSO (opt-in via env config)" },
                    webauthnEnabled
                      ? { label: "MFA", status: "ok",        note: "Passkey / WebAuthn active" }
                      : { label: "MFA", status: "available", note: "Shipped — Passkey/WebAuthn (requires HTTPS)" },
                    { label: "Audit Log",            status: "ok",      note: "auth_audit_log + AI spend logs" },
                    { label: "Column Masking",       status: "ok",      note: "Governance — masking policies" },
                    { label: "Row-level Security",   status: "ok",      note: "Governance — RLS engine" },
                  ].map(({ label, status, note }) => (
                    <div key={label} className="flex items-center gap-3 py-2.5 text-sm">
                      <span className={`h-2 w-2 rounded-full shrink-0 ${
                        status === "ok"        ? "bg-green-500" :
                        status === "pending"   ? "bg-amber-400" :
                        status === "available" ? "bg-blue-400"  : "bg-muted-foreground/30"}`} />
                      <span className="flex-1">{label}</span>
                      <span className="text-xs text-muted-foreground">{note}</span>
                      {status === "ok"        && <Badge variant="secondary" className="text-[10px] h-4 px-1.5 bg-[var(--dp-good)]/10 text-[var(--dp-good)] border-0">Active</Badge>}
                      {status === "pending"   && <Badge variant="secondary" className="text-[10px] h-4 px-1.5 bg-[var(--dp-warn)]/10 text-[var(--dp-warn)] border-0">Pending</Badge>}
                      {status === "available" && <Badge variant="secondary" className="text-[10px] h-4 px-1.5 bg-primary/10 text-primary border-0">Available</Badge>}
                      {status === "planned"   && <Badge variant="secondary" className="text-[10px] h-4 px-1.5">Planned</Badge>}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Passkeys / WebAuthn */}
            {webauthnEnabled && <PasskeyManager />}

            {/* Network isolation */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Server className="h-4 w-4 text-muted-foreground" />Infrastructure Security
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="divide-y">
                  {[
                    { label: "Secret Encryption",  note: "K8s Secrets encrypted at rest" },
                    { label: "Network Isolation",  note: "K8s namespace isolation" },
                    { label: "Container Runtime",  note: "containerd — pod isolation" },
                    { label: "Image Pull Policy",  note: "IfNotPresent" },
                    { label: "Deployment Strategy",note: "Recreate — no partial state" },
                  ].map(({ label, note }) => (
                    <div key={label} className="flex items-center gap-3 py-2.5 text-sm">
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
                      <span className="flex-1">{label}</span>
                      <span className="text-xs text-muted-foreground">{note}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── System ── */}
          <TabsContent value="system" className="mt-5 space-y-5">
            <div className="grid md:grid-cols-2 gap-5">
              {/* Platform info */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Box className="h-4 w-4 text-muted-foreground" />Platform Information
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="divide-y">
                    {[
                      { label: "DataPond",      value: "v2.3.0" },
                      { label: "Kubernetes",    value: "v1.35.4+k3s1" },
                      { label: "Distribution",  value: "K3s" },
                      { label: "Namespace",     value: "datapond" },
                      { label: "Ingress",       value: "Traefik" },
                      { label: "Storage",       value: "Amazon S3 (data)" },
                      { label: "Container RT",  value: "containerd" },
                    ].map(({ label, value }) => (
                      <div key={label} className="flex items-center justify-between py-2 text-sm">
                        <span className="text-muted-foreground text-xs">{label}</span>
                        <span className="font-mono text-xs">{value}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              {/* Resource usage */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Cpu className="h-4 w-4 text-muted-foreground" />Resource Usage
                  </CardTitle>
                  <CardDescription>Cluster-wide resource allocation</CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  {[
                    { label: "CPU",    value: stats?.cpu_usage },
                    { label: "Memory", value: stats?.memory_usage },
                  ].map(({ label, value }) => (
                    <div key={label} className="space-y-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">{label}</span>
                        {loading
                          ? <Skeleton className="h-4 w-12" />
                          : <span className={`font-semibold tabular-nums ${
                              value == null ? "text-muted-foreground" :
                              value >= 90 ? "text-destructive" :
                              value >= 75 ? "text-amber-600" : "text-green-600"}`}>
                              {value != null ? `${value.toFixed(1)}%` : "—"}
                            </span>}
                      </div>
                      {loading ? <Skeleton className="h-2 w-full" /> : (
                        <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                          <div className={`h-full rounded-full transition-all ${
                            value == null ? "" :
                            value >= 90 ? "bg-destructive" :
                            value >= 75 ? "bg-amber-500" : "bg-green-500"}`}
                            style={{ width: `${Math.min(value ?? 0, 100)}%` }} />
                        </div>
                      )}
                    </div>
                  ))}

                  {((stats?.cpu_usage ?? 0) >= 75 || (stats?.memory_usage ?? 0) >= 75) && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50/50 px-3 py-2.5 text-xs text-amber-700 flex items-start gap-2">
                      <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                      <div>
                        <p className="font-medium">High resource usage</p>
                        <p className="mt-0.5 text-amber-600">Disable unused services in values.yaml or add more RAM. Production: 32GB+ recommended.</p>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* Helm configuration */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Terminal className="h-4 w-4 text-muted-foreground" />Configuration Management
                </CardTitle>
                <CardDescription>Helm-based configuration workflow</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="rounded-lg bg-muted/40 border px-4 py-3 text-xs space-y-1.5">
                  <p className="font-medium">How to apply changes</p>
                  <ol className="list-decimal list-inside space-y-1 text-muted-foreground">
                    <li>Edit <code className="bg-background rounded px-1">helm/datapond/values-prod-single.yaml</code></li>
                    <li>Run the upgrade command below</li>
                    <li>Wait for pods to restart and verify</li>
                  </ol>
                </div>
                <div className="space-y-2">
                  {HELM_CMDS.map(({ label, cmd }) => (
                    <CodeBlock key={label} label={label} code={cmd} />
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* SMTP — Airflow-based, only relevant when pipelines (Airflow) is deployed */}
            {pipelinesEnabled && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Activity className="h-4 w-4 text-muted-foreground" />Email Alerts (SMTP)
                </CardTitle>
                <CardDescription>Configure Airflow SMTP for pipeline failure notifications</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50/50 px-4 py-3">
                  <AlertCircle className="h-4 w-4 text-amber-600 shrink-0" />
                  <p className="text-xs text-amber-700"><span className="font-medium">Not configured</span> — follow the steps below to enable email notifications.</p>
                </div>

                <CodeBlock label="Step 1 — Store SMTP password as K8s Secret"
                  code={`kubectl create secret generic datapond-secrets -n datapond \\\n  --from-literal=AIRFLOW_SMTP_PASSWORD="your-password" \\\n  --dry-run=client -o yaml | kubectl apply -f -`} />

                <CodeBlock label="Step 2 — Add to values-prod-single.yaml"
                  code={`airflow:\n  smtp:\n    enabled: true\n    host: "smtp.gmail.com"\n    port: "587"\n    user: "alerts@company.com"\n    mailFrom: "DataPond <alerts@company.com>"`} />

                <CodeBlock label="Step 3 — Apply with Helm upgrade"
                  code="helm upgrade datapond helm/datapond -n datapond --values helm/datapond/values-prod-single.yaml --wait=false" />

                <div>
                  <p className="text-xs font-medium mb-2">Common SMTP providers</p>
                  <div className="space-y-1.5">
                    {[
                      { name: "Gmail",       host: "smtp.gmail.com",                              port: "587", note: "Requires App Password (Google Account → Security → 2FA → App passwords)" },
                      { name: "Office 365",  host: "smtp.office365.com",                          port: "587", note: "Use corporate Microsoft 365 account" },
                      { name: "AWS SES",     host: "email-smtp.ap-northeast-2.amazonaws.com",     port: "587", note: "Create IAM SMTP credentials in SES console" },
                      { name: "On-prem SMTP",host: "mail.company.com",                            port: "25",  note: "Request SMTP relay from IT team" },
                    ].map(p => (
                      <div key={p.name} className="rounded-md border px-3 py-2 text-xs">
                        <div className="flex items-center gap-3">
                          <span className="font-medium w-24 shrink-0">{p.name}</span>
                          <code className="text-muted-foreground">{p.host}:{p.port}</code>
                        </div>
                        <p className="text-[11px] text-muted-foreground mt-0.5">{p.note}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
            )}
          </TabsContent>
        </Tabs>

        {/* User Management (moved outside tabs for clean separation) */}
      </div>
    </div>
  )
}

// ── User Management ────────────────────────────────────────────────────────────

interface UserRecord {
  id: string; username: string; email: string; display_name: string
  role: "admin" | "viewer"; is_active: boolean
  require_password_change: boolean; created_at: string | null
  attributes?: Record<string, string>
}

function UserManagement() {
  const currentUser = getUser()
  const isAdmin     = currentUser?.role === "admin"

  const [users, setUsers]         = useState<UserRecord[]>([])
  const [loading, setLoading]     = useState(true)

  const [showCreate, setShowCreate]   = useState(false)
  const [newUsername, setNewUsername] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [newDisplayName, setNewDisplayName] = useState("")
  const [newRole, setNewRole]         = useState<"admin"|"viewer">("viewer")
  const [showNewPw, setShowNewPw]     = useState(false)
  const [creating, setCreating]       = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const [resetTarget, setResetTarget] = useState<UserRecord | null>(null)
  const [resetPw, setResetPw]         = useState("")
  // RLS attributes editor (department / region / clearance) — see docs/RLS_DESIGN.md
  const [attrTarget, setAttrTarget]   = useState<UserRecord | null>(null)
  const [attrDept, setAttrDept]       = useState("")
  const [attrRegion, setAttrRegion]   = useState("")
  const [attrClear, setAttrClear]     = useState("")
  const [showResetPw, setShowResetPw] = useState(false)
  const [resetting, setResetting]     = useState(false)
  const [resetError, setResetError]   = useState<string | null>(null)

  const [showProfile, setShowProfile] = useState(false)
  const [profileName, setProfileName] = useState("")
  const [ownPw, setOwnPw]             = useState("")
  const [showOwnPw, setShowOwnPw]     = useState(false)
  const [savingProfile, setSavingProfile] = useState(false)
  const [profileMsg, setProfileMsg]   = useState<string | null>(null)

  const fetchUsers = useCallback(async () => {
    if (!isAdmin) { setLoading(false); return }
    setLoading(true)
    try {
      const res = await fetch("/api/auth/users")
      if (res.ok) setUsers(await res.json())
    } finally { setLoading(false) }
  }, [isAdmin])

  useEffect(() => { fetchUsers() }, [fetchUsers])

  const { toast } = useToast()
  const notify = (text: string, ok = true) => toast(text, ok ? "success" : "error")

  const handleCreate = async () => {
    if (!newUsername || !newPassword) return
    const overwriting = users.some(u => u.username === newUsername)
    if (overwriting) {
      const ok = await confirmDialog({
        title: "User already exists",
        message: `A user named '${newUsername}' already exists. Continuing will reset their password — they won't be created as a new user.`,
        destructive: true,
        confirmText: "Reset password",
      })
      if (!ok) return
    }
    setCreating(true); setCreateError(null)
    try {
      const r = await fetch("/api/auth/setup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: newUsername, password: newPassword, display_name: newDisplayName || undefined }),
      })
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail) }
      if (newRole === "admin") {
        const list: UserRecord[] = await (await fetch("/api/auth/users")).json()
        const created = list.find(u => u.username === newUsername)
        if (created) await fetch(`/api/auth/users/${created.id}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role: "admin" }),
        })
      }
      setShowCreate(false); setNewUsername(""); setNewPassword(""); setNewDisplayName(""); setNewRole("viewer")
      notify(overwriting
        ? `Password reset for existing user '${newUsername}'`
        : `User '${newUsername}' created — must change password on first login`)
      fetchUsers()
    } catch (e) { setCreateError(e instanceof Error ? e.message : "Failed") }
    finally { setCreating(false) }
  }

  const handleResetPassword = async () => {
    if (!resetTarget || !resetPw) return
    setResetting(true); setResetError(null)
    try {
      const r = await fetch("/api/auth/setup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: resetTarget.username, password: resetPw }),
      })
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail) }
      setResetTarget(null); setResetPw("")
      notify(`Password reset for '${resetTarget.username}'`)
    } catch (e) { setResetError(e instanceof Error ? e.message : "Failed") }
    finally { setResetting(false) }
  }

  const handleToggleActive = async (u: UserRecord) => {
    await fetch(`/api/auth/users/${u.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !u.is_active }),
    })
    notify(`${u.username} ${!u.is_active ? "activated" : "deactivated"}`)
    fetchUsers()
  }

  const confirmDialog = useConfirm()
  const handleToggleRole = async (u: UserRecord) => {
    const r = u.role === "admin" ? "viewer" : "admin"
    const promoting = r === "admin"
    const ok = await confirmDialog({
      title: promoting ? "Promote to admin" : "Demote to viewer",
      message: promoting
        ? `Grant '${u.username}' full admin access — including user management, governance policies, and all collections.`
        : `Remove admin access from '${u.username}'. They'll keep viewer access.`,
      destructive: promoting,
      confirmText: promoting ? "Promote to admin" : "Demote to viewer",
    })
    if (!ok) return
    await fetch(`/api/auth/users/${u.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: r }),
    })
    notify(`${u.username} role changed to ${r}`)
    fetchUsers()
  }
  const handleDelete = async (u: UserRecord) => {
    if (!(await confirmDialog({ title: "Delete user", message: `Delete user '${u.username}'. This cannot be undone.`, destructive: true, confirmText: "Delete" }))) return
    const r = await fetch(`/api/auth/users/${u.id}`, { method: "DELETE" })
    if (r.ok) { notify(`User '${u.username}' deleted`); fetchUsers() }
    else notify("Failed to delete user", false)
  }

  const openAttrs = (u: UserRecord) => {
    const a = u.attributes || {}
    setAttrDept(a.department || ""); setAttrRegion(a.region || ""); setAttrClear(a.clearance || "")
    setAttrTarget(u)
  }
  const saveAttributes = async () => {
    if (!attrTarget) return
    const attributes: Record<string, string> = { ...(attrTarget.attributes || {}) }
    const setOrDel = (k: string, v: string) => { if (v.trim()) attributes[k] = v.trim(); else delete attributes[k] }
    setOrDel("department", attrDept); setOrDel("region", attrRegion); setOrDel("clearance", attrClear)
    const r = await fetch(`/api/auth/users/${attrTarget.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ attributes }),
    })
    if (r.ok) { notify(`${attrTarget.username} attributes updated`); setAttrTarget(null); fetchUsers() }
    else notify("Failed to update attributes", false)
  }

  const handleSaveProfile = async () => {
    setSavingProfile(true); setProfileMsg(null)
    try {
      if (profileName !== currentUser?.display_name) {
        await fetch("/api/auth/me", {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ display_name: profileName }),
        })
      }
      if (ownPw) {
        const r = await fetch("/api/auth/change-password", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_password: ownPw }),
        })
        if (!r.ok) { const d = await r.json(); throw new Error(d.detail) }
        setOwnPw("")
      }
      setProfileMsg("Profile updated successfully"); setShowProfile(false)
    } catch (e) { setProfileMsg(e instanceof Error ? e.message : "Failed") }
    finally { setSavingProfile(false) }
  }

  return (
    <div className="space-y-4">

      {/* Toolbar */}
      <div className="flex items-center gap-2">
        {isAdmin && (
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <UserPlus className="h-4 w-4 mr-1.5" />New User
          </Button>
        )}
        <Button size="sm" variant="outline"
          onClick={() => { setProfileName(currentUser?.display_name || ""); setOwnPw(""); setProfileMsg(null); setShowProfile(true) }}>
          <KeyRound className="h-4 w-4 mr-1.5" />My Profile
        </Button>
        {isAdmin && (
          <Button size="sm" variant="ghost" className="ml-auto" onClick={fetchUsers}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        )}
      </div>

      {/* Users table */}
      {isAdmin && (
        <Card>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 border-b">
                <tr>
                  <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground">User</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground">Role</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground">Status</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground hidden md:table-cell">Joined</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {loading ? (
                  [...Array(2)].map((_,i) => (
                    <tr key={i}><td colSpan={5} className="px-4 py-3"><Skeleton className="h-8 w-full" /></td></tr>
                  ))
                ) : users.filter(u => u.username).map(u => (
                  <tr key={u.id} className={`hover:bg-muted/20 transition-colors ${!u.is_active ? "opacity-50" : ""}`}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="h-7 w-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                          <span className="text-[11px] font-semibold text-primary">
                            {(u.display_name || u.username || "?")[0].toUpperCase()}
                          </span>
                        </div>
                        <div>
                          <p className="font-medium text-sm leading-tight">
                            {u.display_name || u.username}
                            {u.id === currentUser?.id && <span className="ml-1.5 text-[10px] text-muted-foreground">(you)</span>}
                          </p>
                          <p className="text-[11px] text-muted-foreground">@{u.username}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={u.role === "admin" ? "default" : "secondary"} className="text-[10px] gap-1">
                        {u.role === "admin" && <Shield className="h-2.5 w-2.5" />}
                        {u.role}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      {u.is_active
                        ? <span className="flex items-center gap-1 text-green-600 text-xs"><CheckCircle2 className="h-3.5 w-3.5" />Active</span>
                        : <span className="flex items-center gap-1 text-muted-foreground text-xs"><UserX className="h-3.5 w-3.5" />Inactive</span>}
                      {u.require_password_change && (
                        <span className="text-[10px] text-amber-500 block mt-0.5">Must change password</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground hidden md:table-cell">
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="px-4 py-3">
                      {u.id !== currentUser?.id && (
                        <div className="flex items-center justify-end gap-0.5">
                          <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Reset password" title="Reset password"
                            onClick={() => { setResetTarget(u); setResetPw(""); setResetError(null) }}>
                            <KeyRound className="h-3.5 w-3.5" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-7 w-7"
                            title={u.role === "admin" ? "Demote to viewer" : "Promote to admin"}
                            onClick={() => handleToggleRole(u)}>
                            <Shield className="h-3.5 w-3.5" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-7 w-7"
                            aria-label="RLS attributes (department/region/clearance)" title="RLS attributes (department/region/clearance)"
                            onClick={() => openAttrs(u)}>
                            <SlidersHorizontal className="h-3.5 w-3.5" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-7 w-7"
                            title={u.is_active ? "Deactivate" : "Activate"}
                            onClick={() => handleToggleActive(u)}>
                            {u.is_active ? <UserX className="h-3.5 w-3.5" /> : <UserCheck className="h-3.5 w-3.5" />}
                          </Button>
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive"
                            aria-label="Delete user" title="Delete user" onClick={() => handleDelete(u)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* ── Create User ── */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create New User</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Username <span className="text-destructive">*</span></Label>
                <Input value={newUsername} onChange={e => setNewUsername(e.target.value)} placeholder="username" autoFocus />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Display Name</Label>
                <Input value={newDisplayName} onChange={e => setNewDisplayName(e.target.value)} placeholder="Full Name" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Initial Password <span className="text-destructive">*</span></Label>
              <div className="relative">
                <Input type={showNewPw ? "text" : "password"} value={newPassword}
                  onChange={e => setNewPassword(e.target.value)} placeholder="Min 6 characters" className="pr-9" />
                <button onClick={() => setShowNewPw(v => !v)} tabIndex={-1}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showNewPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p className="text-[11px] text-muted-foreground">User must change password on first login</p>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Role</Label>
              <Select value={newRole} onValueChange={v => setNewRole((v || "viewer") as "admin"|"viewer")}>
                <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="viewer">Viewer — read-only access</SelectItem>
                  <SelectItem value="admin">Admin — full access</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {createError && <ErrorBox msg={createError} />}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!newUsername || !newPassword || creating}>
              {creating ? "Creating…" : "Create User"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Reset Password ── */}
      <Dialog open={!!resetTarget} onOpenChange={o => !o && setResetTarget(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Reset Password — @{resetTarget?.username}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label className="text-xs">New Password <span className="text-destructive">*</span></Label>
              <div className="relative">
                <Input type={showResetPw ? "text" : "password"} value={resetPw}
                  onChange={e => setResetPw(e.target.value)} placeholder="Min 6 characters" className="pr-9" autoFocus />
                <button onClick={() => setShowResetPw(v => !v)} tabIndex={-1}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showResetPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p className="text-[11px] text-muted-foreground">User will be prompted to change password on next login</p>
            </div>
            {resetError && <ErrorBox msg={resetError} />}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetTarget(null)}>Cancel</Button>
            <Button onClick={handleResetPassword} disabled={!resetPw || resetting}>
              {resetting ? "Resetting…" : "Reset Password"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── RLS Attributes (department / region / clearance) ── */}
      <Dialog open={!!attrTarget} onOpenChange={o => !o && setAttrTarget(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>RLS Attributes — @{attrTarget?.username}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <p className="text-[11px] text-muted-foreground">
              Referenced by row-level security (RLS) policies via <code>current_user_attribute(...)</code>. Leave blank to remove an attribute.
            </p>
            <div className="space-y-1.5">
              <Label className="text-xs">Department</Label>
              <Input value={attrDept} onChange={e => setAttrDept(e.target.value)} placeholder="e.g. sales" autoFocus />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Region</Label>
              <Input value={attrRegion} onChange={e => setAttrRegion(e.target.value)} placeholder="e.g. us-east" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Clearance</Label>
              <Input value={attrClear} onChange={e => setAttrClear(e.target.value)} placeholder="e.g. confidential" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAttrTarget(null)}>Cancel</Button>
            <Button onClick={saveAttributes}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── My Profile ── */}
      <Dialog open={showProfile} onOpenChange={setShowProfile}>
        <DialogContent>
          <DialogHeader><DialogTitle>My Profile</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <div className="rounded-lg bg-muted/40 px-3 py-2.5 text-xs">
              <p className="text-muted-foreground">Account: <span className="font-medium text-foreground">@{currentUser?.username}</span></p>
              <p className="text-muted-foreground mt-0.5">Role: <span className="font-medium text-foreground capitalize">{currentUser?.role}</span></p>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Display Name</Label>
              <Input value={profileName} onChange={e => setProfileName(e.target.value)} placeholder="Your full name" autoFocus />
            </div>
            <Separator />
            <div className="space-y-1.5">
              <Label className="text-xs">New Password <span className="text-muted-foreground font-normal">(leave blank to keep current)</span></Label>
              <div className="relative">
                <Input type={showOwnPw ? "text" : "password"} value={ownPw}
                  onChange={e => setOwnPw(e.target.value)} placeholder="New password (optional)" className="pr-9" />
                <button onClick={() => setShowOwnPw(v => !v)} tabIndex={-1}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showOwnPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            {profileMsg && <p className={`text-xs ${profileMsg.includes("success") ? "text-green-600" : "text-destructive"}`}>{profileMsg}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowProfile(false)}>Cancel</Button>
            <Button onClick={handleSaveProfile} disabled={savingProfile}>
              {savingProfile ? "Saving…" : "Save Changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
