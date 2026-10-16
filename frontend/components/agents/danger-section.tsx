"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { AlertTriangle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useToast } from "@/lib/toast"
import type { AgentDetail } from "@/lib/agents"
import { Section, errorText } from "./section"

export function DangerSection({ agent, onChange }: { agent: AgentDetail; onChange: () => void }) {
  const router = useRouter()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [typed, setTyped] = useState("")

  const setActive = async (active: boolean) => {
    setBusy(true)
    try {
      const res = await fetch(`/api/auth/users/${agent.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: active }),
      })
      if (!res.ok) { toast(await errorText(res, "Could not change the status"), "error"); return }
      toast(active ? "Agent enabled" : "Agent disabled", "success")
      onChange()
    } finally { setBusy(false) }
  }

  const remove = async () => {
    setBusy(true)
    try {
      const res = await fetch(`/api/service-accounts/${agent.id}`, { method: "DELETE" })
      if (!res.ok) { toast(await errorText(res, "Could not delete the agent"), "error"); return }
      router.push("/agents")
    } finally { setBusy(false) }
  }

  return (
    <Section title="Danger zone" icon={<AlertTriangle className="h-4 w-4 text-destructive" />}>
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
        <div>
          <p className="font-medium">{agent.is_active ? "Disable this agent" : "Enable this agent"}</p>
          <p className="text-muted-foreground">
            {agent.is_active
              ? "Every key stops working, and the keys stay for when it is enabled again."
              : "Disabled: its keys are refused."}{" "}
            Applies within 30 seconds.
          </p>
        </div>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => void setActive(!agent.is_active)}>
          {agent.is_active ? "Disable" : "Enable"}
        </Button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-3 text-xs">
        <div>
          <p className="font-medium">Delete this agent</p>
          <p className="text-muted-foreground">
            Its keys are deleted and its spend cap removed. Audit rows keep its name.
          </p>
        </div>
        <Button size="sm" variant="destructive" disabled={busy} onClick={() => { setTyped(""); setDeleting(true) }}>Delete</Button>
      </div>

      <Dialog open={deleting} onOpenChange={o => { if (!o) setDeleting(false) }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {agent.username}?</DialogTitle>
            <DialogDescription>Type the username to confirm. This cannot be undone.</DialogDescription>
          </DialogHeader>
          <Input value={typed} onChange={e => setTyped(e.target.value)} placeholder={agent.username}
                 aria-label="Type the username to confirm" className="font-mono text-sm" />
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setDeleting(false)} disabled={busy}>Cancel</Button>
            <Button variant="destructive" size="sm" disabled={busy || typed !== agent.username} onClick={() => void remove()}>
              Delete agent
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Section>
  )
}
