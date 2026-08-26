"use client"

import { useCallback, useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Loader2, Bot, KeyRound, Trash2, Copy, Check } from "lucide-react"

type ApiKey = {
  id: string; name: string; key_prefix: string; status: string
  scopes: string[]; expires_at: string | null; last_used_at: string | null
}
type Account = {
  id: string; username: string; display_name: string; role: string
  permissions: string[]; keys: ApiKey[]
}
type Payload = { accounts: Account[]; assignable_roles: string[] }

/** Service accounts give an app or agent an identity of its own.
 *
 *  Without one, an AI application has to carry a person's token — which expires in a
 *  day, cannot be revoked without disabling that person, and makes spend attribution
 *  and the audit log point at the wrong actor.
 */
export function ServiceAccounts() {
  const [data, setData] = useState<Payload | null>(null)
  const [loading, setLoading] = useState(true)
  const [newName, setNewName] = useState("")
  const [newRole, setNewRole] = useState("ai_engineer")
  const [issued, setIssued] = useState<{ key: string; account: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch("/api/service-accounts")
      if (res.ok) setData(await res.json())
    } finally {
      setLoading(false)
    }
  }, [])

  // A fetch on mount that shows a spinner while it runs. `load` sets `loading`
  // before its first await, which the rule reads as a synchronous setState — the
  // cascade it guards against does not happen here, because `loading` starts true
  // and the initial set is a no-op.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  const createAccount = async () => {
    if (!newName.trim() || busy) return
    setBusy(true)
    try {
      const res = await fetch("/api/service-accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim(), role: newRole }),
      })
      if (res.ok) { setNewName(""); await load() }
    } finally { setBusy(false) }
  }

  const issueKey = async (account: Account) => {
    setBusy(true)
    try {
      const res = await fetch(`/api/service-accounts/${account.id}/keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: `${account.username} key`, scopes: [] }),
      })
      if (res.ok) {
        const d = await res.json()
        setIssued({ key: d.key, account: account.username })
        setCopied(false)
        await load()
      }
    } finally { setBusy(false) }
  }

  const revoke = async (keyId: string) => {
    setBusy(true)
    try {
      await fetch(`/api/service-accounts/keys/${keyId}`, { method: "DELETE" })
      await load()
    } finally { setBusy(false) }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading service accounts…
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {issued && (
        <Card className="border-primary">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">
              Key issued for {issued.account}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Copy it now. It is stored only as a hash and cannot be shown again.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 truncate rounded border bg-muted px-2 py-1.5 font-mono text-xs">
                {issued.key}
              </code>
              <Button
                size="sm" variant="outline" className="h-8 gap-1.5 text-xs"
                onClick={() => {
                  void navigator.clipboard.writeText(issued.key)
                  setCopied(true)
                }}
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "Copied" : "Copy"}
              </Button>
              <Button size="sm" variant="ghost" className="h-8 text-xs"
                      onClick={() => setIssued(null)}>Done</Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Send it as <code className="font-mono">Authorization: Bearer &lt;key&gt;</code>.
            </p>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <Bot className="h-4 w-4 text-muted-foreground" />
            New service account
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="e.g. support-assistant"
              className="h-9 max-w-xs text-sm"
            />
            <select
              value={newRole}
              onChange={e => setNewRole(e.target.value)}
              className="h-9 rounded-md border bg-background px-2 text-sm"
            >
              {(data?.assignable_roles ?? ["ai_engineer"]).map(r => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <Button size="sm" className="h-9 text-xs" disabled={busy || !newName.trim()}
                    onClick={createAccount}>
              Create
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Cannot sign in to this UI, and never holds <code className="font-mono">user:manage</code>{" "}
            or <code className="font-mono">settings:write</code> whatever role it is given.
          </p>
        </CardContent>
      </Card>

      {(data?.accounts ?? []).length === 0 ? (
        <p className="px-1 text-sm text-muted-foreground">
          No service accounts yet. An app using a person&apos;s token inherits that
          person&apos;s access and reports their name in spend and audit records.
        </p>
      ) : (
        data!.accounts.map(a => (
          <Card key={a.id}>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-sm font-medium">
                  {a.display_name}
                  <span className="ml-2 font-mono text-xs text-muted-foreground">
                    {a.username}
                  </span>
                </CardTitle>
                <div className="flex items-center gap-2">
                  {/* What this application has cost. The question a developer has is
                      not "what have I spent" but "what is my integration spending",
                      and the integration is this account — a distinct user id, so its
                      spend is exactly measurable. */}
                  <AccountSpend accountId={a.id} />
                  <Badge variant="secondary">{a.role}</Badge>
                  <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs"
                          disabled={busy} onClick={() => issueKey(a)}>
                    <KeyRound className="h-3.5 w-3.5" /> Issue key
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-1">
                {a.permissions.map(p => (
                  <span key={p} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                    {p}
                  </span>
                ))}
              </div>
              {a.keys.length === 0 ? (
                <p className="text-xs text-muted-foreground">No keys issued.</p>
              ) : (
                <ul className="space-y-1">
                  {a.keys.map(k => (
                    <li key={k.id} className="flex items-center justify-between gap-2 text-xs">
                      <span className="flex items-center gap-2 truncate">
                        <code className="font-mono">{k.key_prefix}…</code>
                        <span className="text-muted-foreground truncate">{k.name}</span>
                        {k.status !== "active" && (
                          <Badge variant="outline" className="text-[10px]">{k.status}</Badge>
                        )}
                      </span>
                      <span className="flex shrink-0 items-center gap-2 text-muted-foreground">
                        {k.last_used_at
                          ? `used ${new Date(k.last_used_at).toLocaleDateString()}`
                          : "never used"}
                        {k.status === "active" && (
                          <button
                            onClick={() => revoke(k.id)}
                            disabled={busy}
                            aria-label="Revoke key"
                            className="text-muted-foreground hover:text-red-600"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        ))
      )}
    </div>
  )
}


function AccountSpend({ accountId }: { accountId: string }) {
  const [s, setS] = useState<{ spend: number; requests: number } | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/service-accounts/${accountId}/usage`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (!cancelled && d) setS({ spend: d.spend, requests: d.requests }) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [accountId])

  if (!s) return null
  return (
    <span className="text-[11px] tabular-nums text-muted-foreground">
      {s.requests === 0
        ? "no calls yet"
        : `${s.requests} call${s.requests === 1 ? "" : "s"} · $${s.spend.toFixed(s.spend >= 0.01 ? 4 : 6)}`}
    </span>
  )
}
