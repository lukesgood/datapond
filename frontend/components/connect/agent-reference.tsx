"use client"

/** How an application or agent calls this deployment: the MCP endpoint, the document
 *  an agent gateway registers, and the REST surface. Reference material, shown in the
 *  integration guide (app/help/integrate); issuing the key is on the Agents page.
 * Everything is read from the running server, so it stays true as the API
 *  changes. */
import { useEffect, useState, useSyncExternalStore } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Loader2, Play, Terminal } from "lucide-react"

type Endpoint = {
  path: string
  method: string
  summary: string
  permission: string | null
  example: Record<string, unknown> | null
}

const noSubscribe = () => () => {}
/** This deployment's origin for the curl examples; empty during server render. */
export function useOrigin() {
  return useSyncExternalStore(noSubscribe, () => window.location.origin, () => "")
}

export function McpCard() {
  const origin = useOrigin()
  const base = origin || "https://your-deployment"
  const curl = `curl -sX POST ${base}/api/mcp \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Terminal className="h-4 w-4 text-primary" />MCP
        </CardTitle>
        <CardDescription>
          Model Context Protocol at <code className="font-mono">POST /api/mcp</code>: search,
          cited answers, approved metrics, the catalog and governed SQL as read-only
          tools, for an agent that discovers its tools instead of being wired to them by
          hand. <code className="font-mono">tools/list</code> answers with exactly the
          tools the calling key may use. Same service-account key as the REST endpoints.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <pre className="overflow-x-auto rounded border bg-muted/40 p-2 font-mono text-2xs leading-relaxed">
{curl}
        </pre>
        <p className="text-2xs text-muted-foreground">
          Scopes, spend attribution and what a call refuses: <span className="font-mono">docs/MCP.md</span>.
        </p>
      </CardContent>
    </Card>
  )
}

/** An agent gateway (AgentCore Gateway and the like) registers REST tools from an
 *  OpenAPI document, but refuses the anyOf the full spec is full of. This one is
 *  generated for exactly that, and lists only the tools the fetching key can call. */
export function GatewayCard() {
  const origin = useOrigin()
  const base = origin || "https://your-deployment"
  const [busy, setBusy] = useState(false)
  const curl = `curl -s ${base}/api/tools/openapi.json \
  -H "Authorization: Bearer $DATAPOND_KEY" > datapond-tools.json`

  const download = async () => {
    setBusy(true)
    try {
      const res = await fetch("/api/tools/openapi.json")
      if (!res.ok) return
      const url = URL.createObjectURL(new Blob([await res.text()], { type: "application/json" }))
      const a = document.createElement("a")
      a.href = url
      a.download = "datapond-tools.json"
      a.click()
      URL.revokeObjectURL(url)
    } finally { setBusy(false) }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Terminal className="h-4 w-4 text-primary" />Behind an agent gateway
        </CardTitle>
        <CardDescription>
          Optional. If your agents reach tools through a gateway such as AgentCore
          Gateway, register this OpenAPI 3.0 document as its target: search, cited answers
          and SQL as four tools, with no schema composition a gateway would refuse.
          Fetch it with the agent&apos;s key to get only the tools that key can call, and
          configure the same key as the gateway&apos;s outbound API-key credential.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <pre className="overflow-x-auto rounded border bg-muted/40 p-2 font-mono text-2xs leading-relaxed">
{curl}
        </pre>
        <Button size="sm" variant="outline" className="h-8 text-xs" disabled={busy} onClick={download}>
          Download for my account
        </Button>
        <p className="text-2xs text-muted-foreground">
          Behind a gateway, every agent that shares a key is one caller to DataPond. Give
          each agent its own service account to keep access, audit and spend per agent.
        </p>
      </CardContent>
    </Card>
  )
}

/** The REST surface, generated from the running routes (GET /api/api-surface), with a
 *  curl for each and a Send that runs it with the browser session. */
export function EndpointsCard() {
  const [endpoints, setEndpoints] = useState<Endpoint[] | null>(null)
  const [refused, setRefused] = useState(false)
  const origin = useOrigin()

  useEffect(() => {
    fetch("/api/api-surface")
      .then(async r => {
        if (r.status === 403) { setRefused(true); setEndpoints([]); return }
        setEndpoints(r.ok ? ((await r.json()).endpoints || []) : [])
      })
      .catch(() => setEndpoints([]))
  }, [])

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Terminal className="h-4 w-4 text-primary" />REST endpoints
        </CardTitle>
        <CardDescription>
          {endpoints === null ? "Loading…"
            : refused ? "Listing the endpoints needs the ai:generate permission."
            : `${endpoints.length} endpoints an application can call, with the permission each requires.`}
          {" "}The full reference, including the operational and administrative routes, is at{" "}
          <a href="/api/docs" target="_blank" rel="noreferrer"
             className="font-medium text-primary hover:underline">/api/docs</a>.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {endpoints === null && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        {(endpoints ?? []).map(e => (
          <EndpointRow key={`${e.method} ${e.path}`} e={e} origin={origin} />
        ))}
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
        <span className={`w-14 shrink-0 rounded px-1.5 py-0.5 text-center font-mono text-2xs font-semibold ${
          e.method === "GET" ? "bg-primary/10 text-primary"
            : e.method === "DELETE" ? "bg-destructive/10 text-destructive"
            : "bg-[var(--dp-warn)]/10 text-[var(--dp-warn-text)]"}`}>
          {e.method}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-xs">{e.path}</span>
        {e.permission && (
          <code className="hidden shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-2xs text-muted-foreground sm:block">
            {e.permission}
          </code>
        )}
      </button>

      {open && (
        <div className="space-y-2 border-t px-3 py-2.5">
          {e.summary && <p className="text-xs text-muted-foreground">{e.summary}</p>}

          <div>
            <span className="text-2xs font-medium">curl</span>
            <pre className="mt-1 overflow-x-auto rounded border bg-muted/40 p-2 font-mono text-2xs leading-relaxed">
{curl}
            </pre>
          </div>

          {templated ? (
            <p className="text-2xs text-muted-foreground">
              This path takes a value in the URL, so it is not runnable from here —
              the curl above shows the shape.
            </p>
          ) : (
            <>
              {hasBody && (
                <div>
                  <span className="text-2xs font-medium">Request body</span>
                  <textarea value={body} onChange={ev => setBody(ev.target.value)} rows={5}
                            spellCheck={false}
                            className="mt-1 w-full rounded border bg-background p-2 font-mono text-2xs" />
                </div>
              )}
              <div className="flex items-center gap-2">
                <Button size="sm" className="h-7 gap-1.5 text-xs" disabled={busy} onClick={() => void run()}>
                  {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                  Send
                </Button>
                <span className="text-2xs text-muted-foreground">
                  Runs with your browser session, not an API key — same request and
                  response, no credential to paste in.
                </span>
              </div>
            </>
          )}

          {res && (
            <div>
              <span className="text-2xs font-medium">
                Response <span className={res.status >= 400 || res.status === 0 ? "text-destructive" : "text-[var(--dp-good-text)]"}>
                  {res.status || "error"}
                </span>
              </span>
              <pre className="mt-1 max-h-64 overflow-auto rounded border bg-muted/40 p-2 font-mono text-2xs leading-relaxed">
{res.text}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
