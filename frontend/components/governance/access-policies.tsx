"use client"

import { useCallback, useEffect, useState } from "react"
import { Loader2, X } from "lucide-react"
import { useCapabilities } from "@/lib/capabilities"
import { lakeCatalogs } from "@/lib/data-catalogs"
import { usePermissions } from "@/lib/permissions"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"
import { describeMask, describeRowPolicy, MASK_TEXT } from "@/lib/policy-text"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorBox } from "@/components/ui/error-box"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { kindShort } from "@/lib/catalog-view"
import { parseMaskParam } from "@/lib/concepts"

interface RlsPolicy {
  id: string; name?: string | null; catalog_name: string; schema_name: string; table_name: string
  filter_expression: string; priority: number; enabled: boolean; roles: string[]; exempt_roles: string[]
}
interface MaskPolicy {
  id: string; name?: string | null; catalog_name: string; schema_name: string; table_name: string
  column_name: string; masking_type: string; custom_expression?: string | null; enabled: boolean; roles: string[]
}
interface Role { name: string; display_name?: string }
interface Lake { engine_catalog: string; is_default: boolean; kind: string; enabled: boolean }
interface PreviewResult { allowed?: boolean; rewritten_sql?: string; reason?: string; error?: string; detail?: string }

type MaskTarget = { catalog: string; schema: string; table: string; column: string }
type Editing =
  | { kind: "row"; policy: RlsPolicy | null }
  | { kind: "mask"; policy: MaskPolicy | null; target?: MaskTarget }

const errText = async (r: Response) => {
  const d = await r.json().catch(() => ({}))
  return typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`
}
const select = "h-9 w-full rounded-md border bg-background px-2 text-sm"

/** Row policies and column masks in one list, edited in the right column, with a
 *  try-it box under the list. They were two create forms of placeholder-only inputs
 *  above two lists; neither could be edited (masks could not even be turned off),
 *  roles were typed as comma lists, and an auditor saw every write control. Writes
 *  need an administrator — the API's own check (`_require_admin`). */
export function AccessPolicies() {
  const caps = useCapabilities()
  const { role, loaded: permsLoaded } = usePermissions()
  const canWrite = permsLoaded && role === "admin"
  const confirm = useConfirm()
  const { toast } = useToast()

  const [policies, setPolicies] = useState<RlsPolicy[]>([])
  const [masks, setMasks] = useState<MaskPolicy[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [lakes, setLakes] = useState<Lake[]>([])
  const [defaultDeny, setDefaultDeny] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [editing, setEditing] = useState<Editing | null>(null)

  const load = useCallback(async () => {
    setErr(null)
    try {
      const [p, m, rules] = await Promise.all([
        fetch("/api/governance/rls/policies"),
        fetch("/api/governance/masking/policies"),
        fetch("/api/governance/rls/trino-rules"),
      ])
      if (!p.ok) throw new Error(p.status === 403 ? "Reading policies needs governance:read." : `Could not read row policies (${await errText(p)})`)
      if (!m.ok) throw new Error(`Could not read column masks (${await errText(m)})`)
      setPolicies(await p.json() ?? [])
      setMasks(await m.json() ?? [])
      if (rules.ok) {
        const d = await rules.json().catch(() => null)
        const v = d?.summary?.default_deny
        setDefaultDeny(typeof v === "boolean" ? v : null)
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read policies")
    } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const t = window.setTimeout(() => void load(), 0)
    fetch("/api/governance/roles").then(r => (r.ok ? r.json() : [])).then(d => setRoles(Array.isArray(d) ? d : [])).catch(() => {})
    fetch("/api/catalogs").then(r => (r.ok ? r.json() : { catalogs: [] }))
      .then(d => setLakes(lakeCatalogs<Lake>(d.catalogs ?? []))).catch(() => {})
    // ?mask=catalog.schema.table.column (Metrics › Concepts, a PII column with no mask):
    // open a new mask with the column filled in. Nothing is saved until it is submitted.
    const target = parseMaskParam(new URLSearchParams(window.location.search).get("mask"))
    if (target) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setEditing({ kind: "mask", policy: null, target })
      // Drop the parameter so a reload after saving does not open the form again.
      const url = new URL(window.location.href); url.searchParams.delete("mask")
      window.history.replaceState(null, "", url.toString())
    }
    return () => window.clearTimeout(t)
  }, [load])

  const queryCatalog = typeof caps.query_catalog === "string" && caps.query_catalog ? caps.query_catalog : "iceberg"
  const enforced = caps.rls === true ? "on" : caps.rls === false ? "off" : "unknown"

  const toggle = async (kind: "row" | "mask", id: string, enabled: boolean, label: string) => {
    if (enabled && !(await confirm({
      title: `Turn off ${label}?`,
      message: kind === "row"
        ? "The rows it hides become visible to the roles it names, from the next query."
        : "The column is returned unmasked to the roles it names, from the next query.",
      confirmText: "Turn off", destructive: true,
    }))) return
    const url = kind === "row" ? `/api/governance/rls/policies/${id}` : `/api/governance/masking/policies/${id}`
    const r = await fetch(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: !enabled }) })
    if (r.ok) toast(`${label} turned ${enabled ? "off" : "on"}`, "success")
    else toast(`Could not change ${label}: ${await errText(r)}`, "error")
    void load()
  }

  if (loading) return <Skeleton className="h-64" />
  if (err) return <div role="alert"><ErrorBox msg={err} action={<Button size="sm" variant="outline" onClick={() => { setLoading(true); void load() }}>Retry</Button>} /></div>

  const rows: { key: string; kind: "row" | "mask"; name: string; on: string; rule: string; roles: string[]; exempt: string[]; enabled: boolean; open: () => void }[] = [
    ...policies.map(p => ({
      key: `r${p.id}`, kind: "row" as const, name: p.name || "(unnamed)", on: `${p.catalog_name}.${p.schema_name}.${p.table_name}`,
      rule: p.filter_expression, roles: p.roles, exempt: p.exempt_roles, enabled: p.enabled,
      open: () => setEditing({ kind: "row", policy: p }),
    })),
    ...masks.map(m => ({
      key: `m${m.id}`, kind: "mask" as const, name: m.name || "(unnamed)", on: `${m.catalog_name}.${m.schema_name}.${m.table_name}.${m.column_name}`,
      rule: m.masking_type === "custom" ? m.custom_expression || "custom" : m.masking_type.replace("_", " "), roles: m.roles, exempt: [], enabled: m.enabled,
      open: () => setEditing({ kind: "mask", policy: m }),
    })),
  ]
  const editingKey = editing?.policy ? `${editing.kind === "row" ? "r" : "m"}${editing.policy.id}` : null

  return (
    <div className="space-y-4">
      <div className={`flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border px-4 py-2.5 text-sm ${enforced === "on" ? "border-[var(--dp-good)]/30" : "border-[var(--dp-warn)]/40"}`}>
        <span className="font-medium">
          <span aria-hidden className={`mr-1.5 inline-block h-2 w-2 rounded-full ${enforced === "on" ? "bg-[var(--dp-good)]" : "bg-[var(--dp-warn)]"}`} />
          {enforced === "on" ? "Enforced on the query API" : enforced === "off" ? "Not enforced: policies are records only" : "Enforcement not reported"}
        </span>
        <span className="text-xs text-muted-foreground">
          Tables without a policy: {defaultDeny === true ? "denied (default-deny on)" : defaultDeny === false ? "open (default-deny off)" : "not reported"}.
          {" "}Direct engine and object-store access is outside this boundary.
        </span>
      </div>

      <div className="flex flex-wrap items-start gap-5">
        <div className="min-w-0 flex-[3_1_520px] space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold">
              Policies <span className="text-sm font-normal text-muted-foreground">· {policies.length} row, {masks.length} column</span>
            </h3>
            {canWrite && (
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => setEditing({ kind: "mask", policy: null })}>New column mask</Button>
                <Button size="sm" onClick={() => setEditing({ kind: "row", policy: null })}>New row policy</Button>
              </div>
            )}
          </div>

          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Policy</th>
                  <th className="px-4 py-2 font-medium">Applies to</th>
                  <th className="px-4 py-2 font-medium">Rule</th>
                  <th className="px-4 py-2 font-medium">For roles</th>
                  <th className="px-4 py-2 pr-5 text-right font-medium">On</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-muted-foreground">
                    No policies yet. {defaultDeny === false ? "Every role sees every row and column of every table it may query." : ""}
                  </td></tr>
                )}
                {rows.map(r => (
                  <tr key={r.key} className={`border-b last:border-0 ${editingKey === r.key ? "bg-primary/5" : "hover:bg-muted/30"}`}>
                    <td className="px-4 py-2">
                      <button type="button" onClick={r.open} className="text-left font-medium hover:underline">{r.name}</button>
                      <div className="text-2xs text-muted-foreground">{r.kind === "row" ? "row" : "column"}</div>
                    </td>
                    <td className="max-w-[220px] truncate px-4 py-2 font-mono text-xs" title={r.on}>{r.on}</td>
                    <td className="max-w-[240px] truncate px-4 py-2 font-mono text-xs" title={r.rule}>{r.rule}</td>
                    <td className="px-4 py-2 text-xs">
                      {r.roles.join(", ") || <span className="text-muted-foreground">none</span>}
                      {r.exempt.length > 0 && <div className="text-2xs text-muted-foreground">exempt: {r.exempt.join(", ")}</div>}
                    </td>
                    <td className="px-4 py-2 pr-5 text-right">
                      <button type="button" role="switch" aria-checked={r.enabled} aria-label={`${r.name} on`}
                              disabled={!canWrite} title={canWrite ? undefined : "Changing a policy needs an administrator"}
                              onClick={() => toggle(r.kind, r.key.slice(1), r.enabled, r.name)}
                              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${r.enabled ? "bg-primary" : "bg-muted-foreground/30"}`}>
                        <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${r.enabled ? "translate-x-4" : "translate-x-0.5"}`} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <TryIt roles={roles} />
        </div>

        {editing ? (
          <PolicyEditor key={`${editing.kind}:${editing.policy?.id ?? "new"}`} editing={editing} roles={roles} lakes={lakes}
            queryCatalog={queryCatalog} canWrite={canWrite}
            onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void load() }} />
        ) : (
          <ExplainRail label="How policies work">
            <RailSection title="Row policies">
              Add a WHERE condition to every query a named role runs on the table.
              <span className="font-mono"> current_user_attribute(&apos;region&apos;)</span> reads the caller&apos;s own
              attribute, set per person in Settings → People and per agent in Agents.
            </RailSection>
            <RailSection title="Column masks">
              Replace a column&apos;s value for the named roles: *** , a hash, null, a partial value, or your own expression.
            </RailSection>
            <RailSection title="Several policies on one table">
              Every matching row policy applies. Lower priority runs first. An exempt role skips that policy only.
            </RailSection>
            {!canWrite && <p className="text-xs text-muted-foreground">Read-only: creating, changing or turning off a policy needs an administrator.</p>}
          </ExplainRail>
        )}
      </div>
    </div>
  )
}

function RolePicker({ label, roles, value, onChange, disabled }: {
  label: string; roles: Role[]; value: string[]; onChange: (v: string[]) => void; disabled?: boolean
}) {
  const names = [...new Set([...roles.map(r => r.name), ...value])]
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {names.length === 0 && <span className="text-xs text-muted-foreground">No roles found.</span>}
      {names.map(n => {
        const on = value.includes(n)
        return (
          <button key={n} type="button" aria-pressed={on} disabled={disabled}
                  onClick={() => onChange(on ? value.filter(v => v !== n) : [...value, n])}
                  className={`h-7 rounded-md border px-2.5 font-mono text-xs transition-colors disabled:opacity-50 ${on ? "border-primary bg-primary/10 font-semibold text-primary" : "bg-card hover:border-primary/50"}`}>
            {n}
          </button>
        )
      })}
    </div>
  )
}

function PolicyEditor({ editing, roles, lakes, queryCatalog, canWrite, onClose, onSaved }: {
  editing: Editing; roles: Role[]; lakes: Lake[]; queryCatalog: string; canWrite: boolean
  onClose: () => void; onSaved: () => void
}) {
  const { toast } = useToast()
  const confirm = useConfirm()
  const isRow = editing.kind === "row"
  const row = isRow ? editing.policy : null
  const mask = !isRow ? editing.policy : null
  const existing = editing.policy
  const defaultLake = lakes.find(l => l.is_default)?.engine_catalog ?? queryCatalog
  const withKind = (engine: string) => {
    const k = kindShort(lakes.find(l => l.engine_catalog === engine)?.kind)
    return k ? `${engine} · ${k}` : engine
  }

  const [name, setName] = useState(existing?.name ?? (!isRow && editing.kind === "mask" && editing.target ? `mask ${editing.target.table}.${editing.target.column}` : ""))
  const target = !isRow && editing.kind === "mask" ? editing.target : undefined
  const [catalog, setCatalog] = useState(existing?.catalog_name ?? target?.catalog ?? "")
  const [schema, setSchema] = useState(existing?.schema_name ?? target?.schema ?? "")
  const [table, setTable] = useState(existing?.table_name ?? target?.table ?? "")
  const [column, setColumn] = useState(mask?.column_name ?? target?.column ?? "")
  const [filter, setFilter] = useState(row?.filter_expression ?? "")
  const [priority, setPriority] = useState(String(row?.priority ?? 0))
  const [maskType, setMaskType] = useState(mask?.masking_type ?? "full")
  const [custom, setCustom] = useState(mask?.custom_expression ?? "")
  const [applies, setApplies] = useState<string[]>(existing?.roles ?? [])
  const [exempt, setExempt] = useState<string[]>(row?.exempt_roles ?? [])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const prio = Number.parseInt(priority, 10)
  const ready = (existing || (name.trim() && schema.trim() && table.trim() && (isRow || column.trim())))
    && (!isRow || filter.trim()) && (isRow || maskType !== "custom" || custom.trim()) && (!isRow || Number.isInteger(prio))

  const save = async () => {
    setBusy(true); setErr(null)
    try {
      let r: Response
      if (existing) {
        const body = isRow
          ? { filter_expression: filter.trim(), priority: prio, role_names: applies, exempt_role_names: exempt }
          : { masking_type: maskType, ...(maskType === "custom" ? { custom_expression: custom.trim() } : {}), role_names: applies }
        r = await fetch(`/api/governance/${isRow ? "rls" : "masking"}/policies/${existing.id}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        })
      } else {
        const base = { name: name.trim(), catalog_name: catalog || defaultLake, schema_name: schema.trim(), table_name: table.trim(), role_names: applies }
        const body = isRow
          ? { ...base, filter_expression: filter.trim(), priority: prio, exempt_role_names: exempt }
          : { ...base, column_name: column.trim(), masking_type: maskType, custom_expression: maskType === "custom" ? custom.trim() : null }
        r = await fetch(`/api/governance/${isRow ? "rls" : "masking"}/policies`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        })
      }
      // A refused save keeps the form and says why — it used to replace the whole tab.
      if (!r.ok) { setErr(await errText(r)); return }
      toast(`${existing ? "Saved" : "Created"} ${name || "policy"}`, "success")
      onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save")
    } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!existing) return
    if (!(await confirm({
      title: `Delete ${existing.name || "this policy"}?`,
      message: isRow ? "Rows it hides become visible to the roles it names. This cannot be undone." : "The column is returned unmasked to the roles it names. This cannot be undone.",
      destructive: true, confirmText: "Delete policy",
    }))) return
    const r = await fetch(`/api/governance/${isRow ? "rls" : "masking"}/policies/${existing.id}`, { method: "DELETE" })
    if (!r.ok) { setErr(await errText(r)); return }
    toast("Policy deleted", "success")
    onSaved()
  }

  const preview = isRow
    ? describeRowPolicy({ filter_expression: filter, roles: applies, exempt_roles: exempt, enabled: row?.enabled ?? true })
    : describeMask({ masking_type: maskType, column_name: column, roles: applies, enabled: mask?.enabled ?? true })

  return (
    <aside aria-label={existing ? `Edit ${existing.name ?? "policy"}` : "New policy"}
           className="min-w-0 flex-[2_1_340px] space-y-4 rounded-xl border border-primary/50 bg-muted/40 p-5 text-sm lg:sticky lg:top-6">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs text-muted-foreground">{isRow ? "Row policy" : "Column mask"}</p>
          <h3 className="text-base font-semibold">{existing ? existing.name || "(unnamed)" : isRow ? "New row policy" : "New column mask"}</h3>
        </div>
        <Button size="icon-sm" variant="ghost" aria-label="Close editor" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>

      <fieldset disabled={!canWrite || busy} className="space-y-4">
        {existing ? (
          <p className="font-mono text-xs text-muted-foreground">
            {existing.catalog_name}.{existing.schema_name}.{existing.table_name}{mask ? `.${mask.column_name}` : ""}
            <span className="block font-sans">The table{mask ? " and column" : ""} cannot change; create a new policy instead.</span>
          </p>
        ) : (
          <>
            <div className="space-y-1.5">
              <Label htmlFor="pe-name">Name</Label>
              <Input id="pe-name" value={name} onChange={e => setName(e.target.value)} placeholder={isRow ? "orders_by_region" : "mask_email"} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2 space-y-1.5">
                <Label htmlFor="pe-cat">Catalog</Label>
                <select id="pe-cat" value={catalog} onChange={e => setCatalog(e.target.value)} className={select}>
                  <option value="">{withKind(defaultLake)} (default)</option>
                  {lakes.filter(l => l.engine_catalog !== defaultLake).map(l => <option key={l.engine_catalog} value={l.engine_catalog}>{withKind(l.engine_catalog)}</option>)}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pe-schema">Schema</Label>
                <Input id="pe-schema" className="font-mono text-xs" value={schema} onChange={e => setSchema(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pe-table">Table</Label>
                <Input id="pe-table" className="font-mono text-xs" value={table} onChange={e => setTable(e.target.value)} />
              </div>
              {!isRow && (
                <div className="col-span-2 space-y-1.5">
                  <Label htmlFor="pe-col">Column</Label>
                  <Input id="pe-col" className="font-mono text-xs" value={column} onChange={e => setColumn(e.target.value)} />
                </div>
              )}
            </div>
          </>
        )}

        {isRow ? (
          <div className="space-y-1.5">
            <Label htmlFor="pe-filter">Show only rows where</Label>
            <textarea id="pe-filter" rows={3} value={filter} onChange={e => setFilter(e.target.value)}
                      placeholder="region = current_user_attribute('region')"
                      className="w-full rounded-md border bg-background px-2.5 py-2 font-mono text-xs" />
          </div>
        ) : (
          <div className="space-y-1.5">
            <Label htmlFor="pe-type">Mask as</Label>
            <select id="pe-type" value={maskType} onChange={e => setMaskType(e.target.value)} className={select}>
              {Object.entries(MASK_TEXT).map(([k, v]) => <option key={k} value={k}>{k.replace("_", " ")} — {v}</option>)}
            </select>
            {maskType === "custom" && (
              <Input aria-label="Custom expression" className="font-mono text-xs" value={custom} onChange={e => setCustom(e.target.value)}
                     placeholder="regexp_replace(email, '.+@', '***@')" />
            )}
          </div>
        )}

        <div className="space-y-1.5">
          <Label>Applies to roles</Label>
          <RolePicker label="Applies to roles" roles={roles} value={applies}
            onChange={v => { setApplies(v); setExempt(exempt.filter(x => !v.includes(x))) }} />
        </div>
        {isRow && (
          <>
            <div className="space-y-1.5">
              <Label>Exempt roles</Label>
              <RolePicker label="Exempt roles" roles={roles} value={exempt}
                onChange={v => { setExempt(v); setApplies(applies.filter(x => !v.includes(x))) }} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pe-prio">Priority</Label>
              <Input id="pe-prio" type="number" className="w-28" value={priority} onChange={e => setPriority(e.target.value)} />
              <p className="text-xs text-muted-foreground">Lower runs first when several policies match.</p>
            </div>
          </>
        )}
      </fieldset>

      <RailSection title="In words">{preview}</RailSection>
      {applies.length === 0 && <RailAttention title="No roles chosen">A policy only applies to the roles it names.</RailAttention>}

      {err && <p role="alert" className="text-xs text-destructive">{err}</p>}
      {canWrite ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={save} disabled={busy || !ready}>{busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}{existing ? "Save policy" : "Create policy"}</Button>
          <Button size="sm" variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          {existing && <Button size="sm" variant="ghost" className="ml-auto text-destructive" onClick={remove} disabled={busy}>Delete…</Button>}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">Read-only: changing a policy needs an administrator.</p>
      )}
    </aside>
  )
}

function TryIt({ roles }: { roles: Role[] }) {
  const [sql, setSql] = useState("SELECT * FROM default.orders")
  const [asRoles, setAsRoles] = useState<string[]>([])
  const [attrs, setAttrs] = useState('{"region": "us-east"}')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<PreviewResult | null>(null)

  const run = async () => {
    let attributes: Record<string, unknown>
    try {
      const parsed: unknown = JSON.parse(attrs || "{}")
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error()
      attributes = parsed as Record<string, unknown>
    } catch { setResult({ error: 'Attributes must be a JSON object, like {"region": "us-east"}.' }); return }
    setBusy(true)
    try {
      const r = await fetch("/api/governance/rls/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql, roles: asRoles, attributes }),
      })
      const d: PreviewResult = await r.json().catch(() => ({ error: `HTTP ${r.status}` }))
      setResult(r.ok ? d : { error: typeof d.detail === "string" ? d.detail : `HTTP ${r.status}` })
    } finally { setBusy(false) }
  }

  return (
    <section aria-label="Try it" className="space-y-3 rounded-xl border bg-card p-4">
      <div>
        <h3 className="text-sm font-semibold">Try it</h3>
        <p className="text-xs text-muted-foreground">See what a query becomes for a caller with these roles and attributes. Nothing runs.</p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="ti-sql">Query</Label>
        <Input id="ti-sql" className="font-mono text-xs" value={sql} onChange={e => setSql(e.target.value)} />
      </div>
      <div className="space-y-1.5">
        <Label>As roles</Label>
        <RolePicker label="As roles" roles={roles} value={asRoles} onChange={setAsRoles} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="ti-attrs">Attributes</Label>
        <Input id="ti-attrs" className="font-mono text-xs" value={attrs} onChange={e => setAttrs(e.target.value)} />
      </div>
      <Button size="sm" variant="outline" onClick={run} disabled={busy || !sql.trim()}>
        {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Run preview
      </Button>
      {result && (
        <div role={result.error || result.allowed === false ? "alert" : undefined}
             className={`rounded-md p-3 text-xs ${result.allowed ? "bg-[var(--dp-good)]/10" : "bg-destructive/10"}`}>
          {result.error ? result.error
            : result.allowed
              ? <>Allowed, rewritten to <code className="block whitespace-pre-wrap break-all pt-1 font-mono">{result.rewritten_sql}</code></>
              : <>Refused: {result.reason}</>}
        </div>
      )}
    </section>
  )
}
