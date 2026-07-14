"use client"

import { useEffect, useState, useCallback } from "react"
import { useToast } from "@/lib/toast"
import Link from "next/link"
import { Sparkles, Plus, Trash2, Search, MessageSquare, Database, Upload, AlertCircle, Loader2, FileText, ShieldCheck, Clock, Users } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { getUser } from "@/lib/auth"
import { useConfirm } from "@/lib/confirm"
import { ErrorBox, EmptyState } from "@/components/ui/error-box"

interface Collection {
  name: string; embed_model: string; dim: number
  description: string | null; chunks: number; created_at: string | null
  owner_id: string | null
  sources?: number; index?: string | null; last_ingested?: string | null
}

// Relative time, e.g. "just now" / "3 hr ago"
function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "Not ingested"
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return "just now"
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} hr ago`
  return `${Math.floor(s / 86400)} d ago`
}
interface Hit { source: string | null; content: string; score: number }

export default function KnowledgePage() {
  const { toast } = useToast()
  const [cols, setCols] = useState<Collection[]>([])
  const [loading, setLoading] = useState(true)
  const [sel, setSel] = useState<string | null>(null)
  const [egress, setEgress] = useState<string>("")
  const [err, setErr] = useState<string | null>(null)
  const me = getUser()
  const confirm = useConfirm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch("/api/ai/collections")
      const d = await r.json()
      const list: Collection[] = d.collections || []
      setCols(list)
      setSel(s => s && list.some(c => c.name === s) ? s : (list[0]?.name ?? null))
    } catch { setErr("Failed to load collections") }
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
    fetch("/api/settings/ai/status").then(r => r.json()).then(d => setEgress(d.egress_policy || "")).catch(() => {})
  }, [load])

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" /> Knowledge
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Vector collections & RAG over your data — embeddings and chat run through the
            governed LiteLLM gateway (PII-masked at ingest{egress === "local-only" ? ", no data egress" : ""}).
          </p>
        </div>
        <div className="flex items-center gap-2">
          {egress && (
            <Badge variant="outline" className={egress === "local-only" ? "border-[var(--dp-good)]/30 text-[var(--dp-good)]" : ""}>
              AI egress: {egress}
            </Badge>
          )}
          <CreateCollection onCreated={load} />
        </div>
      </div>

      {err && (
        <div className="flex items-center gap-2 rounded-lg border border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/5 px-4 py-2.5 text-xs text-[var(--dp-warn)]">
          <AlertCircle className="h-4 w-4 shrink-0" />{err}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-5">
        {/* Collections list */}
        <div className="space-y-2">
          {loading ? [0, 1, 2].map(i => <Skeleton key={i} className="h-16 rounded-lg" />)
            : cols.length === 0 ? (
              <Card><CardContent>
                <EmptyState
                  icon={Sparkles}
                  title="No collections yet"
                  hint="Create one with New Collection above, or send data straight from a table's ✨ (Send to Knowledge) action in Catalog."
                  action={<Button size="sm" variant="outline" render={<Link href="/catalog" />}>Send from Catalog</Button>}
                />
              </CardContent></Card>
            ) : cols.map(c => (
              <Card key={c.name}
                className={`cursor-pointer transition ${sel === c.name ? "border-primary ring-1 ring-primary" : "hover:border-muted-foreground/30"}`}
                onClick={() => setSel(c.name)}>
                <CardContent className="py-3 px-4">
                  <div className="flex items-center justify-between">
                    <div className="font-medium text-sm flex items-center gap-1.5">
                      <Database className="h-3.5 w-3.5 text-muted-foreground" />{c.name}
                      {c.owner_id === null
                        ? <Badge variant="outline" className="text-[9px] gap-0.5"><Users className="h-2.5 w-2.5" />shared</Badge>
                        : (me && c.owner_id !== me.id)
                          ? <Badge variant="outline" className="text-[9px]">other</Badge>
                          : null}
                    </div>
                    {(me?.role === "admin" || (c.owner_id !== null && me?.id === c.owner_id)) && (
                      <button aria-label={`Delete collection ${c.name}`} onClick={e => { e.stopPropagation(); deleteCol(c.name, load, confirm, toast) }}
                        className="text-muted-foreground hover:text-destructive"><Trash2 className="h-3.5 w-3.5" /></button>
                    )}
                  </div>
                  <div className="dp-num text-[11px] text-muted-foreground mt-1 flex flex-wrap gap-x-2 gap-y-0.5">
                    <span>{c.chunks} vectors</span>·<span>{c.embed_model} ({c.dim}d)</span>
                    {c.sources != null && <><span>·</span><span>{c.sources} sources</span></>}
                  </div>
                  <div className="text-[10px] text-muted-foreground/70 mt-0.5 flex flex-wrap gap-x-2 items-center">
                    <Badge variant="outline" className="text-[9px] gap-0.5"><Database className="h-2.5 w-2.5" />{c.index || "HNSW · cosine"}</Badge>
                    <span className="flex items-center gap-0.5"><Clock className="h-2.5 w-2.5" />Last ingested {timeAgo(c.last_ingested)}</span>
                  </div>
                  {c.description && <div className="text-[11px] text-muted-foreground mt-0.5 truncate">{c.description}</div>}
                </CardContent>
              </Card>
            ))}
        </div>

        {/* Selected collection workspace */}
        <div>
          {sel ? <Workspace key={sel} name={sel} onChange={load} empty={(cols.find(c => c.name === sel)?.chunks ?? 0) === 0} />
            : <Card><CardContent>
                <EmptyState
                  icon={Sparkles}
                  title="Select a collection"
                  hint="Choose a collection on the left to search it or ask a question with RAG — or create one with New Collection to start ingesting data."
                />
              </CardContent></Card>}
        </div>
      </div>
    </div>
  )
}

async function deleteCol(name: string, after: () => void, confirm: (o: any) => Promise<boolean>, notify?: (m: string, t?: any) => void) {
  if (!(await confirm({ title: "Delete collection", message: `This deletes "${name}" and all its chunks. This cannot be undone.`, destructive: true, confirmText: "Delete" }))) return
  await fetch(`/api/ai/collections/${encodeURIComponent(name)}`, { method: "DELETE" })
  notify?.(`Collection "${name}" deleted`, "success")
  after()
}

function CreateCollection({ onCreated }: { onCreated: () => void }) {
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(""); const [desc, setDesc] = useState("")
  const [busy, setBusy] = useState(false); const [e, setE] = useState<string | null>(null)
  const submit = async () => {
    if (!name.trim()) return
    setBusy(true); setE(null)
    try {
      const r = await fetch("/api/ai/collections", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), description: desc || undefined }),
      })
      if (!r.ok) throw new Error((await r.json()).detail || "Create failed")
      setOpen(false); toast(`Collection "${name.trim()}" created`, "success"); setName(""); setDesc(""); onCreated()
    } catch (err: any) { setE(err.message) }
    setBusy(false)
  }
  return (
    <>
      <Button size="sm" className="gap-1.5" onClick={() => setOpen(true)}><Plus className="h-3.5 w-3.5" />New Collection</Button>
      <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogHeader><DialogTitle>New Collection</DialogTitle></DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1.5"><Label className="text-xs">Name</Label>
            <Input value={name} onChange={e => setName(e.target.value)} placeholder="kb_docs" className="font-mono" /></div>
          <div className="space-y-1.5"><Label className="text-xs">Description</Label>
            <Input value={desc} onChange={e => setDesc(e.target.value)} placeholder="optional" /></div>
          {e && <ErrorBox msg={e} />}
          <Button onClick={submit} disabled={!name.trim() || busy} className="w-full">
            {busy && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}Create</Button>
        </div>
      </DialogContent>
    </Dialog>
    </>
  )
}

function Workspace({ name, onChange, empty }: { name: string; onChange: () => void; empty: boolean }) {
  return (
    <Card>
      <CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2">
        <Database className="h-4 w-4" />{name}</CardTitle>
        <CardDescription>Ingest documents, then search or ask with RAG.</CardDescription></CardHeader>
      <CardContent>
        {/* An empty collection has nothing to search — open on Ingest so the first step is obvious. */}
        <Tabs defaultValue={empty ? "ingest" : "search"}>
          <TabsList><TabsTrigger value="search"><Search className="h-3.5 w-3.5 mr-1" />Search / RAG</TabsTrigger>
            <TabsTrigger value="ingest"><Upload className="h-3.5 w-3.5 mr-1" />Ingest</TabsTrigger></TabsList>
          <TabsContent value="search"><SearchPanel name={name} /></TabsContent>
          <TabsContent value="ingest"><IngestPanel name={name} onChange={onChange} /></TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

function SearchPanel({ name }: { name: string }) {
  const [q, setQ] = useState(""); const [mode, setMode] = useState<"search" | "rag">("rag")
  const [busy, setBusy] = useState(false); const [ans, setAns] = useState<string | null>(null)
  const [hits, setHits] = useState<Hit[]>([]); const [e, setE] = useState<string | null>(null)
  const [pii, setPii] = useState(0)
  const run = async () => {
    if (!q.trim()) return
    setBusy(true); setE(null); setAns(null); setHits([]); setPii(0)
    try {
      if (mode === "rag") {
        const r = await fetch("/api/ai/rag", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ collection: name, question: q, k: 5 }) })
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
        const d = await r.json(); setAns(d.answer); setHits(d.citations || []); setPii(d.pii_masked || 0)
      } else {
        const r = await fetch("/api/ai/search", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ collection: name, query: q, k: 8 }) })
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
        const d = await r.json(); setHits(d.results || []); setPii(d.pii_masked || 0)
      }
    } catch (err: any) { setE(err.message) }
    setBusy(false)
  }
  return (
    <div className="space-y-3 pt-3">
      <div className="flex gap-2">
        <Input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && run()}
          placeholder="Ask a question…" />
        <div className="flex rounded-md border overflow-hidden">
          {(["rag", "search"] as const).map(m => (
            <button key={m} onClick={() => setMode(m)}
              className={`px-3 text-xs ${mode === m ? "bg-primary text-primary-foreground" : "bg-background"}`}>
              {m === "rag" ? "RAG" : "Search"}</button>
          ))}
        </div>
        <Button onClick={run} disabled={!q.trim() || busy}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquare className="h-4 w-4" />}</Button>
      </div>
      {pii > 0 && <div className="text-[11px] text-[var(--dp-good)] flex items-center gap-1"><ShieldCheck className="h-3 w-3" />{pii} PII item(s) masked before processing (guardrail)</div>}
      {e && <ErrorBox msg={e} />}
      {ans && (
        <Card className="dp-surface">
          <CardContent className="py-3">
            <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
              <Sparkles className="h-3 w-3 text-primary" />Answer
            </div>
            <div className="text-sm leading-relaxed whitespace-pre-wrap">{ans}</div>
          </CardContent>
        </Card>
      )}
      {hits.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">{mode === "rag" ? "Citations" : "Results"}</p>
          {hits.map((h, i) => (
            <div key={i} className="rounded-md border px-3 py-2 text-xs">
              <div className="flex items-center justify-between text-[11px] text-muted-foreground mb-1">
                <span className="flex items-center gap-1"><FileText className="h-3 w-3" />{h.source || "n/a"}</span>
                <Badge variant="outline" className="dp-num text-[10px]">{h.score?.toFixed(3)}</Badge>
              </div>
              <div className="line-clamp-3">{h.content}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function IngestPanel({ name, onChange }: { name: string; onChange: () => void }) {
  const [tab, setTab] = useState<"text" | "source">("text")
  const [text, setText] = useState(""); const [src, setSrc] = useState("")
  const [stype, setStype] = useState<"iceberg" | "s3">("iceberg")
  const [schema, setSchema] = useState("default"); const [table, setTable] = useState(""); const [col, setCol] = useState("")
  const [bucket, setBucket] = useState(""); const [prefix, setPrefix] = useState("")
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<string | null>(null); const [e, setE] = useState<string | null>(null)
  const [sched, setSched] = useState("@daily"); const [schedBusy, setSchedBusy] = useState(false)
  // Lakehouse picker: iceberg catalog tree (schemas→tables) + columns of the chosen table.
  const [tree, setTree] = useState<{ schema: string; tables: string[] }[]>([])
  const [cols, setCols] = useState<{ name: string; type: string }[]>([])

  useEffect(() => {
    fetch("/api/catalog/schemas").then(r => r.json()).then(d => {
      const ice = (d.catalogs || []).find((c: any) => c.name === "iceberg") || (d.catalogs || [])[0]
      const sc = (ice?.schemas || []).map((s: any) => ({ schema: s.name, tables: (s.tables || []).map((t: any) => t.name) }))
      setTree(sc)
    }).catch(() => {})
  }, [])
  // When a table is picked, lazily fetch its columns to populate the text-column select.
  useEffect(() => {
    if (stype !== "iceberg" || !schema || !table) { setCols([]); return }
    const qs = new URLSearchParams({ catalog: "iceberg", schema, table })
    fetch(`/api/catalog/columns?${qs}`).then(r => r.json())
      .then((c) => { const list = Array.isArray(c) ? c : []; setCols(list); if (list.length && !list.find((x: any) => x.name === col)) setCol(list[0].name) })
      .catch(() => setCols([]))
  }, [schema, table, stype])  // eslint-disable-line react-hooks/exhaustive-deps
  const sourceBody = () => stype === "iceberg"
    ? { type: "iceberg", schema, table, text_column: col }
    : { type: "s3", bucket, prefix }

  const ingestText = async () => {
    setBusy(true); setE(null); setMsg(null)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}/ingest`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ documents: [{ source: src || "manual", text }] }) })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      const d = await r.json(); setMsg(`Ingested ${d.chunks} chunks (${d.pii_masked} PII masked)`); setText(""); onChange()
    } catch (err: any) { setE(err.message) }
    setBusy(false)
  }
  const ingestSource = async () => {
    setBusy(true); setE(null); setMsg(null)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}/ingest-source`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sourceBody()) })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      const d = await r.json(); setMsg(`${d.documents} docs → ${d.chunks} chunks (${d.pii_masked} PII masked)`); onChange()
    } catch (err: any) { setE(err.message) }
    setBusy(false)
  }
  const scheduleSource = async () => {
    setSchedBusy(true); setE(null); setMsg(null)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}/schedule`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schedule: sched, source: sourceBody() }) })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      const d = await r.json(); setMsg(`Schedule created: auto re-embeds every ${d.interval_minutes} min`)
    } catch (err: any) { setE(err.message) }
    setSchedBusy(false)
  }

  return (
    <div className="space-y-3 pt-3">
      <div className="flex rounded-md border overflow-hidden w-fit text-xs">
        {(["text", "source"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} className={`px-3 py-1 ${tab === t ? "bg-primary text-primary-foreground" : "bg-background"}`}>
            {t === "text" ? "Paste text" : "From catalog / S3"}</button>
        ))}
      </div>
      {tab === "text" ? (
        <>
          <Input value={src} onChange={e => setSrc(e.target.value)} placeholder="source label (optional)" className="text-sm" />
          <Textarea value={text} onChange={e => setText(e.target.value)} placeholder="Paste documents to embed…" className="min-h-[160px] text-sm" />
          <Button onClick={ingestText} disabled={!text.trim() || busy}>{busy && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}Ingest</Button>
        </>
      ) : (
        <>
          <div className="flex rounded-md border overflow-hidden w-fit text-xs">
            {(["iceberg", "s3"] as const).map(t => (
              <button key={t} onClick={() => setStype(t)} className={`px-3 py-1 ${stype === t ? "bg-primary text-primary-foreground" : "bg-background"}`}>{t}</button>
            ))}
          </div>
          {stype === "iceberg" ? (
            tree.length > 0 ? (
              <div className="grid grid-cols-3 gap-2">
                <select value={schema} onChange={e => { setSchema(e.target.value); setTable("") }}
                  className="h-9 rounded-md border bg-background px-2 text-xs">
                  <option value="">schema…</option>
                  {tree.map(s => <option key={s.schema} value={s.schema}>{s.schema}</option>)}
                </select>
                <select value={table} onChange={e => setTable(e.target.value)}
                  className="h-9 rounded-md border bg-background px-2 text-xs" disabled={!schema}>
                  <option value="">table…</option>
                  {(tree.find(s => s.schema === schema)?.tables || []).map(t => <option key={t} value={t}>{t}</option>)}
                </select>
                <select value={col} onChange={e => setCol(e.target.value)}
                  className="h-9 rounded-md border bg-background px-2 text-xs" disabled={!table}>
                  <option value="">text column…</option>
                  {cols.map(c => <option key={c.name} value={c.name}>{c.name} ({c.type})</option>)}
                </select>
              </div>
            ) : (
              // Fallback to manual entry if the catalog tree is unavailable.
              <div className="grid grid-cols-3 gap-2">
                <Input value={schema} onChange={e => setSchema(e.target.value)} placeholder="schema" className="text-sm" />
                <Input value={table} onChange={e => setTable(e.target.value)} placeholder="table" className="text-sm" />
                <Input value={col} onChange={e => setCol(e.target.value)} placeholder="text_column" className="text-sm" />
              </div>
            )
          ) : (
            <div className="grid grid-cols-2 gap-2">
              <Input value={bucket} onChange={e => setBucket(e.target.value)} placeholder="bucket" className="text-sm" />
              <Input value={prefix} onChange={e => setPrefix(e.target.value)} placeholder="prefix (optional)" className="text-sm" />
            </div>
          )}
          {(() => { const ready = stype === "iceberg" ? !!(table && col) : !!bucket; return (
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={ingestSource} disabled={busy || schedBusy || !ready}>
                {busy && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}Ingest from {stype}</Button>
              <span className="text-xs text-muted-foreground ml-1">or schedule:</span>
              <select value={sched} onChange={e => setSched(e.target.value)}
                className="h-9 rounded-md border bg-background px-2 text-xs">
                <option value="@hourly">Hourly</option>
                <option value="@daily">Daily</option>
                <option value="@weekly">Weekly</option>
              </select>
              <Button variant="outline" onClick={scheduleSource} disabled={busy || schedBusy || !ready}>
                {schedBusy ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Clock className="h-4 w-4 mr-1.5" />}
                Schedule ingest</Button>
            </div>
          )})()}
          <p className="text-[11px] text-muted-foreground">Scheduled ingest re-embeds the source on an interval — and automatically whenever a connector sync updates the source table, so retrieval stays fresh.</p>
        </>
      )}
      {msg && <p className="text-xs text-[var(--dp-good)]">{msg}</p>}
      {e && <ErrorBox msg={e} />}
    </div>
  )
}
