"use client"

import { useState } from "react"
import Link from "next/link"
import { Database, Plus, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useCapability } from "@/lib/capabilities"
import { useToast } from "@/lib/toast"
import { attrRows, buildAttributes, grantWarning, revokeWarning, viaLabel, type AgentDetail, type AttrRow } from "@/lib/agents"
import { useConfirm } from "@/lib/confirm"
import { isInvalidRule, isRule, type StoredChunkRule } from "@/lib/chunk-rule"
import { Loading, Section, SectionError, errorText } from "./section"
import { useJson } from "./use-json"

type AccountCollection = { name: string; access: "owner" | "reader" | "editor" | "global"; chunks: number }
type CatalogRow = { catalog: string; restricted: boolean; allowed: boolean; via: "user" | "role" | "open" | null }
type CollectionInfo = { name: string; chunk_access: StoredChunkRule }

/** What this agent may read: collections, catalogs, and the attributes that chunk rules
 *  match against. Membership is edited through the per-collection members routes, the
 *  same ones the Knowledge → Members tab uses, so there is one value with two views. */
export function AccessSection({ agent, onChange }: { agent: AgentDetail; onChange: () => void }) {
  const catalogs = useCapability("catalog")
  const mine = useJson<{ collections: AccountCollection[] }>(`/api/service-accounts/${agent.id}/collections`)
  const all = useJson<{ collections: CollectionInfo[] }>("/api/ai/collections")

  return (
    <Section title="Data access" icon={<Database className="h-4 w-4 text-primary" />}
             description="A key still needs the scope (knowledge:read, ai:generate…) to use what is granted here.">
      <Collections agent={agent} mine={mine} all={all} />
      {catalogs && <Catalogs agent={agent} />}
      <Attributes agent={agent} mine={mine.data?.collections ?? null} rules={all.data?.collections ?? null} onChange={onChange} />
    </Section>
  )
}

function Collections({ agent, mine, all }: {
  agent: AgentDetail
  mine: ReturnType<typeof useJson<{ collections: AccountCollection[] }>>
  all: ReturnType<typeof useJson<{ collections: CollectionInfo[] }>>
}) {
  const { toast } = useToast()
  const [pick, setPick] = useState("")
  const [role, setRole] = useState<"reader" | "editor">("reader")
  const [busy, setBusy] = useState(false)

  const members = (name: string) => `/api/ai/collections/${encodeURIComponent(name)}/members`

  const add = async () => {
    if (!pick || busy) return
    setBusy(true)
    try {
      const res = await fetch(members(pick), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: agent.username, role }),
      })
      if (!res.ok) { toast(await errorText(res, "Could not grant access"), "error"); return }
      toast(`${agent.username} can now ${role === "editor" ? "edit" : "read"} ${pick}`, "success")
      setPick("")
      mine.reload()
    } finally { setBusy(false) }
  }

  const remove = async (name: string) => {
    setBusy(true)
    try {
      const res = await fetch(`${members(name)}?username=${encodeURIComponent(agent.username)}`, { method: "DELETE" })
      if (!res.ok) { toast(await errorText(res, "Could not remove access"), "error"); return }
      mine.reload()
    } finally { setBusy(false) }
  }

  const rows = mine.data?.collections ?? []
  // Already granted (or owned/global) collections are offered again only to change role,
  // which POST does as an upsert; global and owner rows are not changeable, so skip them.
  const pickable = (all.data?.collections ?? []).filter(c => {
    const r = rows.find(x => x.name === c.name)
    return !r || r.access === "reader" || r.access === "editor"
  })

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-medium">Collections</h4>
      {mine.loading ? <Loading what="collections" /> : mine.error && !mine.data ? (
        <SectionError message={`Collections could not be loaded: ${mine.error}`} onRetry={mine.reload} />
      ) : rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">Reads no collection yet.</p>
      ) : (
        <ul className="divide-y rounded-lg border text-xs">
          {rows.map(c => (
            <li key={c.name} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span className="flex min-w-0 items-center gap-2">
                <Link href={`/knowledge`} className="truncate font-medium hover:underline">{c.name}</Link>
                <Badge variant="outline" className="text-2xs">{c.access === "global" ? "open to every caller" : c.access}</Badge>
                <span className="text-muted-foreground">{c.chunks} chunks</span>
              </span>
              {(c.access === "reader" || c.access === "editor") && (
                <button className="text-muted-foreground hover:text-destructive disabled:opacity-40" disabled={busy}
                        aria-label={`Remove access to ${c.name}`} onClick={() => void remove(c.name)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <select value={pick} onChange={e => setPick(e.target.value)} aria-label="Collection to grant"
                className="h-8 min-w-48 flex-1 rounded-md border bg-background px-2 text-xs">
          <option value="">{all.error ? "Collections could not be listed" : "Grant a collection…"}</option>
          {pickable.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
        <select value={role} onChange={e => setRole(e.target.value as "reader" | "editor")} aria-label="Access level"
                className="h-8 rounded-md border bg-background px-2 text-xs">
          <option value="reader">reader</option>
          <option value="editor">editor</option>
        </select>
        <Button size="sm" className="h-8 gap-1 text-xs" disabled={busy || !pick} onClick={() => void add()}>
          <Plus className="h-3.5 w-3.5" />Grant
        </Button>
      </div>
    </div>
  )
}

function Catalogs({ agent }: { agent: AgentDetail }) {
  const { toast } = useToast()
  const list = useJson<{ catalogs: CatalogRow[] }>(`/api/service-accounts/${agent.id}/catalogs`)
  const [busy, setBusy] = useState(false)

  const confirm = useConfirm()

  const send = async (row: CatalogRow, method: "PUT" | "DELETE") => {
    const catalog = row.catalog
    setBusy(true)
    try {
      // The first grant restricts a catalog for everyone else and the last revoke
      // reopens it, so say so before doing either.
      let warning: string | null = null
      if (method === "PUT") warning = grantWarning(catalog, row.restricted)
      else {
        const g = await fetch(`/api/catalogs/${encodeURIComponent(catalog)}/grants`)
        if (!g.ok) { toast(await errorText(g, "Could not read the catalog's grants"), "error"); return }
        warning = revokeWarning(catalog, (await g.json()).grants ?? [], agent.id)
      }
      if (warning && !(await confirm({
        title: method === "PUT" ? "Restrict this catalog?" : "Open this catalog to everyone?",
        message: warning, confirmText: method === "PUT" ? "Grant" : "Revoke", destructive: true,
      }))) return
      const res = await fetch(`/api/catalogs/${encodeURIComponent(catalog)}/grants/user/${agent.id}`, { method })
      if (!res.ok) { toast(await errorText(res, "Could not change the grant"), "error"); return }
      list.reload()
    } finally { setBusy(false) }
  }

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-medium">Catalogs</h4>
      {list.loading ? <Loading what="catalogs" /> : list.error && !list.data ? (
        // 503 = grants unreadable. Say so; showing every catalog as open would claim
        // access that enforcement may deny.
        <SectionError message={`Catalog access could not be determined: ${list.error}`} onRetry={list.reload} />
      ) : (list.data?.catalogs ?? []).length === 0 ? (
        <p className="text-xs text-muted-foreground">No catalog is enabled.</p>
      ) : (
        <ul className="divide-y rounded-lg border text-xs">
          {list.data!.catalogs.map(c => (
            <li key={c.catalog} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span className="flex min-w-0 items-center gap-2">
                <span className="truncate font-mono">{c.catalog}</span>
                <span className={c.allowed ? "text-[var(--dp-good-text)]" : "text-muted-foreground"}>{viaLabel(c.via, agent.role)}</span>
              </span>
              {c.via === "user" ? (
                <Button size="sm" variant="ghost" className="h-7 text-xs" disabled={busy} onClick={() => void send(c, "DELETE")}>Revoke</Button>
              ) : (
                <Button size="sm" variant="outline" className="h-7 text-xs" disabled={busy} onClick={() => void send(c, "PUT")}>Grant</Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Attributes({ agent, mine, rules, onChange }: {
  agent: AgentDetail; mine: AccountCollection[] | null; rules: CollectionInfo[] | null; onChange: () => void
}) {
  const { toast } = useToast()
  const [items, setItems] = useState<AttrRow[]>(() => attrRows(agent.attributes))
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    try {
      // Whole-object replace, as PATCH /api/auth/users/{id} does. Unedited rows are
      // sent back exactly as loaded.
      const res = await fetch(`/api/auth/users/${agent.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ attributes: buildAttributes(items) }),
      })
      if (!res.ok) { toast(await errorText(res, "Could not save attributes"), "error"); return }
      toast("Attributes saved", "success")
      onChange()
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save attributes", "error")
    } finally { setBusy(false) }
  }

  const patch = (i: number, p: Partial<AttrRow>) => setItems(prev => prev.map((it, j) => (j === i ? { ...it, ...p } : it)))

  // Collections whose chunk rule reads an attribute. A rule on an attribute this agent
  // lacks withholds every chunk of that collection from it, which is easy to miss.
  const held = new Set(Object.keys(agent.attributes ?? {}))
  const used = (rules ?? []).flatMap(c => (isRule(c.chunk_access) ? [{ collection: c.name, attr: c.chunk_access.user_attribute }] : []))
  const readable = new Set((mine ?? []).map(c => c.name))
  const withheld = used.filter(u => readable.has(u.collection) && !held.has(u.attr))
  const invalid = (rules ?? []).filter(c => isInvalidRule(c.chunk_access) && readable.has(c.name))

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-medium">Attributes</h4>
      <p className="text-2xs text-muted-foreground">
        Values that chunk rules match against (for example <code className="font-mono">department</code>).
        A comma is part of the value; tick &ldquo;list&rdquo; to give several values, one per line.
      </p>
      {items.map((it, i) => (
        <div key={i} className="flex items-start gap-2">
          <Input value={it.key} onChange={e => patch(i, { key: e.target.value })} placeholder="name" aria-label="Attribute name" className="h-8 w-40 font-mono text-xs" />
          {it.isList ? (
            <textarea value={it.text} onChange={e => patch(i, { text: e.target.value })} rows={Math.max(2, it.text.split("\n").length)}
                      placeholder="one value per line" aria-label="Attribute values"
                      className="flex-1 rounded-md border bg-background px-3 py-1.5 text-xs" />
          ) : (
            <Input value={it.text} onChange={e => patch(i, { text: e.target.value })} placeholder="value" aria-label="Attribute value" className="h-8 flex-1 text-xs" />
          )}
          <label className="flex h-8 items-center gap-1 text-2xs text-muted-foreground">
            <input type="checkbox" checked={it.isList} onChange={e => patch(i, { isList: e.target.checked })} />list
          </label>
          <button className="flex h-8 items-center text-muted-foreground hover:text-destructive" aria-label="Remove attribute"
                  onClick={() => setItems(prev => prev.filter((_, j) => j !== i))}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      <div className="flex gap-2">
        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setItems(prev => [...prev, { key: "", text: "", isList: false }])}>Add attribute</Button>
        <Button size="sm" className="h-7 text-xs" disabled={busy} onClick={() => void save()}>Save attributes</Button>
      </div>
      {used.length > 0 && (
        <p className="text-2xs text-muted-foreground">
          Used by: {used.map(u => `${u.collection} (${u.attr})`).join(", ")}
        </p>
      )}
      {withheld.length > 0 && (
        <p className="text-2xs text-[var(--dp-warn-text)]">
          No value for {[...new Set(withheld.map(u => u.attr))].join(", ")}: {withheld.map(u => u.collection).join(", ")} returns
          none of its chunks to this agent.
        </p>
      )}
      {invalid.length > 0 && (
        <p className="text-2xs text-[var(--dp-warn-text)]">
          {invalid.map(c => c.name).join(", ")} has a chunk rule that no longer parses and returns nothing to anyone.
        </p>
      )}
    </div>
  )
}
