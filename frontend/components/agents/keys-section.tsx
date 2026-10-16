"use client"

import { useState } from "react"
import { Check, Copy, KeyRound, Link2, RotateCw, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"
import {
  DEFAULT_EXPIRY_DAYS, EXPIRY_OPTIONS, choosableScopes, defaultScopes, describeKey, keyRequestBody,
} from "@/lib/service-account-keys"
import { type OAuthMode, oauthLinkView } from "@/lib/service-account-oauth"
import type { AgentDetail, AgentKey } from "@/lib/agents"
import { Section } from "./section"

/** Keys, scopes, expiry, rotation and the OAuth client of one agent. A key is shown
 *  once, at issue or rotation, and is never returned again. */
export function KeysSection({ agent, onChange }: { agent: AgentDetail; onChange: () => void }) {
  const [issued, setIssued] = useState<{ key: string; account: string; note?: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [issuing, setIssuing] = useState(false)
  const [keyName, setKeyName] = useState("")
  const [keyScopes, setKeyScopes] = useState<string[]>([])
  const [keyExpiry, setKeyExpiry] = useState<number | null>(DEFAULT_EXPIRY_DAYS)
  const { toast } = useToast()
  const confirm = useConfirm()
  const a = agent

  const openIssue = () => {
    const choosable = choosableScopes(a.grantable_permissions, a.permissions)
    setIssuing(true)
    setKeyName(`${a.username} key`)
    setKeyScopes(defaultScopes(choosable))
    setKeyExpiry(DEFAULT_EXPIRY_DAYS)
  }

  const submitIssue = async () => {
    if (busy) return
    setBusy(true)
    try {
      const res = await fetch(`/api/service-accounts/${a.id}/keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(keyRequestBody(keyName.trim() || `${a.username} key`, keyScopes, keyExpiry)),
      })
      if (res.ok) {
        const d = await res.json()
        setIssued({ key: d.key, account: a.username })
        setCopied(false)
        setIssuing(false)
        onChange()
      } else {
        const d = await res.json().catch(() => ({}))
        toast(typeof d.detail === "string" ? d.detail : `Could not issue key (HTTP ${res.status})`, "error")
      }
    } finally { setBusy(false) }
  }

  // The old key keeps working for a day so the agent holding it can be switched
  // over first; revoking and re-issuing would break it the moment it happened.
  const rotate = async (key: AgentKey) => {
    setBusy(true)
    try {
      const res = await fetch(`/api/service-accounts/keys/${key.id}/rotate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grace_hours: 24 }),
      })
      const d = await res.json().catch(() => ({}))
      if (res.ok) {
        const until = d.old_key_expires_at ? new Date(d.old_key_expires_at).toLocaleString() : null
        setIssued({
          key: d.key, account: a.username,
          note: until ? `Replaces ${key.key_prefix}…, which keeps working until ${until}.` : undefined,
        })
        setCopied(false)
        onChange()
      } else {
        toast(typeof d.detail === "string" ? d.detail : `Could not rotate key (HTTP ${res.status})`, "error")
      }
    } finally { setBusy(false) }
  }

  const revoke = async (key: AgentKey) => {
    const ok = await confirm({
      title: "Revoke this key?",
      message: `${key.key_prefix}… stops working for this agent (within 30 seconds on every replica). This cannot be undone.`,
      confirmText: "Revoke", destructive: true,
    })
    if (!ok) return
    setBusy(true)
    try {
      const res = await fetch(`/api/service-accounts/keys/${key.id}`, { method: "DELETE" })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        toast(typeof d.detail === "string" ? d.detail : `Could not revoke key (HTTP ${res.status})`, "error")
        return
      }
      onChange()
    } finally { setBusy(false) }
  }

  return (
    <Section
      title="Access keys"
      icon={<KeyRound className="h-4 w-4 text-primary" />}
      description={`${a.rate_limit_per_minute} requests/min per key, per replica`}
    >
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
            {issued.note && <p className="text-xs text-muted-foreground">{issued.note}</p>}
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

      {!issuing && (
        <Button size="sm" variant={a.keys.length === 0 ? "default" : "outline"} className="h-8 gap-1.5 text-xs"
                disabled={busy} onClick={openIssue}>
          <KeyRound className="h-3.5 w-3.5" /> Issue a key
        </Button>
      )}
      {issuing && (
        <div className="rounded-md border p-3 space-y-3 text-sm">
          <div className="space-y-1">
            <Label htmlFor={`key-name-${a.id}`} className="text-xs">Key name</Label>
            <Input id={`key-name-${a.id}`} value={keyName} onChange={e => setKeyName(e.target.value)} maxLength={128} />
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium">Scopes — the key can never do more than the account&apos;s role</p>
            {choosableScopes(a.grantable_permissions, a.permissions).map(scope => (
              <label key={scope} className="flex items-center gap-2 text-xs">
                <Checkbox
                  checked={keyScopes.includes(scope)}
                  onCheckedChange={v => setKeyScopes(prev => v ? [...prev, scope] : prev.filter(s => s !== scope))}
                />
                <code className="font-mono">{scope}</code>
              </label>
            ))}
            {keyScopes.length === 0 && (
              <p className="text-xs text-[var(--dp-warn-text)]">No scopes selected: the key gets every permission of the role.</p>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor={`key-expiry-${a.id}`} className="text-xs">Expires</Label>
            <select id={`key-expiry-${a.id}`} className="rounded-md border bg-background px-2 py-1 text-xs"
                    value={keyExpiry === null ? "never" : String(keyExpiry)}
                    onChange={e => setKeyExpiry(e.target.value === "never" ? null : Number(e.target.value))}>
              {EXPIRY_OPTIONS.map(o => (
                <option key={o.label} value={o.days === null ? "never" : String(o.days)}>{o.label}</option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={submitIssue} disabled={busy}>Issue key</Button>
            <Button size="sm" variant="ghost" onClick={() => setIssuing(false)} disabled={busy}>Cancel</Button>
          </div>
        </div>
      )}

      <OAuthClientRow account={a} mode={a.oauth} onChange={onChange} />
      {a.keys.length === 0 ? (
        <p className="text-xs text-muted-foreground">No keys issued.</p>
      ) : (
        <ul className="space-y-1">
          {a.keys.map(k => (
            <li key={k.id} className="flex items-center justify-between gap-2 text-xs">
              <span className="flex items-center gap-2 truncate">
                <code className="font-mono">{k.key_prefix}…</code>
                <span className="text-muted-foreground truncate">
                  {k.name}
                  <span className="block text-2xs text-muted-foreground">{describeKey(k)}</span>
                </span>
                {k.status !== "active" && (
                  <Badge variant="outline" className="text-2xs">{k.status}</Badge>
                )}
              </span>
              <span className="flex shrink-0 items-center gap-2 text-muted-foreground">
                {k.last_used_at
                  ? `used ${new Date(k.last_used_at).toLocaleDateString()}`
                  : "never used"}
                {k.status === "active" && (
                  <button
                    onClick={() => rotate(k)}
                    disabled={busy}
                    aria-label="Rotate key"
                    title="Issue a replacement; this key keeps working for 24 hours"
                    className="text-muted-foreground hover:text-foreground"
                  >
                    <RotateCw className="h-3.5 w-3.5" />
                  </button>
                )}
                {k.status === "active" && (
                  <button
                    onClick={() => revoke(k)}
                    disabled={busy}
                    aria-label="Revoke key"
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}


/** Link the agent's own IdP client to this account, so it can call with a
 *  client-credentials token instead of a DataPond key. */
function OAuthClientRow({ account, mode, onChange }: {
  account: AgentDetail; mode: OAuthMode | undefined; onChange: () => void
}) {
  const view = oauthLinkView(mode, account.oauth_client)
  const [clientId, setClientId] = useState("")
  const [saving, setSaving] = useState(false)
  const { toast } = useToast()

  const send = async (method: "PUT" | "DELETE") => {
    setSaving(true)
    try {
      const res = await fetch(`/api/service-accounts/${account.id}/oauth-client`, {
        method,
        headers: method === "PUT" ? { "Content-Type": "application/json" } : undefined,
        body: method === "PUT" ? JSON.stringify({ client_id: clientId.trim() }) : undefined,
      })
      if (res.ok) {
        setClientId("")
        onChange()
      } else {
        const d = await res.json().catch(() => ({}))
        toast(typeof d.detail === "string" ? d.detail : `Could not update the OAuth client (HTTP ${res.status})`, "error")
      }
    } finally { setSaving(false) }
  }

  return (
    <div className="space-y-1.5 rounded-md border px-3 py-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-1.5 font-medium">
          <Link2 className="h-3.5 w-3.5 text-muted-foreground" /> OAuth client
        </span>
        {view.clientId && <code className="font-mono">{view.clientId}</code>}
        {view.state === "linked" && <Badge variant="secondary" className="text-2xs">linked</Badge>}
        {view.state === "stale" && <Badge variant="outline" className="text-2xs text-[var(--dp-warn-text)]">stale</Badge>}
        {view.state === "unlinked" && <span className="text-muted-foreground">not linked</span>}
        {view.canUnlink && (
          <Button size="sm" variant="ghost" className="h-7 text-xs" disabled={saving}
                  onClick={() => send("DELETE")}>
            Unlink
          </Button>
        )}
      </div>
      {view.state === "linked" && mode?.issuer && (
        <p className="text-muted-foreground">
          Client-credentials tokens from <code className="font-mono">{mode.issuer}</code> for this client act as this account.
        </p>
      )}
      {view.note && (
        <p className={view.state === "stale" ? "text-[var(--dp-warn-text)]" : "text-muted-foreground"}>{view.note}</p>
      )}
      {view.canLink && (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={clientId}
            onChange={e => setClientId(e.target.value)}
            placeholder="IdP client id (e.g. Entra application id)"
            aria-label={`OAuth client id for ${account.username}`}
            maxLength={512}
            className="h-8 max-w-xs text-xs"
          />
          <Button size="sm" variant="outline" className="h-8 text-xs"
                  disabled={saving || !clientId.trim()} onClick={() => send("PUT")}>
            Link
          </Button>
        </div>
      )}
    </div>
  )
}
