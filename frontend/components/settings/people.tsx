"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import NextLink from "next/link"
import { Eye, EyeOff, Loader2, Plus, Search, Trash2, X } from "lucide-react"
import { getUser } from "@/lib/auth"
import { usePermissions } from "@/lib/permissions"
import { roleOptions } from "@/lib/user-roles"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorBox } from "@/components/ui/error-box"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"

export interface Person {
  id: string; username: string; email: string; display_name: string; role: string; is_active: boolean
  require_password_change: boolean; created_at: string | null; last_activity_at: string | null
  attributes?: Record<string, string>
  /** "service" for an agent's account (Agents), "person" otherwise. */
  kind?: "person" | "service"
}

const SYNTHETIC = /@(service\.)?datapond\.local$/i
const when = (iso: string | null) => {
  if (!iso) return "never"
  const d = new Date(iso)
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  return days <= 0 ? "today" : days === 1 ? "yesterday" : days < 30 ? `${days} days ago` : d.toLocaleDateString()
}
const errText = async (r: Response) => {
  const d = await r.json().catch(() => ({}))
  return typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`
}
const sel = "h-9 w-full rounded-md border bg-background px-2 text-sm"

/** People: the list, with the selected person (or a new one) in the right column.
 *  It was a table of icon buttons opening four dialogs; role changes and
 *  deactivation toasted success without checking the response, a new user could not
 *  be given an email (so password recovery could not reach them), and the RLS
 *  attributes were three fixed fields. */
export function People() {
  const me = getUser()
  const [people, setPeople] = useState<Person[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [selected, setSelected] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [agents, setAgents] = useState(0)

  const load = useCallback(async () => {
    setErr(null)
    try {
      const r = await fetch("/api/auth/users")
      if (!r.ok) throw new Error(await errText(r))
      const all = ((await r.json()) as Person[]).filter(p => p.username)
      // Agents' service accounts are user rows too; they are managed in Agents.
      setPeople(all.filter(p => p.kind !== "service"))
      setAgents(all.length - all.filter(p => p.kind !== "service").length)
    } catch (e) { setErr(e instanceof Error ? e.message : "Could not read people") }
  }, [])
  useEffect(() => { const t = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(t) }, [load])

  const needle = query.trim().toLowerCase()
  const shown = (people ?? []).filter(p => !needle || [p.username, p.display_name, p.email, p.role].some(v => (v ?? "").toLowerCase().includes(needle)))
  const current = people?.find(p => p.id === selected) ?? null

  return (
    <div className="flex flex-wrap items-start gap-5">
      <div className="min-w-0 flex-[3_1_480px] space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[220px] flex-1">
            <Search aria-hidden className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input aria-label="Search people" placeholder="Search by name, email or role" value={query} onChange={e => setQuery(e.target.value)} className="pl-8" />
          </div>
          <Button size="sm" onClick={() => { setCreating(true); setSelected(null) }}><Plus className="mr-1.5 h-3.5 w-3.5" />Add person</Button>
        </div>
        {err ? (
          <div role="alert"><ErrorBox msg={err} action={<Button size="sm" variant="outline" onClick={load}>Retry</Button>} /></div>
        ) : people === null ? <Skeleton className="h-48" /> : (
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Person</th>
                  <th className="px-4 py-2 font-medium">Role</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 pr-5 text-right font-medium">Last active</th>
                </tr>
              </thead>
              <tbody>
                {shown.length === 0 && <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-muted-foreground">No one matches &quot;{query}&quot;.</td></tr>}
                {shown.map(p => (
                  <tr key={p.id} onClick={() => { setSelected(p.id); setCreating(false) }}
                      className={`cursor-pointer border-b last:border-0 ${selected === p.id ? "bg-primary/5" : "hover:bg-muted/30"} ${p.is_active ? "" : "text-muted-foreground"}`}>
                    <td className="px-4 py-2">
                      <button type="button" className="text-left font-medium hover:underline" onClick={e => { e.stopPropagation(); setSelected(p.id); setCreating(false) }}>
                        {p.display_name || p.username}{p.id === me?.id && <span className="ml-1 text-xs font-normal text-muted-foreground">(you)</span>}
                      </button>
                      <div className="text-2xs text-muted-foreground">@{p.username}{p.email && !SYNTHETIC.test(p.email) ? ` · ${p.email}` : ""}</div>
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">{p.role}</td>
                    <td className="px-4 py-2 text-xs">
                      {!p.is_active ? "Inactive" : p.require_password_change ? <span className="text-[var(--dp-warn-text)]">Must change password</span> : "Active"}
                    </td>
                    <td className="px-4 py-2 pr-5 text-right text-xs text-muted-foreground">{when(p.last_activity_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {creating ? (
        <NewPersonRail existing={people ?? []} onClose={() => setCreating(false)}
          onCreated={async id => { setCreating(false); await load(); if (id) setSelected(id) }} />
      ) : current ? (
        <PersonRail key={current.id} person={current} isMe={current.id === me?.id}
          onClose={() => setSelected(null)} onChanged={load} onDeleted={() => { setSelected(null); void load() }} />
      ) : (
        <ExplainRail label="About people">
          <RailSection title={`${people?.length ?? "…"} people`}>
            {people ? `${people.filter(p => p.is_active).length} active, ${people.filter(p => p.role === "admin").length} administrators.` : ""}
          </RailSection>
          <RailSection title="Choose a person">
            Change their role, email and row-policy attributes, reset their password, or deactivate them.
          </RailSection>
          <RailSection title="Agents are not people">
            {agents > 0 ? `${agents} service account${agents === 1 ? "" : "s"} for tools and AI agents ${agents === 1 ? "is" : "are"} not listed here; they are` : "Service accounts for tools and AI agents are"} in <NextLink href="/agents" className="text-primary hover:underline">Agents</NextLink>.
            Your own password and passkeys are in <NextLink href="/account" className="text-primary hover:underline">Account</NextLink>.
          </RailSection>
        </ExplainRail>
      )}
    </div>
  )
}

function useRoleOptions() {
  const { assignableRoles } = usePermissions()
  return useMemo(() => roleOptions(assignableRoles), [assignableRoles])
}

function AttributesEditor({ value, onChange, disabled }: {
  value: [string, string][]; onChange: (v: [string, string][]) => void; disabled?: boolean
}) {
  return (
    <div className="space-y-1.5">
      {value.map(([k, v], i) => (
        <div key={i} className="flex gap-2">
          <Input aria-label={`Attribute ${i + 1} name`} className="w-32 font-mono text-xs" value={k} disabled={disabled}
                 onChange={e => onChange(value.map((p, j) => (j === i ? [e.target.value, p[1]] : p)))} placeholder="region" />
          <Input aria-label={`Attribute ${i + 1} value`} className="flex-1 font-mono text-xs" value={v} disabled={disabled}
                 onChange={e => onChange(value.map((p, j) => (j === i ? [p[0], e.target.value] : p)))} placeholder="us-east" />
          <Button size="icon-sm" variant="ghost" aria-label={`Remove attribute ${k || i + 1}`} disabled={disabled}
                  onClick={() => onChange(value.filter((_, j) => j !== i))}><Trash2 className="h-3.5 w-3.5" /></Button>
        </div>
      ))}
      <Button size="sm" variant="outline" disabled={disabled} onClick={() => onChange([...value, ["", ""]])}>Add attribute</Button>
    </div>
  )
}

function PersonRail({ person, isMe, onClose, onChanged, onDeleted }: {
  person: Person; isMe: boolean; onClose: () => void; onChanged: () => void | Promise<void>; onDeleted: () => void
}) {
  const { toast } = useToast()
  const confirm = useConfirm()
  const options = useRoleOptions()
  const [role, setRole] = useState(person.role)
  const [displayName, setDisplayName] = useState(person.display_name ?? "")
  const [email, setEmail] = useState(person.email && !SYNTHETIC.test(person.email) ? person.email : "")
  const [attrs, setAttrs] = useState<[string, string][]>(Object.entries(person.attributes ?? {}))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [resetting, setResetting] = useState(false)
  const [pw, setPw] = useState("")
  const [showPw, setShowPw] = useState(false)

  const cleanAttrs = Object.fromEntries(attrs.map(([k, v]) => [k.trim(), v.trim()]).filter(([k, v]) => k && v))
  const body: Record<string, unknown> = {}
  if (role !== person.role) body.role = role
  if (displayName.trim() !== (person.display_name ?? "")) body.display_name = displayName.trim()
  const savedEmail = person.email && !SYNTHETIC.test(person.email) ? person.email : ""
  if (email.trim() !== savedEmail && email.trim()) body.email = email.trim()
  if (JSON.stringify(cleanAttrs) !== JSON.stringify(person.attributes ?? {})) body.attributes = cleanAttrs
  const dirty = Object.keys(body).length > 0
  const dupKey = new Set(attrs.map(([k]) => k.trim()).filter(Boolean)).size !== attrs.map(([k]) => k.trim()).filter(Boolean).length
  const emailBad = !!email.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())
  const roleDesc = options.find(o => o.value === role)

  const patch = async (b: Record<string, unknown>) => {
    const r = await fetch(`/api/auth/users/${person.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })
    if (!r.ok) throw new Error(await errText(r))
  }

  const save = async () => {
    if (body.role && (body.role === "admin" || person.role === "admin") && !(await confirm({
      title: body.role === "admin" ? `Make ${person.username} an administrator?` : `Remove ${person.username}'s administrator access?`,
      message: body.role === "admin"
        ? "Administrators manage people, policies, models and every collection."
        : `They become ${role} and lose user management, policies and settings.`,
      confirmText: body.role === "admin" ? "Make administrator" : "Change role", destructive: body.role === "admin",
    }))) return
    setBusy(true); setErr(null)
    try { await patch(body); toast(`${person.username} saved`, "success"); await onChanged() }
    catch (e) { setErr(e instanceof Error ? e.message : "Could not save") }
    finally { setBusy(false) }
  }

  const setActive = async (active: boolean) => {
    if (!active && !(await confirm({
      title: `Deactivate ${person.username}?`,
      message: "They are signed out now and cannot sign in. Their history and ownership stay. You can reactivate them.",
      confirmText: "Deactivate", destructive: true,
    }))) return
    setBusy(true); setErr(null)
    try { await patch({ is_active: active }); toast(`${person.username} ${active ? "reactivated" : "deactivated"}`, "success"); await onChanged() }
    catch (e) { setErr(e instanceof Error ? e.message : "Could not change status") }
    finally { setBusy(false) }
  }

  const resetPassword = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await fetch("/api/auth/setup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: person.username, password: pw }) })
      if (!r.ok) throw new Error(await errText(r))
      toast(`Password reset for ${person.username}; they change it at next sign-in`, "success")
      setResetting(false); setPw(""); await onChanged()
    } catch (e) { setErr(e instanceof Error ? e.message : "Could not reset the password") }
    finally { setBusy(false) }
  }

  const remove = async () => {
    if (!(await confirm({
      title: `Delete ${person.username}?`,
      message: "The account is removed. Deactivating keeps their history instead. This cannot be undone.",
      confirmText: "Delete person", destructive: true,
    }))) return
    const r = await fetch(`/api/auth/users/${person.id}`, { method: "DELETE" })
    if (!r.ok) { setErr(await errText(r)); return }
    toast(`${person.username} deleted`, "success")
    onDeleted()
  }

  return (
    <aside aria-label={`Settings for ${person.username}`} className="min-w-0 flex-[2_1_340px] space-y-4 rounded-xl border border-primary/50 bg-muted/40 p-5 text-sm lg:sticky lg:top-6">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold">{person.display_name || person.username}</h3>
          <p className="text-xs text-muted-foreground">@{person.username}{person.created_at ? ` · joined ${new Date(person.created_at).toLocaleDateString()}` : ""}</p>
        </div>
        <Button size="icon-sm" variant="ghost" aria-label="Close" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>

      <fieldset disabled={busy} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="pp-role">Role</Label>
          <select id="pp-role" value={role} onChange={e => setRole(e.target.value)} disabled={isMe} className={sel}>
            {options.map(o => <option key={o.value} value={o.value}>{o.value}</option>)}
            {!options.some(o => o.value === role) && <option value={role}>{role}</option>}
          </select>
          <p className="text-xs text-muted-foreground">{isMe ? "You cannot change your own role." : roleDesc ? `${roleDesc.label} ${roleDesc.description !== roleDesc.label ? roleDesc.description : ""}` : ""}</p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pp-name">Display name</Label>
          <Input id="pp-name" value={displayName} onChange={e => setDisplayName(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pp-email">Email</Label>
          <Input id="pp-email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="name@company.com" />
          <p className="text-xs text-muted-foreground">Where password recovery is sent.</p>
        </div>
        <div className="space-y-1.5">
          <Label>Attributes for row policies</Label>
          <AttributesEditor value={attrs} onChange={setAttrs} />
          <p className="text-xs text-muted-foreground">
            Read by row policies with <span className="font-mono">current_user_attribute(&apos;name&apos;)</span>.
          </p>
        </div>
      </fieldset>

      {!email.trim() && <RailAttention title="No email">Password recovery cannot reach them; an administrator resets it instead.</RailAttention>}
      {emailBad && <p role="alert" className="text-xs text-destructive">That email does not look right.</p>}
      {dupKey && <p role="alert" className="text-xs text-destructive">Two attributes have the same name.</p>}
      {err && <p role="alert" className="text-xs text-destructive">{err}</p>}
      <div className="flex gap-2">
        <Button size="sm" onClick={save} disabled={busy || !dirty || emailBad || dupKey}>{busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Save</Button>
        <Button size="sm" variant="ghost" disabled={busy || !dirty}
                onClick={() => { setRole(person.role); setDisplayName(person.display_name ?? ""); setEmail(savedEmail); setAttrs(Object.entries(person.attributes ?? {})); setErr(null) }}>Undo changes</Button>
      </div>

      {!isMe && (
        <div className="space-y-3 border-t pt-4">
          {resetting ? (
            <div className="space-y-2">
              <Label htmlFor="pp-pw">New password</Label>
              <div className="relative">
                <Input id="pp-pw" type={showPw ? "text" : "password"} value={pw} onChange={e => setPw(e.target.value)} className="pr-9" autoComplete="new-password" />
                <button type="button" onClick={() => setShowPw(v => !v)} aria-label={showPw ? "Hide password" : "Show password"}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p className="text-xs text-muted-foreground">At least 6 characters. They must change it at next sign-in.</p>
              <div className="flex gap-2">
                <Button size="sm" onClick={resetPassword} disabled={busy || pw.length < 6}>Reset password</Button>
                <Button size="sm" variant="ghost" onClick={() => { setResetting(false); setPw("") }}>Cancel</Button>
              </div>
            </div>
          ) : (
            <Row title="Reset password" hint="Sets a temporary password." action={<Button size="sm" variant="outline" onClick={() => setResetting(true)} disabled={busy}>Reset…</Button>} />
          )}
          {person.is_active
            ? <Row title="Deactivate" hint="Signs out now, keeps history." action={<Button size="sm" variant="outline" onClick={() => setActive(false)} disabled={busy}>Deactivate…</Button>} />
            : <Row title="Reactivate" hint="They can sign in again." action={<Button size="sm" variant="outline" onClick={() => setActive(true)} disabled={busy}>Reactivate</Button>} />}
          <Row title="Delete person" hint="Cannot be undone." danger action={<Button size="sm" variant="outline" className="border-destructive/40 text-destructive" onClick={remove} disabled={busy}>Delete…</Button>} />
        </div>
      )}
    </aside>
  )
}

function Row({ title, hint, action, danger }: { title: string; hint: string; action: React.ReactNode; danger?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div><p className={`text-sm font-medium ${danger ? "text-destructive" : ""}`}>{title}</p><p className="text-xs text-muted-foreground">{hint}</p></div>
      {action}
    </div>
  )
}

function NewPersonRail({ existing, onClose, onCreated }: { existing: Person[]; onClose: () => void; onCreated: (id: string | null) => void }) {
  const { toast } = useToast()
  const options = useRoleOptions()
  const [username, setUsername] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [email, setEmail] = useState("")
  const [role, setRole] = useState("viewer")
  const [pw, setPw] = useState("")
  const [showPw, setShowPw] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const taken = existing.some(p => p.username.toLowerCase() === username.trim().toLowerCase())
  const emailBad = !!email.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())
  const roleDesc = options.find(o => o.value === role)

  const create = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await fetch("/api/auth/setup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password: pw, display_name: displayName.trim() || undefined, email: email.trim() || undefined }),
      })
      if (!r.ok) throw new Error(await errText(r))
      // /auth/setup always creates a viewer; any other role is a second call, checked.
      const list = await fetch("/api/auth/users").then(x => (x.ok ? x.json() : [])) as Person[]
      const made = list.find(p => p.username === username.trim()) ?? null
      if (role !== "viewer") {
        if (!made) throw new Error("Created, but could not find the account to set its role. Set it from the list.")
        const p = await fetch(`/api/auth/users/${made.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role }) })
        if (!p.ok) throw new Error(`Created as viewer, but the role was refused: ${await errText(p)}`)
      }
      toast(`${username.trim()} added; they change the password at first sign-in`, "success")
      onCreated(made?.id ?? null)
    } catch (e) { setErr(e instanceof Error ? e.message : "Could not add the person") }
    finally { setBusy(false) }
  }

  return (
    <aside aria-label="Add person" className="min-w-0 flex-[2_1_340px] space-y-4 rounded-xl border border-primary/50 bg-muted/40 p-5 text-sm lg:sticky lg:top-6">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-base font-semibold">Add person</h3>
        <Button size="icon-sm" variant="ghost" aria-label="Close" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>
      <fieldset disabled={busy} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5"><Label htmlFor="np-user">Username</Label><Input id="np-user" value={username} onChange={e => setUsername(e.target.value)} autoComplete="off" /></div>
          <div className="space-y-1.5"><Label htmlFor="np-name">Display name</Label><Input id="np-name" value={displayName} onChange={e => setDisplayName(e.target.value)} /></div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="np-email">Email</Label>
          <Input id="np-email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="name@company.com" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="np-role">Role</Label>
          <select id="np-role" value={role} onChange={e => setRole(e.target.value)} className={sel}>
            {options.map(o => <option key={o.value} value={o.value}>{o.value}</option>)}
          </select>
          {roleDesc && <p className="text-xs text-muted-foreground">{roleDesc.label}</p>}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="np-pw">Temporary password</Label>
          <div className="relative">
            <Input id="np-pw" type={showPw ? "text" : "password"} value={pw} onChange={e => setPw(e.target.value)} className="pr-9" autoComplete="new-password" />
            <button type="button" onClick={() => setShowPw(v => !v)} aria-label={showPw ? "Hide password" : "Show password"}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          <p className="text-xs text-muted-foreground">At least 6 characters. They must change it at first sign-in.</p>
        </div>
      </fieldset>
      {taken && <RailAttention title="That username exists" tone="bad">Adding it would reset that person&apos;s password. Choose another name, or reset it from their page.</RailAttention>}
      {!email.trim() && username.trim() && <RailAttention title="No email">Password recovery cannot reach them.</RailAttention>}
      {emailBad && <p role="alert" className="text-xs text-destructive">That email does not look right.</p>}
      {err && <p role="alert" className="text-xs text-destructive">{err}</p>}
      <div className="flex gap-2">
        <Button size="sm" onClick={create} disabled={busy || !username.trim() || pw.length < 6 || taken || emailBad}>
          {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Add person
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
      </div>
    </aside>
  )
}
