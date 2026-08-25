"use client"

import { useCallback, useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useHasPermission } from "@/lib/permissions"
import { Loader2, ShieldAlert, Terminal } from "lucide-react"
import { MySpend } from "@/components/ai/my-spend"
import { ServiceAccounts } from "@/components/settings/service-accounts"
import { getUser } from "@/lib/auth"

/** How an application calls this deployment.
 *
 *  The product's stated audience is teams building AI applications on top of it, and
 *  the path for them was: ask an administrator for a service account, read a one-line
 *  hint about the Authorization header, then work out the request shape from nothing.
 *
 *  Gated on ai:generate rather than knowledge:read. knowledge:read includes viewer,
 *  business_analyst, data_engineer and auditor — none of whom are writing an
 *  application against the retrieval API. The three roles that hold ai:generate are
 *  exactly the ones who are.
 */
export default function ConnectPage() {
  const canUse = useHasPermission("ai:generate")
  // Issuing a credential is an administrator action — every /service-accounts route
  // is require_admin. So this page is two things depending on who opens it: the
  // place an administrator creates and revokes the key an application uses, and for
  // everyone else the request to make, with the exact scopes to ask for. What it
  // must not be is a create button that 403s.
  const [isAdmin] = useState(() => getUser()?.role === "admin")
  const [collections, setCollections] = useState<string[]>([])
  const [picked, setPicked] = useState("")
  const [loading, setLoading] = useState(true)
  const [origin, setOrigin] = useState("")

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/ai/collections")
      const d = await r.json()
      const names = (Array.isArray(d) ? d : d.collections || [])
        .map((c: { name?: string }) => c?.name).filter(Boolean) as string[]
      setCollections(names)
      setPicked(p => p || names[0] || "")
    } catch { /* the snippets still render with a placeholder */ } finally {
      setLoading(false)
    }
  }, [])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setOrigin(window.location.origin) }, [])
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  if (!canUse) {
    return (
      <div className="flex-1 p-8 pt-6">
        <div className="flex flex-col items-center gap-3 rounded-lg border bg-muted/30 p-16 text-center">
          <ShieldAlert className="h-6 w-6 text-muted-foreground" />
          <h2 className="text-lg font-semibold">Not available for your role</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            This page is for calling the retrieval API from an application, which needs
            the permission to spend model tokens.
          </p>
        </div>
      </div>
    )
  }

  const base = origin || "https://your-deployment"
  const name = picked || "your-collection"

  return (
    <div className="flex-1 space-y-5 p-8 pt-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">Build AI</p>
        <h1 className="mt-0.5 text-[23px] font-semibold tracking-tight">Connect your app</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Call the same retrieval and cited-answer endpoints this UI uses, from your
          own application.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Terminal className="h-4 w-4 text-primary" />Endpoints
          </CardTitle>
          <CardDescription>
            Against{" "}
            {loading ? <Loader2 className="inline h-3 w-3 animate-spin" /> : (
              collections.length > 0 ? (
                <select value={picked} onChange={e => setPicked(e.target.value)}
                        className="rounded border bg-background px-1.5 py-0.5 font-mono text-xs">
                  {collections.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              ) : <span className="font-mono text-xs">your-collection</span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Snippet label="Search — the chunks, with scores" code={`curl -sX POST ${base}/api/ai/search \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"collection":"${name}","query":"your question","k":8}'`} />

          <Snippet label="Cited answer — prose plus the sources it used" code={`curl -sX POST ${base}/api/ai/rag \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"collection":"${name}","question":"your question","k":5}'`} />

          <Snippet label="Python" code={`import os, httpx

r = httpx.post(
    "${base}/api/ai/rag",
    headers={"Authorization": f"Bearer {os.environ['DATAPOND_KEY']}"},
    json={"collection": "${name}", "question": "your question", "k": 5},
    timeout=60,
)
answer = r.json()
print(answer["answer"])
for c in answer.get("citations", []):
    print(" -", c.get("source"))`} />
        </CardContent>
      </Card>

      {isAdmin ? (
        <ServiceAccounts />
      ) : (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Getting a key</CardTitle>
            <CardDescription>
              Issuing credentials is an administrator action, so this is what to ask for.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p className="text-muted-foreground">
              Ask an administrator for a <b>service account</b> with these scopes:
            </p>
            <div className="flex flex-wrap gap-1.5">
              {["knowledge:read", "ai:generate"].map(scope => (
                <code key={scope} className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{scope}</code>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              The key is shown once, at creation. It is sent as{" "}
              <code className="font-mono">Authorization: Bearer &lt;key&gt;</code>, the same
              header as the examples above. A service account cannot use the assistant
              panel or change settings, whatever scopes it is given.
            </p>
          </CardContent>
        </Card>
      )}

      <MySpend />
    </div>
  )
}

function Snippet({ label, code }: { label: string; code: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium">{label}</span>
        <button
          onClick={() => { void navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
          className="text-[11px] text-muted-foreground hover:text-foreground">
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto rounded-lg border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed">
{code}
      </pre>
    </div>
  )
}
