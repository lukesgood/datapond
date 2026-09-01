"use client"

import { useCallback, useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useHasPermission, usePermissions } from "@/lib/permissions"
import { permissionState } from "@/lib/permission-state"
import { PermissionUnknown } from "@/components/ui/permission-state"
import { ServiceAccounts } from "@/components/settings/service-accounts"
import { Loader2, Play, ShieldAlert, Terminal } from "lucide-react"

type Endpoint = {
  path: string
  method: string
  summary: string
  permission: string | null
  example: Record<string, unknown> | null
}

/** Everything an application needs to call this deployment, and nothing else.
 *
 *  It was three things stapled together — a hand-typed endpoint list, credential
 *  management, and the signed-in person's own spend — and the endpoint list was the
 *  worst of them: three paths, typed, against a surface of fourteen that changes.
 *  The list is generated from the running routes now, including the permission each
 *  guard enforces, so it cannot drift from what the server does.
 *
 *  Calls run with the browser session rather than an API key. The request and
 *  response are identical either way, and a page that asks someone to paste a
 *  long-lived credential into a form is the wrong habit to teach.
 */
export default function ApiPage() {
  const { role, loaded, error, refetch } = usePermissions()
  const canUse = useHasPermission("ai:generate")
  // Service account issuance (components/settings/service-accounts.tsx) is
  // require_admin on the backend (backend/app/api/service_account_routes.py) — a
  // role, not a permission — so this reads the role itself rather than a
  // fabricated permission name, sourced from /api/me/permissions like canUse is.
  const isAdmin = role === "admin"
  const [endpoints, setEndpoints] = useState<Endpoint[]>([])
  const [loading, setLoading] = useState(true)
  const [origin, setOrigin] = useState("")

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/api-surface")
      if (r.ok) setEndpoints((await r.json()).endpoints || [])
    } catch { /* the page still renders the credential half */ } finally {
      setLoading(false)
    }
  }, [])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setOrigin(window.location.origin) }, [])
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  const access = permissionState({ loaded, error, allowed: canUse })
  if (access !== "allowed") {
    return (
      <div className="flex-1 p-8 pt-6">
        <div className="flex flex-col items-center gap-3 rounded-lg border bg-muted/30 p-16 text-center">
          {access === "unknown" ? (
            <PermissionUnknown onRetry={refetch} />
          ) : (
            <>
              <ShieldAlert className="h-6 w-6 text-muted-foreground" />
              <h2 className="text-lg font-semibold">Not available for your role</h2>
              <p className="max-w-md text-sm text-muted-foreground">
                This page is for calling the API from an application, which needs the
                permission to spend model tokens.
              </p>
            </>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-5 p-8 pt-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">Build AI</p>
        <h1 className="mt-0.5 text-[23px] font-semibold tracking-tight">API</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Call this deployment from your own application. Everything below is read from
          the running server, so it stays true as the API changes.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Terminal className="h-4 w-4 text-primary" />Endpoints
          </CardTitle>
          <CardDescription>
            {loading ? "Loading…" : `${endpoints.length} endpoints an application can call, with the permission each requires.`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
          {endpoints.map(e => (
            <EndpointRow key={`${e.method} ${e.path}`} e={e} origin={origin} />
          ))}
        </CardContent>
      </Card>

      {isAdmin ? <ServiceAccounts /> : <AskForAKey />}
    </div>
  )
}

function AskForAKey() {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Getting a key</CardTitle>
        <CardDescription>
          Issuing credentials is an administrator action, so this is what to ask for.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p className="text-muted-foreground">
          Ask an administrator for a <b>service account</b> with the scopes the
          endpoints above say they need — commonly:
        </p>
        <div className="flex flex-wrap gap-1.5">
          {["knowledge:read", "ai:generate"].map(scope => (
            <code key={scope} className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{scope}</code>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          The key is shown once, at creation, and is sent as{" "}
          <code className="font-mono">Authorization: Bearer &lt;key&gt;</code>. A service
          account cannot use the assistant panel or change settings, whatever scopes it
          is given.
        </p>
      </CardContent>
    </Card>
  )
}

function EndpointRow({ e, origin }: { e: Endpoint; origin: string }) {
  const [open, setOpen] = useState(false)
  const [body, setBody] = useState(() => JSON.stringify(e.example ?? {}, null, 2))
  const [res, setRes] = useState<{ status: number; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const base = origin || "https://your-deployment"
  const hasBody = e.method !== "GET" && e.method !== "DELETE"
  const path = e.path.replace(/\{[^}]+\}/g, "…")
  const templated = path !== e.path

  const run = async () => {
    setBusy(true); setRes(null)
    try {
      const r = await fetch(e.path, {
        method: e.method,
        headers: hasBody ? { "Content-Type": "application/json" } : undefined,
        body: hasBody ? body : undefined,
      })
      const text = await r.text()
      setRes({ status: r.status, text: text.slice(0, 4000) })
    } catch (err) {
      setRes({ status: 0, text: err instanceof Error ? err.message : "request failed" })
    } finally {
      setBusy(false)
    }
  }

  const curl = hasBody
    ? `curl -sX ${e.method} ${base}${e.path} \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify(e.example ?? {})}'`
    : `curl -s${e.method === "GET" ? "" : `X ${e.method}`} ${base}${e.path} \\
  -H "Authorization: Bearer $DATAPOND_KEY"`

  return (
    <div className="rounded-lg border">
      <button onClick={() => setOpen(o => !o)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/40">
        <span className={`w-14 shrink-0 rounded px-1.5 py-0.5 text-center font-mono text-[10px] font-semibold ${
          e.method === "GET" ? "bg-primary/10 text-primary"
            : e.method === "DELETE" ? "bg-destructive/10 text-destructive"
            : "bg-amber-500/10 text-amber-700 dark:text-amber-400"}`}>
          {e.method}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-xs">{e.path}</span>
        {e.permission && (
          <code className="hidden shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground sm:block">
            {e.permission}
          </code>
        )}
      </button>

      {open && (
        <div className="space-y-2 border-t px-3 py-2.5">
          {e.summary && <p className="text-xs text-muted-foreground">{e.summary}</p>}

          <div>
            <span className="text-[11px] font-medium">curl</span>
            <pre className="mt-1 overflow-x-auto rounded border bg-muted/40 p-2 font-mono text-[10px] leading-relaxed">
{curl}
            </pre>
          </div>

          {templated ? (
            <p className="text-[11px] text-muted-foreground">
              This path takes a value in the URL, so it is not runnable from here —
              the curl above shows the shape.
            </p>
          ) : (
            <>
              {hasBody && (
                <div>
                  <span className="text-[11px] font-medium">Request body</span>
                  <textarea value={body} onChange={ev => setBody(ev.target.value)} rows={5}
                            spellCheck={false}
                            className="mt-1 w-full rounded border bg-background p-2 font-mono text-[11px]" />
                </div>
              )}
              <div className="flex items-center gap-2">
                <Button size="sm" className="h-7 gap-1.5 text-xs" disabled={busy} onClick={() => void run()}>
                  {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                  Send
                </Button>
                <span className="text-[10px] text-muted-foreground">
                  Runs with your browser session, not an API key — same request and
                  response, no credential to paste in.
                </span>
              </div>
            </>
          )}

          {res && (
            <div>
              <span className="text-[11px] font-medium">
                Response <span className={res.status >= 400 || res.status === 0 ? "text-destructive" : "text-[var(--dp-good)]"}>
                  {res.status || "error"}
                </span>
              </span>
              <pre className="mt-1 max-h-64 overflow-auto rounded border bg-muted/40 p-2 font-mono text-[10px] leading-relaxed">
{res.text}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
