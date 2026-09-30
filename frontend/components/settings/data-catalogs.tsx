"use client"

import { useCallback, useEffect, useState } from "react"
import { AlertCircle, CheckCircle2, KeyRound, Library, Loader2, Lock, Plus, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useToast } from "@/lib/toast"
import { useConfirm } from "@/lib/confirm"
import { usePermissions } from "@/lib/permissions"
import {
  KIND_FIELDS, KIND_LABEL, KINDS, OPEN_ACCESS, RESTRICT_NOTE, accessSummary, addGrant,
  deleteBlocked, disableBlocked, emptyForm, formFromCatalog, grantCandidates, grantKey,
  grantLabel, grantsChanged, grantsPayload, locationOf, removeGrant, testSummary,
  toCreatePayload, toPatchPayload, validateForm,
  type CatalogForm, type CatalogGrant, type CatalogKind, type DataCatalog, type FormErrors,
  type GrantCandidate, type TestResult,
} from "@/lib/data-catalogs"

async function call(url: string, init?: RequestInit) {
  const r = await fetch(url, init)
  const body = await r.json().catch(() => ({}))
  if (!r.ok) {
    const d = body?.detail
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map(x => x.msg).join("; ")
      : `HTTP ${r.status}`)
  }
  return body
}

const json = (method: string, payload: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
})

/** The data catalogs DataPond reads (GET/POST/PATCH/DELETE /api/catalogs). Admins
 *  edit; everyone with catalog:read sees the list. A catalog is queryable only when
 *  the query engine knows its engine catalog name — see docs/DEPLOYMENT_PROFILES.md. */
export function DataCatalogs({ canEdit }: { canEdit: boolean }) {
  const { toast } = useToast()
  const confirm = useConfirm()
  const [rows, setRows] = useState<DataCatalog[]>([])
  const [source, setSource] = useState<string>("registry")
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [tests, setTests] = useState<Record<string, TestResult | "running">>({})
  const [rowErr, setRowErr] = useState<Record<string, string>>({})
  const [editing, setEditing] = useState<DataCatalog | "new" | null>(null)
  // Who may use each catalog — admins only (the grants routes need a signed-in admin).
  const [grants, setGrants] = useState<Record<string, CatalogGrant[] | "error">>({})
  const [access, setAccess] = useState<DataCatalog | null>(null)

  const loadGrants = useCallback(async (names: string[]) => {
    const pairs = await Promise.all(names.map(async n => {
      try {
        const d = await call(`/api/catalogs/${encodeURIComponent(n)}/grants`)
        return [n, (d.grants ?? []) as CatalogGrant[]] as const
      } catch {
        return [n, "error" as const] as const
      }
    }))
    setGrants(Object.fromEntries(pairs))
  }, [])

  const load = useCallback(async () => {
    setErr(null)
    try {
      const d = await call("/api/catalogs")
      setRows(d.catalogs ?? []); setSource(d.source ?? "registry")
      if (canEdit && d.source !== "env")
        void loadGrants((d.catalogs ?? []).map((c: DataCatalog) => c.name))
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load catalogs")
    } finally {
      setLoading(false)
    }
  }, [canEdit, loadGrants])

  useEffect(() => { void load() }, [load])

  const act = async (name: string, fn: () => Promise<unknown>, done: string) => {
    setBusy(name); setRowErr(prev => ({ ...prev, [name]: "" }))
    try {
      await fn()
      toast(done, "success")
      await load()
    } catch (e) {
      setRowErr(prev => ({ ...prev, [name]: e instanceof Error ? e.message : "Failed" }))
    } finally {
      setBusy(null)
    }
  }

  const test = async (name: string) => {
    setTests(prev => ({ ...prev, [name]: "running" }))
    try {
      const r: TestResult = await call(`/api/catalogs/${encodeURIComponent(name)}/test`, { method: "POST" })
      setTests(prev => ({ ...prev, [name]: r }))
    } catch (e) {
      setTests(prev => ({ ...prev, [name]: {
        ok: false, namespaces: [], namespace_count: 0,
        error: e instanceof Error ? e.message : "Test failed" } }))
    }
  }

  const remove = async (c: DataCatalog) => {
    const ok = await confirm({
      title: `Delete catalog ${c.name}?`,
      message: "DataPond stops reading it. Tables in it disappear from the catalog, the "
        + "schema tree and table resolution. The catalog itself is not touched.",
      confirmText: "Delete", destructive: true,
    })
    if (!ok) return
    void act(c.name, () => call(`/api/catalogs/${encodeURIComponent(c.name)}`, { method: "DELETE" }),
      `Catalog ${c.name} deleted`)
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Library className="h-4 w-4 text-primary" />Data catalogs
        </CardTitle>
        <CardDescription>
          The catalogs DataPond lists, resolves table names against and governs. Two-part names
          (<code className="font-mono">namespace.table</code>) mean the default catalog. A catalog
          is queryable only when the query engine knows its engine catalog name.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />Loading…</div>
        ) : err ? (
          <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />{err}</div>
        ) : (
          <>
            {source === "env" && (
              <p className="text-2xs text-muted-foreground">
                Shown from the deployment&apos;s settings; the registry has not been written yet.
              </p>
            )}
            <div className="divide-y rounded-lg border">
              {rows.map(c => {
                const t = tests[c.name]
                return (
                  <div key={c.name} className="space-y-1.5 px-3 py-2.5 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{c.name}</span>
                      {c.is_default && <Badge className="text-2xs">Default</Badge>}
                      <Badge variant="outline" className="text-2xs">{KIND_LABEL[c.kind] ?? c.kind}</Badge>
                      {!c.enabled && <Badge variant="outline" className="text-2xs text-muted-foreground">Disabled</Badge>}
                      {c.has_secret && (
                        <span className="inline-flex items-center gap-1 text-2xs text-muted-foreground" title="A credential is stored">
                          <KeyRound className="h-3 w-3" />secret</span>
                      )}
                      <span className="text-muted-foreground">
                        engine catalog <code className="font-mono">{c.engine_catalog}</code>
                      </span>
                      {canEdit && (
                        <span className="ml-auto flex items-center gap-2">
                          <button className="text-primary disabled:opacity-40" disabled={t === "running"}
                                  onClick={() => void test(c.name)}>Test</button>
                          <button className="text-primary" onClick={() => setEditing(c)}>Edit</button>
                          {!c.is_default && c.enabled && (
                            <button className="text-primary disabled:opacity-40" disabled={busy === c.name}
                                    onClick={() => void act(c.name, () => call(`/api/catalogs/${encodeURIComponent(c.name)}`,
                                      json("PATCH", { is_default: true })), `${c.name} is now the default`)}>
                              Make default</button>
                          )}
                          <button className="text-muted-foreground disabled:opacity-40"
                                  disabled={busy === c.name || (c.enabled && !!disableBlocked(c))}
                                  title={c.enabled ? disableBlocked(c) ?? undefined : undefined}
                                  onClick={() => void act(c.name, () => call(`/api/catalogs/${encodeURIComponent(c.name)}`,
                                    json("PATCH", { enabled: !c.enabled })), c.enabled ? `${c.name} disabled` : `${c.name} enabled`)}>
                            {c.enabled ? "Disable" : "Enable"}</button>
                          <button className="text-muted-foreground hover:text-destructive disabled:opacity-40"
                                  disabled={busy === c.name || !!deleteBlocked(c)}
                                  title={deleteBlocked(c) ?? undefined}
                                  onClick={() => void remove(c)}>Delete</button>
                        </span>
                      )}
                    </div>
                    {locationOf(c) && <p className="truncate text-muted-foreground" title={locationOf(c)}>{locationOf(c)}</p>}
                    {canEdit && source !== "env" && (
                      <p className="flex items-center gap-1.5 text-muted-foreground">
                        <Lock className="h-3 w-3 shrink-0" />
                        <span>Access: {grants[c.name] === undefined ? "…"
                          : grants[c.name] === "error" ? "could not be read"
                          : accessSummary(grants[c.name] as CatalogGrant[])}</span>
                        {/* Only once the current list is known: saving replaces it. */}
                        {Array.isArray(grants[c.name]) && (
                          <button className="text-primary" onClick={() => setAccess(c)}>Manage</button>
                        )}
                      </p>
                    )}
                    {t === "running" && (
                      <p className="flex items-center gap-1.5 text-muted-foreground">
                        <Loader2 className="h-3 w-3 animate-spin" />Testing…</p>
                    )}
                    {t && t !== "running" && (
                      <p className={`flex items-start gap-1.5 ${t.ok ? "text-[var(--dp-good-text)]" : "text-destructive"}`}>
                        {t.ok ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0" /> : <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />}
                        <span className="break-all">{testSummary(t)}</span>
                      </p>
                    )}
                    {rowErr[c.name] && <p className="text-destructive">{rowErr[c.name]}</p>}
                  </div>
                )
              })}
            </div>
            {canEdit && (
              <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setEditing("new")}>
                <Plus className="h-3.5 w-3.5" />Add catalog</Button>
            )}
          </>
        )}
      </CardContent>
      {canEdit && editing && (
        <CatalogDialog
          original={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={async (msg) => { setEditing(null); toast(msg, "success"); await load() }}
        />
      )}
      {canEdit && access && (
        <AccessDialog
          catalog={access}
          initial={Array.isArray(grants[access.name]) ? grants[access.name] as CatalogGrant[] : []}
          onClose={() => setAccess(null)}
          onSaved={(saved) => {
            setGrants(prev => ({ ...prev, [access.name]: saved }))
            setAccess(null)
            toast(`Access to ${access.name} saved`, "success")
          }}
        />
      )}
    </Card>
  )
}

function Field({ id, label, hint, error, children }: {
  id: string; label: string; hint?: string; error?: string; children: React.ReactNode
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs">{label}</Label>
      {children}
      {error ? <p className="text-2xs text-destructive">{error}</p>
        : hint ? <p className="text-2xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

function CatalogDialog({ original, onClose, onSaved }: {
  original: DataCatalog | null
  onClose: () => void
  onSaved: (message: string) => Promise<void>
}) {
  const creating = original === null
  const [f, setF] = useState<CatalogForm>(() => original ? formFromCatalog(original) : emptyForm())
  const [errors, setErrors] = useState<FormErrors>({})
  const [saveErr, setSaveErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const set = <K extends keyof CatalogForm>(k: K, v: CatalogForm[K]) => setF(prev => ({ ...prev, [k]: v }))
  const fields = new Set(KIND_FIELDS[f.kind])

  const text = (k: keyof CatalogForm & string, label: string, placeholder?: string, hint?: string) => (
    <Field id={`dc-${k}`} label={label} hint={hint} error={errors[k]}>
      <Input id={`dc-${k}`} value={String(f[k] ?? "")} placeholder={placeholder} className="h-8 text-xs"
             aria-invalid={!!errors[k]} onChange={e => set(k, e.target.value as never)} />
    </Field>
  )
  const box = (k: "via_rest" | "sigv4" | "is_default" | "enabled" | "clearSecret", label: string) => (
    <label className="flex items-center gap-2 text-xs">
      <Checkbox checked={f[k]} onCheckedChange={v => set(k, !!v)} />{label}
      {errors[k] && <span className="text-2xs text-destructive">{errors[k]}</span>}
    </label>
  )

  const save = async () => {
    const e = validateForm(f, { creating })
    setErrors(e); setSaveErr(null)
    if (Object.keys(e).length) return
    setSaving(true)
    try {
      if (creating) {
        await call("/api/catalogs", json("POST", toCreatePayload(f)))
        await onSaved(`Catalog ${f.name} added`)
      } else {
        const p = toPatchPayload(f, original)
        if (Object.keys(p).length === 0) { onClose(); return }
        await call(`/api/catalogs/${encodeURIComponent(original.name)}`, json("PATCH", p))
        await onSaved(`Catalog ${original.name} saved`)
      }
    } catch (err) {
      setSaveErr(err instanceof Error ? err.message : "Could not save")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{creating ? "Add a data catalog" : `Edit ${original.name}`}</DialogTitle>
        </DialogHeader>
        <div className="max-h-[65vh] space-y-3 overflow-y-auto py-1 pr-1">
          <div className="grid grid-cols-2 gap-3">
            {creating ? text("name", "Name", "lake", "What DataPond and SQL call it.") : (
              <Field id="dc-name" label="Name"><p className="py-1.5 text-xs font-medium">{original.name}</p></Field>
            )}
            <Field id="dc-kind" label="Kind">
              {creating ? (
                <select id="dc-kind" value={f.kind} className="h-8 w-full rounded-md border bg-background px-2 text-xs"
                        onChange={e => set("kind", e.target.value as CatalogKind)}>
                  {KINDS.map(k => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
                </select>
              ) : <p className="py-1.5 text-xs">{KIND_LABEL[f.kind]}</p>}
            </Field>
          </div>
          {text("engine_catalog", "Engine catalog", creating ? (f.name || "same as name") : undefined,
            "The name the query engine knows it by (Trino catalog / Athena data catalog).")}

          {f.kind === "iceberg_rest" && (
            <>
              {text("uri", "Catalog URI", "https://…/api/catalog")}
              {text("warehouse", "Warehouse", "catalog name, account id or table-bucket ARN")}
              <div className="grid grid-cols-2 gap-3">
                {text("scope", "OAuth scope", "PRINCIPAL_ROLE:ALL")}
                {text("prefix", "Prefix")}
              </div>
              {box("sigv4", "Sign requests with AWS SigV4 (Glue, S3 Tables)")}
              {f.sigv4 && (
                <div className="grid grid-cols-2 gap-3">
                  {text("signing_name", "Signing name", "s3tables")}
                  {text("signing_region", "Signing region", "ap-northeast-2")}
                </div>
              )}
              <Field id="dc-secret" label="Secret"
                     hint={(original?.has_secret ? "A secret is stored; leave blank to keep it. " : "")
                       + "OAuth client credentials as id:secret, or a bearer token. Stored encrypted; never shown again."}>
                <Input id="dc-secret" type="password" autoComplete="new-password" value={f.secret}
                       disabled={f.clearSecret} className="h-8 text-xs"
                       onChange={e => set("secret", e.target.value)} />
              </Field>
              {original?.has_secret && box("clearSecret", "Remove the stored secret")}
            </>
          )}

          {f.kind === "glue" && (
            <>
              <div className="grid grid-cols-2 gap-3">
                {text("region", "Region", "ap-northeast-2")}
                {text("catalog_id", "Catalog id (account)", "123456789012")}
              </div>
              {fields.has("warehouse") && text("warehouse", "Warehouse", "s3://bucket/warehouse")}
              {box("via_rest", "Read through Glue's Iceberg REST endpoint (another account's catalog)")}
              {text("role_arn", "Role to assume (cross-account)", "arn:aws:iam::123456789012:role/catalog-read",
                    "Optional. The node role must be allowed sts:AssumeRole on it.")}
              {f.role_arn.trim() && text("external_id", "External id", undefined,
                "Optional; only if the role's trust policy requires it.")}
              <p className="text-2xs text-muted-foreground">
                Glue uses the backend&apos;s AWS credentials (or the assumed role); it takes no secret.
              </p>
            </>
          )}

          {f.kind === "polaris" && text("warehouse", "Polaris catalog", "iceberg",
            "A catalog of the deployment's own Polaris; uses the deployment's Polaris client.")}

          <div className="flex flex-wrap gap-4 border-t pt-3">
            {box("enabled", "Enabled")}
            {(creating || !original.is_default) && box("is_default", "Default catalog")}
          </div>
          {saveErr && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{saveErr}</div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={() => void save()} disabled={saving}>
            {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            {creating ? "Add" : "Save"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Who may use one catalog. Saving replaces the whole list (PUT …/grants). */
function AccessDialog({ catalog, initial, onClose, onSaved }: {
  catalog: DataCatalog
  initial: CatalogGrant[]
  onClose: () => void
  onSaved: (saved: CatalogGrant[]) => void
}) {
  const { assignableRoles } = usePermissions()
  const [draft, setDraft] = useState<CatalogGrant[]>(initial)
  const [people, setPeople] = useState<GrantCandidate[]>([])
  const [pickUser, setPickUser] = useState("")
  const [pickRole, setPickRole] = useState("")
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)

  // Best-effort, like the budget picker: without these lists the picker is empty and
  // existing grants still show and can be removed.
  useEffect(() => {
    void (async () => {
      let accounts: { id: string; username?: string; display_name?: string | null }[] = []
      let users: { id: string; username?: string | null; display_name?: string | null }[] = []
      try {
        const r = await fetch("/api/service-accounts")
        if (r.ok) accounts = (await r.json()).accounts ?? []
      } catch { /* picker stays partial */ }
      try {
        const r = await fetch("/api/auth/users")
        if (r.ok) users = await r.json()
      } catch { /* picker stays partial */ }
      setPeople(grantCandidates(accounts, users))
    })()
  }, [])

  const draftKeys = new Set(draft.map(grantKey))
  const userOptions = people.filter(p => !draftKeys.has(grantKey({ kind: "user", principal: p.id })))
  const roleOptions = assignableRoles.map(r => r.name)
    .filter(n => !draftKeys.has(grantKey({ kind: "role", principal: n })))

  const addUser = () => {
    const p = people.find(x => x.id === pickUser)
    if (!p) return
    setDraft(d => addGrant(d, { kind: "user", principal: p.id, username: p.label,
      service_account: p.service_account }))
    setPickUser("")
  }
  const addRole = () => {
    if (!pickRole) return
    setDraft(d => addGrant(d, { kind: "role", principal: pickRole }))
    setPickRole("")
  }

  const save = async () => {
    if (!grantsChanged(initial, draft)) { onClose(); return }
    setSaving(true); setSaveErr(null)
    try {
      const d = await call(`/api/catalogs/${encodeURIComponent(catalog.name)}/grants`,
        json("PUT", grantsPayload(draft)))
      onSaved(d.grants ?? [])
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : "Could not save")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Access to {catalog.name}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-1 text-xs">
          <p className="text-muted-foreground">{RESTRICT_NOTE}</p>
          {draft.length === 0 ? (
            <p className="rounded-md border border-dashed px-3 py-2 text-muted-foreground">{OPEN_ACCESS}</p>
          ) : (
            <ul className="divide-y rounded-md border">
              {draft.map(g => (
                <li key={grantKey(g)} className="flex items-center gap-2 px-3 py-1.5">
                  <span className="truncate" title={g.principal}>{grantLabel(g, people)}</span>
                  <button className="ml-auto text-muted-foreground hover:text-destructive"
                          aria-label={`Remove ${grantLabel(g, people)}`}
                          onClick={() => setDraft(d => removeGrant(d, grantKey(g)))}>
                    <X className="h-3.5 w-3.5" /></button>
                </li>
              ))}
            </ul>
          )}
          <div className="grid grid-cols-[1fr_auto] gap-2">
            <select aria-label="User or service account" value={pickUser}
                    className="h-8 w-full rounded-md border bg-background px-2 text-xs"
                    onChange={e => setPickUser(e.target.value)}>
              <option value="">Add a user or service account…</option>
              {userOptions.map(p => (
                <option key={p.id} value={p.id}>
                  {p.service_account ? `${p.label} (service account)` : p.label}</option>
              ))}
            </select>
            <Button size="sm" variant="outline" disabled={!pickUser} onClick={addUser}>Add</Button>
            <select aria-label="Role" value={pickRole}
                    className="h-8 w-full rounded-md border bg-background px-2 text-xs"
                    onChange={e => setPickRole(e.target.value)}>
              <option value="">Add a role…</option>
              {roleOptions.map(n => <option key={n} value={n}>{n}</option>)}
            </select>
            <Button size="sm" variant="outline" disabled={!pickRole} onClick={addRole}>Add</Button>
          </div>
          <p className="text-2xs text-muted-foreground">{accessSummary(draft)}.</p>
          {saveErr && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-destructive">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{saveErr}</div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={() => void save()} disabled={saving}>
            {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
