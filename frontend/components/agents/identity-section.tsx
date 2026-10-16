"use client"

import { useState } from "react"
import { UserRound } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"
import { agentStatus, type AgentDetail } from "@/lib/agents"
import { Section, errorText } from "./section"

const TONE = { ok: "text-[var(--dp-good-text)]", warn: "text-[var(--dp-warn-text)]", bad: "text-destructive" } as const

export function IdentitySection({ agent, onChange }: { agent: AgentDetail; onChange: () => void }) {
  const confirm = useConfirm()
  const { toast } = useToast()
  const [name, setName] = useState(agent.display_name ?? "")
  const [busy, setBusy] = useState(false)
  const status = agentStatus(agent, new Date())

  const patch = async (body: Record<string, unknown>, done: string) => {
    setBusy(true)
    try {
      const res = await fetch(`/api/auth/users/${agent.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      })
      if (!res.ok) { toast(await errorText(res, "Could not save"), "error"); return }
      toast(done, "success")
      onChange()
    } finally { setBusy(false) }
  }

  const changeRole = async (role: string) => {
    if (role === agent.role) return
    // Scopes intersect the role, so this moves every key of the agent at once.
    const ok = await confirm({
      title: `Change role to ${role}?`,
      message: "Changing the role changes what every key of this agent can do.",
      confirmText: "Change role",
    })
    if (ok) await patch({ role }, "Role changed")
  }

  const nameChanged = name.trim() !== (agent.display_name ?? "") && name.trim() !== ""

  return (
    <Section title="Identity" icon={<UserRound className="h-4 w-4 text-primary" />}>
      <div className="grid gap-3 text-xs sm:grid-cols-2">
        <div className="space-y-1">
          <label htmlFor="agent-display" className="text-muted-foreground">Display name</label>
          <div className="flex gap-2">
            <Input id="agent-display" value={name} onChange={e => setName(e.target.value)} className="h-8 text-xs" maxLength={200} />
            <Button size="sm" variant="outline" className="h-8 text-xs" disabled={busy || !nameChanged}
                    onClick={() => void patch({ display_name: name.trim() }, "Name saved")}>Save</Button>
          </div>
        </div>
        <div className="space-y-1">
          <label htmlFor="agent-role" className="text-muted-foreground">Role</label>
          <select id="agent-role" value={agent.role} disabled={busy}
                  onChange={e => void changeRole(e.target.value)}
                  className="h-8 w-full rounded-md border bg-background px-2 text-xs">
            {[...new Set([agent.role, ...agent.assignable_roles])].map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div><span className="text-muted-foreground">Username </span><code className="font-mono">{agent.username}</code></div>
        <div><span className="text-muted-foreground">Created </span>{new Date(agent.created_at).toLocaleDateString()}</div>
        <div><span className="text-muted-foreground">Status </span><span className={`font-medium ${TONE[status.tone]}`}>{status.label}</span></div>
      </div>
      <div className="flex flex-wrap gap-1">
        {agent.permissions.map(p => (
          <Badge key={p} variant="secondary" className="font-mono text-2xs">{p}</Badge>
        ))}
      </div>
    </Section>
  )
}
