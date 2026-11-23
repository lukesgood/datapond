"use client"

import { useEffect, useRef, useState } from "react"
import NextLink from "next/link"
import { Loader2, X } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ChoiceGroup } from "@/components/ui/choice-group"
import { RailAttention, RailSection } from "@/components/ui/explain-rail"
import { tableSelectSql } from "@/lib/catalog-sql"
import { CatalogKindBadge } from "@/components/catalog/kind-badge"
import { CopyName, TableStatus } from "@/components/catalog/table-status"
import type { TableFacts } from "@/lib/catalog-view"
import { displayId, evidenceLabel, neighbours, type RelGraph } from "@/lib/relationship-view"
import { useToast } from "@/lib/toast"

export interface CatalogTable {
  name: string
  namespace: string
  /** The engine's name for the catalog (`iceberg`, `polaris_lake`, `src_…`). */
  catalog: string
  table_type: string
  last_updated?: string
  mirror_of?: string | null
  synced_from?: TableFacts["synced_from"]
  live?: boolean
}

interface Detail { row_count?: number | null; columns: { name: string; type: string }[]; location?: string }

const qs = (t: CatalogTable) => (t.catalog ? `?catalog=${encodeURIComponent(t.catalog)}` : "")
export const tableHref = (t: CatalogTable) =>
  `/catalog/${encodeURIComponent(t.namespace)}/${encodeURIComponent(t.name)}${qs(t)}`

/** One table, in the right column of the catalog: what it is, its first columns, the
 *  tables people join it to, and the actions. It replaces a grid of cards that said
 *  nothing but the name, and a relationship graph that filled the screen first. */
export function TableRail({ table, typeLabel, catalogKind, connectionId, graph, graphNode, sole, canSend, onSend, onClose, onPickJoined }: {
  table: CatalogTable
  typeLabel: string
  /** Registry kind of the table's catalog, for the badge beside its name. */
  catalogKind?: string
  /** For a source catalog: the connection that owns it, for "Sync it into the lake". */
  connectionId?: string | null
  /** Select another table from "Joined with" (a graph node id). */
  onPickJoined?: (nodeId: string) => void
  graph: RelGraph | null
  graphNode: string | null
  sole: string | null
  canSend: boolean
  onSend: () => void
  onClose: () => void
}) {
  const [detail, setDetail] = useState<Detail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/catalog/tables/${encodeURIComponent(table.namespace)}/${encodeURIComponent(table.name)}${qs(table)}`)
      .then(async r => {
        if (!r.ok) throw new Error(`Could not read the table (HTTP ${r.status})`)
        return r.json() as Promise<Detail>
      })
      .then(d => { if (!cancelled) { setDetail(d); setErr(null) } })
      .catch(e => { if (!cancelled) setErr(e instanceof Error ? e.message : "Could not read the table") })
    return () => { cancelled = true }
  }, [table, attempt])

  // Below the two-column width the rail opens under the whole list, off screen: bring
  // it into view and move focus to it, so selecting a table visibly does something.
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (!window.matchMedia("(max-width: 1023px)").matches) return
    heading.current?.scrollIntoView({ behavior: "smooth", block: "start" })
    heading.current?.focus({ preventScroll: true })
  }, [table])

  const joins = graph && graphNode ? neighbours(graph, graphNode).slice(0, 5) : []
  const sql = tableSelectSql(table.namespace, table.name, table.catalog || null)

  return (
    <aside aria-label={`About ${table.name}`}
           className="min-w-0 flex-[2_1_300px] space-y-4 rounded-xl border border-primary/50 bg-muted/40 p-5 text-sm lg:sticky lg:top-6">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex min-w-0 items-center gap-1.5 font-mono text-xs text-muted-foreground">
            <span className="truncate">{table.catalog}.{table.namespace}</span>
            <CatalogKindBadge kind={catalogKind} />
          </p>
          <h3 ref={heading} tabIndex={-1} className="truncate text-base font-semibold focus:outline-none">{table.name}</h3>
          <p className="text-xs text-muted-foreground">{typeLabel}</p>
        </div>
        <Button size="icon-sm" variant="ghost" aria-label="Close table details" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>

      <TableStatus facts={table} connectionId={connectionId} />

      {err ? (
        <RailAttention title="Could not read this table" tone="bad">
          {err} <button className="underline" onClick={() => { setErr(null); setDetail(null); setAttempt(a => a + 1) }}>Retry</button>
        </RailAttention>
      ) : !detail ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />Reading the table…</p>
      ) : (
        <dl className="grid grid-cols-2 gap-3">
          <div><dt className="text-xs text-muted-foreground">Rows</dt><dd className="dp-num text-lg font-semibold">{detail.row_count != null ? detail.row_count.toLocaleString() : "—"}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Columns</dt><dd className="dp-num text-lg font-semibold">{detail.columns.length}</dd></div>
        </dl>
      )}

      <div className="flex flex-wrap gap-2">
        <NextLink href={`/query?sql=${encodeURIComponent(sql)}`} className={buttonVariants({ size: "sm" })}>Open in Analytics</NextLink>
        <NextLink href={tableHref(table)} className={buttonVariants({ size: "sm", variant: "outline" })}>Open table</NextLink>
        {canSend && <Button size="sm" variant="outline" onClick={onSend}>Send to Knowledge</Button>}
        <CopyName name={`${table.catalog}.${table.namespace}.${table.name}`} />
      </div>

      {detail && detail.columns.length > 0 && (
        <RailSection title="Columns">
          <ul className="space-y-0.5">
            {detail.columns.slice(0, 6).map(c => (
              <li key={c.name} className="flex justify-between gap-3 font-mono text-xs">
                <span className="truncate text-foreground">{c.name}</span><span className="shrink-0">{c.type}</span>
              </li>
            ))}
          </ul>
          {detail.columns.length > 6 && (
            <NextLink href={tableHref(table)} className="mt-1 inline-block text-xs text-primary hover:underline">
              All {detail.columns.length} columns
            </NextLink>
          )}
        </RailSection>
      )}

      <RailSection title="Joined with">
        {!graph ? (
          <p className="text-xs">Reading query history…</p>
        ) : joins.length === 0 ? (
          <p className="text-xs">No joins with this table in the last {graph.window_days ?? 30} days. Running one in Analytics adds it here.</p>
        ) : (
          <>
            <p className="text-xs">From joins people ran in the last {graph.window_days ?? 30} days (AI-generated queries not counted) and foreign keys the source database declares.</p>
            <ul className="mt-1.5 space-y-1">
              {joins.map(j => (
                <li key={j.other} className="text-xs">
                  {onPickJoined
                    ? <button type="button" className="font-mono text-primary hover:underline focus-visible:underline focus-visible:outline-none"
                              onClick={() => onPickJoined(j.other)}>{displayId(j.other, sole)}</button>
                    : <span className="font-mono text-foreground">{displayId(j.other, sole)}</span>}
                  <span className="text-muted-foreground"> · {evidenceLabel(j)}</span>
                  {j.on && <div className="truncate font-mono text-2xs" title={displayId(j.on, sole)}>on {displayId(j.on, sole)}</div>}
                </li>
              ))}
            </ul>
          </>
        )}
      </RailSection>
    </aside>
  )
}

interface Collection { name: string }
type Schedule = "" | "@hourly" | "@daily" | "@weekly"
const ROWS_PER_RUN = 1000   // SourceIngest.limit's default on the backend

/** Send a table's text column to a Knowledge collection — in the rail, with what it
 *  will cost and do beside the controls. It was a dialog of three unlabelled native
 *  selects, it sent a table from a second catalog as the default catalog's table of
 *  the same name, and a failed collection create was ignored. */
export function SendToKnowledgePanel({ table, onClose }: { table: CatalogTable; onClose: () => void }) {
  const { toast } = useToast()
  const [collections, setCollections] = useState<Collection[] | null>(null)
  const [collection, setCollection] = useState("")
  const [newName, setNewName] = useState("")
  const [cols, setCols] = useState<{ name: string; type: string }[] | null>(null)
  const [col, setCol] = useState("")
  const [sched, setSched] = useState<Schedule>("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState<{ target: string; text: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch("/api/ai/collections").then(r => (r.ok ? r.json() : { collections: [] }))
      .then((d: { collections?: Collection[] }) => {
        if (cancelled) return
        const list = d.collections ?? []
        setCollections(list); setCollection(list[0]?.name ?? "__new__")
      }).catch(() => { if (!cancelled) { setCollections([]); setCollection("__new__") } })
    const q = new URLSearchParams({ ...(table.catalog ? { catalog: table.catalog } : {}), schema: table.namespace, table: table.name })
    fetch(`/api/catalog/columns?${q}`).then(r => (r.ok ? r.json() : []))
      .then((payload: unknown) => {
        if (cancelled) return
        const list = Array.isArray(payload) ? payload as { name: string; type: string }[] : []
        setCols(list); setCol(list.find(c => /char|text|string/i.test(c.type))?.name ?? list[0]?.name ?? "")
      }).catch(() => { if (!cancelled) setCols([]) })
    return () => { cancelled = true }
  }, [table])

  const target = (collection === "__new__" ? newName : collection).trim()
  const detail = async (r: Response) => {
    const d = await r.json().catch(() => ({}))
    return typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`
  }

  const submit = async () => {
    if (!target || !col) { setErr("Choose a collection and a text column."); return }
    setBusy(true); setErr(null)
    try {
      if (collection === "__new__") {
        const r = await fetch("/api/ai/collections", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: target, description: `From ${table.namespace}.${table.name}` }),
        })
        // 409: it already exists, which is what we wanted.
        if (!r.ok && r.status !== 409) { setErr(`Could not create the collection: ${await detail(r)}`); return }
      }
      const source = { type: "iceberg", catalog: table.catalog || undefined, schema: table.namespace, table: table.name, text_column: col }
      const url = `/api/ai/collections/${encodeURIComponent(target)}/${sched ? "schedule" : "ingest-source"}`
      const r = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sched ? { schedule: sched, source } : source),
      })
      if (!r.ok) { setErr(await detail(r)); return }
      const d = await r.json().catch(() => ({}))
      const text = sched
        ? `Scheduled: re-embeds every ${d.interval_minutes ?? "?"} minutes.`
        : `${d.documents ?? "?"} rows became ${d.chunks ?? "?"} chunks.`
      setDone({ target, text })
      toast(`Sent ${table.name} to ${target}`, "success")
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not send the table")
    } finally { setBusy(false) }
  }

  return (
    <aside aria-label={`Send ${table.name} to Knowledge`}
           className="min-w-0 flex-[2_1_300px] space-y-4 rounded-xl border border-primary/50 bg-muted/40 p-5 text-sm lg:sticky lg:top-6">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-base font-semibold">Send <span className="font-mono">{table.name}</span> to Knowledge</h3>
        <Button size="icon-sm" variant="ghost" aria-label="Close" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>

      <fieldset disabled={busy || !!done} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="stk-coll">Collection</Label>
          <select id="stk-coll" value={collection} onChange={e => setCollection(e.target.value)} disabled={collections === null}
                  className="h-9 w-full rounded-md border bg-background px-2 text-sm">
            {collections === null && <option value="">Loading…</option>}
            {(collections ?? []).map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
            <option value="__new__">New collection…</option>
          </select>
          {collection === "__new__" && (
            <Input aria-label="New collection name" value={newName} onChange={e => setNewName(e.target.value)} placeholder="Name" />
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="stk-col">Text column</Label>
          <select id="stk-col" value={col} onChange={e => setCol(e.target.value)} disabled={cols === null}
                  className="h-9 w-full rounded-md border bg-background px-2 font-mono text-xs">
            {cols === null && <option value="">Loading columns…</option>}
            {cols?.length === 0 && <option value="">No columns found</option>}
            {(cols ?? []).map(c => <option key={c.name} value={c.name}>{c.name} ({c.type})</option>)}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label>Keep it fresh</Label>
          <ChoiceGroup<Schedule> label="Keep it fresh" value={sched} onChange={setSched}
            options={[{ label: "Once, now", value: "" }, { label: "Hourly", value: "@hourly" }, { label: "Daily", value: "@daily" }, { label: "Weekly", value: "@weekly" }]} />
        </div>
      </fieldset>

      <RailSection title="What happens">
        Each row&apos;s <span className="font-mono">{col || "text column"}</span> becomes a document, masked by the
        collection&apos;s PII mode before it is embedded. Up to the first {ROWS_PER_RUN.toLocaleString()} rows are read
        per run, and the embedding is billed to you.
        {sched ? " Each scheduled run replaces the chunks the previous one made." : ""}
      </RailSection>

      {err && <p role="alert" className="text-xs text-destructive">{err}</p>}
      {done ? (
        <div className="space-y-2">
          <p className="text-xs text-[var(--dp-good-text)]">{done.text}</p>
          <div className="flex gap-2">
            <NextLink href={`/knowledge?collection=${encodeURIComponent(done.target)}`} className={buttonVariants({ size: "sm" })}>Open in Knowledge</NextLink>
            <Button size="sm" variant="ghost" onClick={onClose}>Close</Button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2">
          <Button size="sm" onClick={submit} disabled={busy || !target || !col}>
            {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}{sched ? "Schedule" : "Send now"}
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
        </div>
      )}
    </aside>
  )
}
