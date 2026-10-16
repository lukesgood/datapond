"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { AlertCircle, Bot, Loader2, Plus, RefreshCw } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { PermissionGate } from "@/components/ui/permission-state"
import { formatUsd } from "@/lib/format-usd"
import {
  agentStatus, joinAgentRows, lastUsed,
  type Agent, type AgentRow, type Budget, type ByActor,
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
      getJson<{ accounts: Agent[]; assignable_roles: string[] }>("/api/service-accounts"),
      getJson<{ by_actor: ByActor[] }>(`/api/audit/tool-calls/summary?since=${encodeURIComponent(since)}`),
      getJson<{ customers?: Budget[]; unavailable?: string | null }>("/api/settings/ai/budgets"),
    ])
    if (acc.status === "fulfilled") {
      setAgents(acc.value.accounts); setRoles(acc.value.assignable_roles ?? [])
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
      <NewAgentDialog open={creating} roles={roles} onClose={() => setCreating(false)} />
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

function NewAgentDialog({ open, roles, onClose }: { open: boolean; roles: string[]; onClose: () => void }) {
  const router = useRouter()
  const [name, setName] = useState("")
  const [role, setRole] = useState("ai_engineer")
  const [description, setDescription] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const create = async () => {
    if (!name.trim() || busy) return
    setBusy(true); setErr(null)
    try {
      const res = await fetch("/api/service-accounts", {
        method: "POST", headers: { "Content-Type": "application/json" },
        // The backend stores the description as the display name when given.
        body: JSON.stringify({ name: name.trim(), role, description: description.trim() || undefined }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) { setErr(typeof d.detail === "string" ? d.detail : `Could not create the agent (HTTP ${res.status})`); return }
      router.push(`/agents/${d.id}`)
    } finally { setBusy(false) }
  }

  return (
    <Dialog open={open} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>New agent</DialogTitle></DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="space-y-1">
            <Label htmlFor="agent-name" className="text-xs">Name</Label>
            <Input id="agent-name" value={name} onChange={e => setName(e.target.value)}
                   placeholder="e.g. support-assistant" maxLength={128} />
            <p className="text-2xs text-muted-foreground">Becomes the username <code className="font-mono">svc-…</code>.</p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="agent-role" className="text-xs">Role</Label>
            <select id="agent-role" value={role} onChange={e => setRole(e.target.value)}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm">
              {(roles.length ? roles : ["ai_engineer"]).map(r => <option key={r} value={r}>{r}</option>)}
            </select>
            <p className="text-2xs text-muted-foreground">
              Cannot sign in to the console, and never holds <code className="font-mono">user:manage</code> or{" "}
              <code className="font-mono">settings:write</code> whatever the role.
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
          <Button size="sm" onClick={create} disabled={busy || !name.trim()}>Create</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
