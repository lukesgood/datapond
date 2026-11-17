"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { AlertCircle, Bot, Check, Copy, Loader2, Plus, RefreshCw } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { PermissionGate } from "@/components/ui/permission-state"
import { formatUsd } from "@/lib/format-usd"
import {
  agentStatus, createAgentBody, joinAgentRows, lastUsed, PII_MODE_TEXT,
  type Agent, type AgentPreset, type AgentRow, type Budget, type ByActor, type PiiMode,
} from "@/lib/agents"

const TONE = {
  ok: "text-[var(--dp-good-text)]",
  warn: "text-[var(--dp-warn-text)]",
  bad: "text-destructive",
} as const

export default function AgentsPage() {
  return (
    <PermissionGate permission="user:manage" label="Agents">
      <AgentsList />
    </PermissionGate>
  )
}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

function AgentsList() {
  const [agents, setAgents] = useState<Agent[] | null>(null)
  const [roles, setRoles] = useState<string[]>([])
  const [presets, setPresets] = useState<AgentPreset[]>([])
  const [summary, setSummary] = useState<ByActor[] | null>(null)
  const [budgets, setBudgets] = useState<Budget[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)

  // The three sources load independently: the list is the page, the other two only
  // fill columns, so a failed audit or gateway read shows "—" and nothing else.
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    const since = new Date(Date.now() - 24 * 3_600_000).toISOString()
    const [acc, sum, bud] = await Promise.allSettled([
      getJson<{ accounts: Agent[]; assignable_roles: string[]; presets?: AgentPreset[] }>("/api/service-accounts"),
      getJson<{ by_actor: ByActor[] }>(`/api/audit/tool-calls/summary?since=${encodeURIComponent(since)}`),
      getJson<{ customers?: Budget[]; unavailable?: string | null }>("/api/settings/ai/budgets"),
    ])
    if (acc.status === "fulfilled") {
      setAgents(acc.value.accounts); setRoles(acc.value.assignable_roles ?? [])
      setPresets(acc.value.presets ?? [])
    } else {
      setError(acc.reason instanceof Error ? acc.reason.message : "Could not load agents")
    }
    setSummary(sum.status === "fulfilled" ? sum.value.by_actor : null)
    // `unavailable` means the gateway could not be read: no caps known, not "no spend".
    setBudgets(bud.status === "fulfilled" && !bud.value.unavailable ? (bud.value.customers ?? []) : null)
    setLoading(false)
  }, [])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  const rows = agents ? joinAgentRows(agents, summary, budgets) : []

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-5 px-6 py-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Agents</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              One identity per application or agent: its keys, what it may read, what it spends
              and what it called.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="gap-1.5" onClick={load} disabled={loading}>
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />Refresh
            </Button>
            <Button size="sm" className="gap-1.5" onClick={() => setCreating(true)} disabled={!agents}>
              <Plus className="h-3.5 w-3.5" />New agent
            </Button>
          </div>
        </div>

        {loading && !agents ? (
          <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />Loading agents…
          </div>
        ) : error ? (
          <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />{error}
            <button className="ml-auto underline" onClick={load}>Retry</button>
          </div>
        ) : rows.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
              <Bot className="h-6 w-6 text-muted-foreground" />
              <p className="max-w-md text-sm text-muted-foreground">
                No agents yet. An application using a person&apos;s token inherits that person&apos;s
                access and reports their name in spend and audit records.
              </p>
              <Button size="sm" onClick={() => setCreating(true)}>New agent</Button>
            </CardContent>
          </Card>
        ) : (
          <>
            <AgentTable rows={rows} />
            {(summary === null || budgets === null) && (
              <p className="text-2xs text-muted-foreground">
                {summary === null && "Call counts could not be read. "}
                {budgets === null && "Spend could not be read from the model gateway. "}
                Those columns show — rather than zero.
              </p>
            )}
          </>
        )}
      </div>
      {creating && <NewAgentDialog roles={roles} presets={presets} onClose={() => setCreating(false)} />}
    </div>
  )
}

function AgentTable({ rows }: { rows: AgentRow[] }) {
  const now = new Date()
  const num = (n: number | null) => (n === null ? "—" : n)
  return (
    <div className="divide-y rounded-lg border text-xs">
      <div className="hidden grid-cols-[1.6fr_7rem_8rem_6rem_4.5rem_4.5rem_9rem] gap-3 px-3 py-1.5 text-2xs text-muted-foreground md:grid">
        <span>Name</span><span>Role</span><span>Status</span><span>Last used</span>
        <span className="text-right">Calls 24h</span><span className="text-right">Refused 24h</span>
        <span className="text-right">Spend / cap</span>
      </div>
      {rows.map(a => {
        const st = agentStatus(a, now)
        const used = lastUsed(a)
        return (
          <Link key={a.id} href={`/agents/${a.id}`}
                className="grid grid-cols-2 items-center gap-x-3 gap-y-1 px-3 py-2 hover:bg-muted/50 md:grid-cols-[1.6fr_7rem_8rem_6rem_4.5rem_4.5rem_9rem]">
            <span className="col-span-2 min-w-0 md:col-span-1">
              <span className="block truncate font-medium">{a.display_name || a.username}</span>
              <span className="block truncate font-mono text-2xs text-muted-foreground">{a.username}</span>
            </span>
            <span><Badge variant="secondary" className="text-2xs">{a.role}</Badge></span>
            <span className={`font-medium ${TONE[st.tone]}`}>{st.label}</span>
            <span className="text-muted-foreground">{used ? new Date(used).toLocaleDateString() : "never"}</span>
            <span className="tabular-nums md:text-right">{num(a.calls24h)}</span>
            <span className={`tabular-nums md:text-right ${a.refused24h ? "text-destructive" : ""}`}>{num(a.refused24h)}</span>
            <span className="tabular-nums md:text-right">
              {a.spend === null ? "—" : `${formatUsd(a.spend)} / ${a.cap === null ? "no cap" : formatUsd(a.cap)}`}
            </span>
          </Link>
        )
      })}
    </div>
  )
}

const CUSTOM = "custom"

type IssuedKey = { key: string; scopes: string[]; expires_at: string | null }

/** Mounted only while open, so every opening starts from the first preset. */
function NewAgentDialog({ roles, presets, onClose }: {
  roles: string[]; presets: AgentPreset[]; onClose: () => void
}) {
  const router = useRouter()
  const [name, setName] = useState("")
  const [choice, setChoice] = useState<string>(presets[0]?.id ?? CUSTOM)
  const [role, setRole] = useState("ai_engineer")
  const [pii, setPii] = useState<PiiMode | null>(presets[0]?.pii_mode ?? null)
  const [piiTouched, setPiiTouched] = useState(false)
  const [description, setDescription] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [created, setCreated] = useState<{ id: string; key: IssuedKey | null } | null>(null)
  const [copied, setCopied] = useState(false)

  const preset = presets.find(p => p.id === choice) ?? null

  const pick = (id: string) => {
    setChoice(id)
    // Picking another purpose resets the PII mode to that purpose's, unless the admin
    // already chose one themselves.
    if (!piiTouched) setPii(presets.find(p => p.id === id)?.pii_mode ?? null)
  }

  const create = async () => {
    if (!name.trim() || busy) return
    setBusy(true); setErr(null)
    try {
      const res = await fetch("/api/service-accounts", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(createAgentBody(name, description, preset ? { preset } : { role }, pii, piiTouched)),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) { setErr(typeof d.detail === "string" ? d.detail : `Could not create the agent (HTTP ${res.status})`); return }
      // A preset issues the first key, and this is the only time it can be shown.
      if (d.key?.key) setCreated({ id: d.id, key: d.key })
      else router.push(`/agents/${d.id}`)
    } finally { setBusy(false) }
  }

  if (created?.key) {
    const k = created.key
    return (
      <Dialog open onOpenChange={() => { /* must leave through the button: the key is shown once */ }}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>Agent created — copy its key</DialogTitle></DialogHeader>
          <div className="space-y-3 text-sm">
            <p className="text-xs text-muted-foreground">
              Stored only as a hash and cannot be shown again. Send it as{" "}
              <code className="font-mono">Authorization: Bearer &lt;key&gt;</code>.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 truncate rounded border bg-muted px-2 py-1.5 font-mono text-xs">{k.key}</code>
              <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs"
                      onClick={() => { void navigator.clipboard.writeText(k.key); setCopied(true) }}>
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <p className="text-2xs text-muted-foreground">
              Scopes <code className="font-mono">{k.scopes.join(", ")}</code>
              {k.expires_at ? ` · expires ${k.expires_at.slice(0, 10)}` : ""}.
              Next, grant the collections or catalogs it should read on its page.
            </p>
          </div>
          <DialogFooter>
            <Button size="sm" onClick={() => router.push(`/agents/${created.id}`)}>
              {copied ? "Open agent" : "I saved it — open agent"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    )
  }

  return (
    <Dialog open onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>New agent</DialogTitle></DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="space-y-1">
            <Label htmlFor="agent-name" className="text-xs">Name</Label>
            <Input id="agent-name" value={name} onChange={e => setName(e.target.value)}
                   placeholder="e.g. support-assistant" maxLength={64} />
            <p className="text-2xs text-muted-foreground">Becomes the username <code className="font-mono">svc-…</code>.</p>
          </div>

          <fieldset className="space-y-1.5">
            <legend className="mb-1 text-xs font-medium">What is it for?</legend>
            {[...presets, null].map(p => {
              const id = p?.id ?? CUSTOM
              const on = choice === id
              return (
                <label key={id}
                       className={`flex cursor-pointer gap-2 rounded-md border px-3 py-2 ${on ? "border-primary bg-primary/5" : "hover:bg-muted/50"}`}>
                  <input type="radio" name="agent-preset" className="mt-0.5" checked={on} onChange={() => pick(id)} />
                  <span className="space-y-0.5">
                    <span className="block text-xs font-medium">{p ? p.label : "Custom"}</span>
                    <span className="block text-2xs text-muted-foreground">
                      {p ? p.description : "Choose the role yourself, then issue a key with the scopes you pick on the agent's page."}
                    </span>
                    {p && on && (
                      <span className="block text-2xs text-muted-foreground">
                        Role <code className="font-mono">{p.role}</code> · first key{" "}
                        <code className="font-mono">{p.scopes.join(", ")}</code>, 90 days
                      </span>
                    )}
                  </span>
                </label>
              )
            })}
          </fieldset>

          {!preset && (
            <div className="space-y-1">
              <Label htmlFor="agent-role" className="text-xs">Role</Label>
              <select id="agent-role" value={role} onChange={e => setRole(e.target.value)}
                      className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                {(roles.length ? roles : ["ai_engineer"]).map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
          )}

          <div className="space-y-1">
            <Label htmlFor="agent-pii" className="text-xs">PII guardrail</Label>
            <select id="agent-pii" value={pii ?? ""}
                    onChange={e => { setPii((e.target.value || null) as PiiMode | null); setPiiTouched(true) }}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm">
              <option value="">Inherit the deployment default</option>
              <option value="mask">{PII_MODE_TEXT.mask}</option>
              <option value="block">{PII_MODE_TEXT.block}</option>
            </select>
            <p className="text-2xs text-muted-foreground">
              Can only make the deployment default stricter. Cannot sign in to the console, and never holds{" "}
              <code className="font-mono">user:manage</code> or <code className="font-mono">settings:write</code>.
            </p>
          </div>

          <div className="space-y-1">
            <Label htmlFor="agent-desc" className="text-xs">Description (optional)</Label>
            <Input id="agent-desc" value={description} onChange={e => setDescription(e.target.value)} maxLength={200} />
          </div>
          {err && <p className="text-xs text-destructive">{err}</p>}
        </div>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button size="sm" onClick={create} disabled={busy || !name.trim()}>
            {preset ? "Create and issue key" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
