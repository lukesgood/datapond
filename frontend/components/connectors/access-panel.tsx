"use client"

import { useCallback, useEffect, useState } from "react"
import { AlertCircle, Loader2, ShieldCheck, Trash2, UserPlus, Users } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useToast } from "@/lib/toast"
import { useConfirm } from "@/lib/confirm"
import { getUser } from "@/lib/auth"
import { usePermissions } from "@/lib/permissions"
import {
  buildSourceAccessRows, canManageSourceMembers, ownershipSummary, roleLabel,
  SOURCE_ROLE_EXPLANATION, type MemberRole, type RawMember, type SourceOwnership,
} from "@/lib/source-members"

/** Who can reach this source, and at what level.
 *
 *  One component for both kinds because the API is one implementation for both
 *  (backend/app/api/source_access.py): `/connectors/{id}/members` and
 *  `/transforms/{id}/members` differ only in the path and the permission their routes
 *  require.
 *
 *  Two things it will not pretend to know. A 403 on the GET is the server's own answer
 *  that this viewer may not manage sharing here, and is trusted over any client-side
 *  guess — an *editor* grant passes on the server and cannot be derived in the browser.
 *  And the panel shows nothing at all before that GET returns, rather than flashing
 *  controls it may have to take away.
 */
export function SourceAccessPanel({
  kind, id,
}: {
  kind: "connectors" | "transforms"
  id: string
}) {
  const { toast } = useToast()
  const confirm = useConfirm()
  const viewer = getUser()
  const { role, permissions } = usePermissions()
  const writePermission = kind === "connectors" ? "connector:write" : "pipeline:write"
  const label = kind === "connectors" ? "source" : "transform"

  const [ownership, setOwnership] = useState<SourceOwnership | null>(null)
  const [members, setMembers] = useState<RawMember[]>([])
  const [authorized, setAuthorized] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [newUsername, setNewUsername] = useState("")
  const [newRole, setNewRole] = useState<MemberRole>("reader")

  const load = useCallback(async () => {
    setErr(null)
    try {
      const r = await fetch(`/api/${kind}/${encodeURIComponent(id)}/members`)
      if (r.status === 403) { setAuthorized(false); return }
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      const d = await r.json()
      setAuthorized(true)
      setOwnership({ owner_id: d.owner_id ?? null, owner: d.owner ?? null })
      setMembers(d.members ?? [])
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load who has access")
    } finally {
      setLoading(false)
    }
  }, [kind, id])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  if (!viewer || loading) return null

  // The server said no. Say so plainly rather than showing an empty list, which would
  // read as "nobody has access" — the opposite of what a 403 means.
  if (authorized === false) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Access</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Only this {label}&apos;s owner, an editor, or an administrator can see or change
          who can reach it.
        </CardContent>
      </Card>
    )
  }

  const current: SourceOwnership = ownership ?? { owner_id: null, owner: null }
  const rows = buildSourceAccessRows(current, { id: viewer.id }, members)
  // Reaching here means the GET succeeded, which the API only allows for someone who
  // may write this source — so managing is allowed. canManageSourceMembers still runs:
  // it is the same rule stated where a reader can check it, and it keeps the panel
  // honest if the route's gate is ever loosened.
  const mayManage = authorized === true
    || canManageSourceMembers(current, { id: viewer.id, role, permissions }, writePermission)

  const addMember = async () => {
    const username = newUsername.trim()
    if (!username) return
    setBusy(true); setErr(null)
    try {
      const r = await fetch(`/api/${kind}/${encodeURIComponent(id)}/members`, {
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
      title: "Remove access",
      message: `"${username}" will no longer be able to reach this ${label}.`,
      destructive: true, confirmText: "Remove",
    })
    if (!ok) return
    setBusy(true); setErr(null)
    try {
      const r = await fetch(
        `/api/${kind}/${encodeURIComponent(id)}/members?username=${encodeURIComponent(username)}`,
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
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <Users className="h-3.5 w-3.5 text-muted-foreground" />Access
        </CardTitle>
        <CardDescription className="text-xs">
          {ownershipSummary(current, { id: viewer.id })} {SOURCE_ROLE_EXPLANATION}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {err && (
          <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />{err}
          </div>
        )}

        <div className="divide-y rounded-lg border">
          {rows.map(row => row.kind === "owner" ? (
            <div key="__owner" className="flex items-center justify-between gap-3 px-3 py-2">
              <span className="truncate text-xs font-medium">
                {row.isViewer ? "You" : row.username ?? "Another user"}
              </span>
              {/* No remove control: there is no grant row to delete, and this panel
                  has no transfer-ownership action. */}
              <Badge variant="outline" className="text-[10px] gap-1">
                <ShieldCheck className="h-2.5 w-2.5" />Owner
              </Badge>
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
              Nobody has been given access individually yet.
            </p>
          )}
        </div>

        {mayManage && (
          <div className="flex items-center gap-2">
            <Input value={newUsername} onChange={e => setNewUsername(e.target.value)}
                   onKeyDown={e => e.key === "Enter" && void addMember()}
                   placeholder="username" className="h-8 flex-1 text-xs" />
            <div className="flex rounded-md border overflow-hidden text-xs">
              {(["reader", "editor"] as const).map(r => (
                <button key={r} type="button" onClick={() => setNewRole(r)}
                        aria-pressed={newRole === r}
                        className={`px-2.5 py-1.5 ${newRole === r ? "bg-primary text-primary-foreground" : "bg-background"}`}>
                  {roleLabel(r)}
                </button>
              ))}
            </div>
            <Button size="sm" onClick={() => void addMember()}
                    disabled={!newUsername.trim() || busy} className="gap-1.5">
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}Add
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
