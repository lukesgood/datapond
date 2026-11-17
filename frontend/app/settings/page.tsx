"use client"

import { useEffect, useState, useSyncExternalStore, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import NextLink from "next/link"
import { CheckCircle2, Copy, ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorBox } from "@/components/ui/error-box"
import { PageHeader } from "@/components/ui/page-header"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { DataCatalogs } from "@/components/settings/data-catalogs"
import { People } from "@/components/settings/people"
import { useCapabilityStrict, useCapability, useCapabilities } from "@/lib/capabilities"
import { usePermissions } from "@/lib/permissions"
import { permissionState } from "@/lib/permission-state"
import { PermissionUnknown } from "@/components/ui/permission-state"

// Path-hosted services. OpenMetadata / MinIO / Trino are not listed: their web UIs
// don't support sub-path hosting. MLflow/Airflow keep a trailing slash to skip an
// http:// add-slash redirect. `cap` hides a link unless its capability is true.
const SERVICE_URLS = [
  { service: "Console", path: "" },
  { service: "Backend API", path: "/api/health" },
  { service: "JupyterLab", path: "/jupyter", cap: "notebooks" },
  { service: "Airflow", path: "/airflow/", cap: "pipelines" },
  // mlflow_ui, not experiments: MLflow has no authentication, so a deployment can run
  // experiments with its UI kept off the ingress, and then this link would be dead.
  { service: "MLflow", path: "/mlflow/", cap: "mlflow_ui" },
] as const

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" aria-label={`Copy ${text}`}
      onClick={() => { void navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}>
      {copied ? <CheckCircle2 className="h-3 w-3 text-[var(--dp-good-text)]" /> : <Copy className="h-3 w-3 text-muted-foreground" />}
    </Button>
  )
}

const subscribeToClient = () => () => {}

// ?tab=<value> opens that tab. Old names still work: "users" → people, "overview" →
// urls; "service" went to /agents when service accounts moved there.
const TABS = ["people", "catalogs", "security", "urls"] as const
const ALIASES: Record<string, string> = { users: "people", overview: "urls" }

export default function SettingsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <SettingsWorkspace />
    </Suspense>
  )
}

function SettingsWorkspace() {
  const asked = useSearchParams().get("tab")
  const router = useRouter()
  useEffect(() => { if (asked === "service") router.replace("/agents") }, [asked, router])
  const resolved = asked ? ALIASES[asked] ?? asked : null
  const tab = resolved && (TABS as readonly string[]).includes(resolved) ? resolved : "people"
  const setTab = (v: string) => router.replace(v === "people" ? "/settings" : `/settings?tab=${v}`, { scroll: false })

  // Settings is platform administration — admin only (every tab's API is). Personal
  // credentials live on /account.
  const { role, loaded, error, refetch } = usePermissions()
  const isAdmin = role === "admin"
  const access = permissionState({ loaded, error, allowed: isAdmin })

  if (access !== "allowed") {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-16 text-center">
        {access === "unknown" ? <PermissionUnknown onRetry={refetch} /> : (
          <>
            <ShieldCheck className="h-6 w-6 text-muted-foreground" />
            <h2 className="text-lg font-semibold">Needs an administrator</h2>
            <p className="max-w-md text-sm text-muted-foreground">
              Settings is for platform administration. Manage your own password and passkeys in{" "}
              <NextLink className="font-medium text-primary hover:underline" href="/account">Account</NextLink>.
            </p>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1400px] flex-1 space-y-5 p-8 pt-6">
      <PageHeader title="Settings"
        description={<>People, catalogs and sign-in. Workload health is in <NextLink href="/services" className="text-primary hover:underline">Infrastructure</NextLink>; agents and models have their own menus.</>} />
      <Tabs value={tab} onValueChange={v => setTab(String(v))}>
        <TabsList>
          <TabsTrigger value="people">People</TabsTrigger>
          <TabsTrigger value="catalogs">Data catalogs</TabsTrigger>
          <TabsTrigger value="security">Sign-in &amp; security</TabsTrigger>
          <TabsTrigger value="urls">Service URLs</TabsTrigger>
        </TabsList>
        <TabsContent value="people" className="mt-5"><People /></TabsContent>
        <TabsContent value="catalogs" className="mt-5"><DataCatalogs canEdit /></TabsContent>
        <TabsContent value="security" className="mt-5"><SecurityPanel /></TabsContent>
        <TabsContent value="urls" className="mt-5"><ServiceUrls /></TabsContent>
      </Tabs>
    </div>
  )
}

function ServiceUrls() {
  const caps = {
    notebooks: useCapability("notebooks"),
    pipelines: useCapability("pipelines"),
    mlflow_ui: useCapability("mlflow_ui"),
  }
  const mounted = useSyncExternalStore(subscribeToClient, () => true, () => false)
  const reported = useCapabilities().version
  const version = typeof reported === "string" && reported ? reported : "unknown"
  return (
    <div className="max-w-3xl space-y-3">
      <div className="divide-y rounded-xl border bg-card">
        {SERVICE_URLS.filter(s => !("cap" in s) || caps[s.cap]).map(({ service, path }) => {
          const url = mounted ? `${window.location.protocol}//${window.location.host}${path}` : path
          return (
            <div key={service} className="flex items-center gap-3 px-4 py-2.5 text-sm">
              <span className="w-28 shrink-0 text-xs text-muted-foreground">{service}</span>
              <a href={url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate font-mono text-xs text-primary hover:underline">{url}</a>
              <CopyButton text={url} />
            </div>
          )
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        DataPond {version}. Add-on UIs sign in with their own credentials; OpenMetadata, MinIO and Trino need a subdomain or port-forward.
      </p>
    </div>
  )
}

interface SecurityConfig {
  session_hours: number; session_cookie: string; password_hash: string; password_min_length: number
  first_login_change: boolean
  login_lockout: { max_failures: number; lockout_seconds: number; max_lockout_seconds: number }
  roles: { name: string; description: string; permissions: number }[]
  oauth_resource_server: boolean
}

/** What sign-in does here, as the server reports it. It was a hard-coded list that
 *  still said "admin / viewer roles" with seven roles live. */
function SecurityPanel() {
  const sso = useCapabilityStrict("sso")
  const webauthn = useCapabilityStrict("webauthn")
  const rls = useCapabilityStrict("rls")
  const mounted = useSyncExternalStore(subscribeToClient, () => true, () => false)
  const [cfg, setCfg] = useState<SecurityConfig | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetch("/api/auth/security-config")
      .then(async r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(d => { if (!cancelled) { setCfg(d); setErr(null) } })
      .catch(e => { if (!cancelled) setErr(e instanceof Error ? e.message : "Could not read") })
    return () => { cancelled = true }
  }, [attempt])

  const https = mounted && window.location.protocol === "https:"
  const rows: [string, string, "ok" | "warn" | "info"][] = cfg ? [
    ["Session", `${cfg.session_hours} h, in a cookie (${cfg.session_cookie})`, "ok"],
    ["Passwords", `${cfg.password_hash}; at least ${cfg.password_min_length} characters${cfg.first_login_change ? "; changed at first sign-in" : ""}`, "ok"],
    ["Failed sign-ins", `${cfg.login_lockout.max_failures} failures lock the account for ${cfg.login_lockout.lockout_seconds} s, doubling up to ${Math.round(cfg.login_lockout.max_lockout_seconds / 60)} min`, "ok"],
    ["HTTPS", !mounted ? "Checking…" : https ? "This page is served over HTTPS" : "This page is served over plain HTTP: configure TLS at the ingress", https ? "ok" : "warn"],
    ["Single sign-on", sso ? "OIDC sign-in is on" : "Off. LDAP/AD and OIDC are set by environment variables", sso ? "ok" : "info"],
    ["Passkeys", webauthn ? "On: each person adds theirs in Account" : "Off (needs HTTPS and WEBAUTHN settings)", webauthn ? "ok" : "info"],
    ["IdP tokens for tools", cfg.oauth_resource_server ? "Accepted (OAuth resource-server mode)" : "Off: tools use agent keys", "info"],
    ["Row and column policies", rls ? "Enforced on the query API" : "Not enforced on this deployment", rls ? "ok" : "warn"],
  ] : []

  return (
    <div className="flex flex-wrap items-start gap-5">
      <div className="min-w-0 flex-[3_1_480px] space-y-4">
        {err ? <div role="alert"><ErrorBox msg={`Could not read the sign-in settings: ${err}`} action={<Button size="sm" variant="outline" onClick={() => setAttempt(a => a + 1)}>Retry</Button>} /></div>
          : !cfg ? <Skeleton className="h-64" /> : (
          <>
            <div className="divide-y rounded-xl border bg-card">
              {rows.map(([label, note, tone]) => (
                <div key={label} className="flex items-start gap-3 px-4 py-2.5 text-sm">
                  <span aria-hidden className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${tone === "ok" ? "bg-[var(--dp-good)]" : tone === "warn" ? "bg-[var(--dp-warn)]" : "bg-muted-foreground/40"}`} />
                  <span className="w-44 shrink-0 font-medium">{label}</span>
                  <span className="text-muted-foreground">{note}</span>
                </div>
              ))}
            </div>
            <div className="rounded-xl border bg-card">
              <h3 className="border-b px-4 py-2.5 text-sm font-semibold">Roles · {cfg.roles.length}</h3>
              <ul className="divide-y">
                {cfg.roles.map(r => (
                  <li key={r.name} className="flex gap-3 px-4 py-2 text-sm">
                    <span className="w-36 shrink-0 font-mono text-xs">{r.name}</span>
                    <span className="flex-1 text-xs text-muted-foreground">{r.description}</span>
                    <span className="dp-num shrink-0 text-xs text-muted-foreground">{r.permissions} permissions</span>
                  </li>
                ))}
              </ul>
            </div>
          </>
        )}
      </div>
      <aside aria-label="Not covered here" className="min-w-0 flex-[2_1_300px] space-y-3 rounded-xl border bg-muted/40 p-5 text-sm">
        <h4 className="font-semibold">Your responsibility, not reported here</h4>
        <ul className="list-disc space-y-1 pl-4 text-muted-foreground">
          <li>Backing up and rotating ENCRYPTION_KEY</li>
          <li>Kubernetes secret encryption at rest</li>
          <li>NetworkPolicies and runtime hardening</li>
          <li>Pinning and scanning images before production</li>
        </ul>
      </aside>
    </div>
  )
}
