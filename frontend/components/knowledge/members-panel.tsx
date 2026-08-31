"use client"

import { useCallback, useEffect, useState } from "react"
import { AlertCircle, Loader2, ShieldCheck, Trash2, UserPlus, Users } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useToast } from "@/lib/toast"
import { useConfirm } from "@/lib/confirm"
import { getUser } from "@/lib/auth"
import {
  buildAccessRows, roleLabel, ROLE_EXPLANATION,
  type MemberRole, type RawMember,
} from "@/lib/collection-members"

/** Who has access to this collection, and at what level.
 *
 *  GET/POST/DELETE /ai/collections/{name}/members (backend/app/api/ai_vectors.py)
 *  are gated on may_write for THIS collection, not on knowledge:write alone — the
 *  same gate as ingest. That means a plain reader's GET here 403s exactly like
 *  their POST would, so `authorized` below is set from the real response, not a
 *  client-side guess: lib/collection-members.ts's `canManageMembers` only covers
 *  the two cases the client can already be sure of without asking (admin, owner);
 *  an editor member also passes on the server, and the only way this component
 *  learns that is the GET call succeeding anyway.
 */
export function MembersPanel({ name, ownerId }: { name: string; ownerId: string | null }) {
  const { toast } = useToast()
  const confirm = useConfirm()
  const viewer = getUser()

  const [members, setMembers] = useState<RawMember[] | null>(null)
  const [authorized, setAuthorized] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [newUsername, setNewUsername] = useState("")
  const [newRole, setNewRole] = useState<MemberRole>("reader")

  const load = useCallback(async () => {
    setErr(null)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}/members`)
      if (r.status === 403) { setAuthorized(false); setMembers(null); return }
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      const d = await r.json()
      setAuthorized(true)
      setMembers(d.members ?? [])
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load members")
    } finally {
      setLoading(false)
    }
  }, [name])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  if (!viewer) return null

  if (loading) {
    return <div className="flex items-center gap-1.5 py-6 text-xs text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />Loading…</div>
  }
  if (err) {
    return <div className="mt-3 flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
      <AlertCircle className="h-3.5 w-3.5 shrink-0" />{err}</div>
  }

  // authorized === false ⇒ the server's own answer (a 403 on GET) is that this
  // viewer is neither owner, admin, nor editor here. Trust that response, not a
  // client-side guess — see the module docstring for why the two can disagree.
  if (authorized === false) {
    return (
      <div className="pt-3 text-sm text-muted-foreground">
        Only the collection&apos;s owner, an editor, or an administrator can view or
        manage who has access. Ask one of them to add you if you need to see this.
      </div>
    )
  }

  const rows = buildAccessRows(
    { owner_id: ownerId },
    { id: viewer.id, username: viewer.username },
    members ?? [],
  )
  // The GET above already is the authoritative check (see the module docstring):
  // reaching this line with authorized === true means the server itself confirmed
  // this viewer may manage membership, whether as owner, admin, or editor member.
  const mayManage = authorized === true

  const addMember = async () => {
    const username = newUsername.trim()
    if (!username) return
    setBusy(true); setErr(null)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}/members`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, role: newRole }),
      })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      toast(`${username} added as ${roleLabel(newRole).toLowerCase()}`, "success")
      setNewUsername(""); await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not add member")
    } finally {
      setBusy(false)
    }
  }

  const removeMember = async (username: string) => {
    const ok = await confirm({
      title: "Remove access", message: `"${username}" will no longer be able to reach "${name}".`,
      destructive: true, confirmText: "Remove",
    })
    if (!ok) return
    setBusy(true); setErr(null)
    try {
      const r = await fetch(
        `/api/ai/collections/${encodeURIComponent(name)}/members?username=${encodeURIComponent(username)}`,
        { method: "DELETE" })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      toast(`Removed ${username}`, "success"); await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not remove member")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3 pt-3">
      <p className="text-xs text-muted-foreground">{ROLE_EXPLANATION}</p>

      <div className="divide-y rounded-lg border">
        {rows.map(row => row.kind === "owner" ? (
          <div key="__owner" className="flex items-center justify-between gap-3 px-3 py-2">
            <span className="flex min-w-0 items-center gap-1.5">
              <Users className="h-3 w-3 shrink-0 text-muted-foreground" />
              <span className="truncate text-xs font-medium">
                {row.isViewer ? row.username : "Owner"}
              </span>
            </span>
            {/* Not removable: there is no member row to delete, and this dialog has
                no "transfer ownership" action. */}
            <Badge variant="outline" className="text-[10px] gap-1"><ShieldCheck className="h-2.5 w-2.5" />Owner</Badge>
          </div>
        ) : (
          <div key={row.username} className="flex items-center justify-between gap-3 px-3 py-2">
            <span className="truncate text-xs font-mono">{row.username}</span>
            <span className="flex shrink-0 items-center gap-2">
              <Badge variant="outline" className="text-[10px]">{roleLabel(row.role)}</Badge>
              {mayManage && (
                <button onClick={() => void removeMember(row.username)} disabled={busy}
                        aria-label={`Remove ${row.username}`}
                        className="text-muted-foreground hover:text-destructive disabled:opacity-40">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </span>
          </div>
        ))}
        {rows.length === 0 && (
          <p className="px-3 py-4 text-center text-xs text-muted-foreground">
            Only the owner has access — nobody else has been added yet.
          </p>
        )}
      </div>

      {mayManage && (
        <div className="flex items-center gap-2">
          <Input value={newUsername} onChange={e => setNewUsername(e.target.value)}
                 onKeyDown={e => e.key === "Enter" && void addMember()}
                 placeholder="username" className="h-8 flex-1 text-xs" />
          <div className="flex rounded-md border overflow-hidden text-xs">
            {(["reader", "editor"] as const).map(role => (
              <button key={role} type="button" onClick={() => setNewRole(role)}
                      aria-pressed={newRole === role}
                      className={`px-2.5 py-1.5 ${newRole === role ? "bg-primary text-primary-foreground" : "bg-background"}`}>
                {roleLabel(role)}
              </button>
            ))}
          </div>
          <Button size="sm" onClick={() => void addMember()} disabled={!newUsername.trim() || busy} className="gap-1.5">
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}Add
          </Button>
        </div>
      )}
    </div>
  )
}
