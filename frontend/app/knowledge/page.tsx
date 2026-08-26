"use client"

import { useEffect, useState, useCallback } from "react"
import { useToast } from "@/lib/toast"
import Link from "next/link"
import { Sparkles, Plus, Trash2, Search, MessageSquare, Database, Upload, AlertCircle, Loader2, FileText, ShieldCheck, Clock, Users, CheckCircle2, ArrowDownWideNarrow, BookMarked, Layers, GitBranch } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { ConceptsPanel } from "@/components/knowledge/concepts-panel"
import { ComparePanel } from "@/components/knowledge/compare-panel"
import { Markdown } from "@/components/ui/markdown"
import { MySpend } from "@/components/ai/my-spend"
import { CompositionPanel } from "@/components/knowledge/composition-panel"
import { LineagePanel } from "@/components/knowledge/lineage-panel"
import { Skeleton } from "@/components/ui/skeleton"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { getUser } from "@/lib/auth"
import { useConfirm } from "@/lib/confirm"
import { ErrorBox, EmptyState } from "@/components/ui/error-box"
import { useCapability } from "@/lib/capabilities"

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
interface Hit { source: string | null; content: string; score: number; rerank_score?: number }
interface ChunkPreset { name: string; label: string; hint: string; chunk_size: number; chunk_overlap: number }
interface CollectionsResponse { collections?: Collection[]; total?: number }
interface AiStatusResponse { egress_policy?: string }
interface CatalogColumn { name: string; type: string }
interface CatalogResponse {
  catalogs?: Array<{ name: string; schemas?: Array<{ name: string; tables?: Array<{ name: string }> }> }>
}

export default function KnowledgePage() {
  const { toast } = useToast()
  const catalogEnabled = useCapability("catalog")
  const [cols, setCols] = useState<Collection[]>([])
  const [loading, setLoading] = useState(true)
  const [sel, setSel] = useState<string | null>(null)
  // Collapsed by default: on a deployment that ingests by hand this is a list
  // of collections with no upstream, which is true but not worth the space.
  const [showLineage, setShowLineage] = useState(false)
  // Filtering server-side rather than in the browser: with a page limit the client
  // only holds a window, so filtering what it holds would search the wrong set.
  const [filter, setFilter] = useState("")
  const [total, setTotal] = useState(0)
  const [egress, setEgress] = useState<string>("")
  const [err, setErr] = useState<string | null>(null)
  const me = getUser()
  const confirm = useConfirm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: "100" })
      if (filter.trim()) params.set("q", filter.trim())
      const r = await fetch(`/api/ai/collections?${params}`)
      const d: CollectionsResponse = await r.json()
      const list = d.collections ?? []
      setCols(list)
      setTotal(d.total ?? list.length)
      // Keep the selection when it survives the filter; otherwise fall to the first
      // match, so typing never leaves the workspace showing something not in the list.
      setSel(s => s && list.some(c => c.name === s) ? s : (list[0]?.name ?? null))
    } catch { setErr("Failed to load collections") }
    setLoading(false)
  }, [filter])

  // Debounced, because `load` now changes with the filter text: without this every
  // keystroke is a request, and the last one to arrive wins rather than the last one
  // typed.
  useEffect(() => {
    const t = window.setTimeout(() => void load(), 250)
    return () => window.clearTimeout(t)
  }, [load])

  // Once. It used to refetch alongside the collection list, which had nothing to do
  // with it.
  useEffect(() => {
    fetch("/api/settings/ai/status")
      .then(r => r.json() as Promise<AiStatusResponse>)
      .then(d => setEgress(d.egress_policy ?? ""))
      .catch(() => {})
  }, [])

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
        {/* Collections list. Bounded and filterable: it used to render every
            collection into an unbounded column, so a deployment with a few hundred
            stretched the page far below the workspace it sits beside, with no way to
            find one but to read them all. */}
        <div className="space-y-2">
          {(cols.length > 8 || filter) && (
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input value={filter} onChange={e => setFilter(e.target.value)}
                     placeholder={`Filter ${total || cols.length} collections…`}
                     className="h-8 pl-7 text-xs" />
            </div>
          )}
          <div className="max-h-[calc(100vh-16rem)] space-y-2 overflow-y-auto pr-1">
          {loading ? [0, 1, 2].map(i => <Skeleton key={i} className="h-16 rounded-lg" />)
            : cols.length === 0 ? (
              <Card><CardContent>
                <EmptyState
                  icon={Sparkles}
                  title="No collections yet"
                  hint={catalogEnabled
                    ? "Create one above, or send a table to Knowledge from the enabled Catalog module."
                    : "Create a collection above, then ingest text or an S3 source directly."}
                  action={catalogEnabled
                    ? <Button size="sm" variant="outline" render={<Link href="/catalog" />}>Send from Catalog</Button>
                    : undefined}
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
          {total > cols.length && (
            <p className="text-center text-[11px] text-muted-foreground">
              Showing {cols.length} of {total}. Narrow the filter to find the rest.
            </p>
          )}
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

      {/* Personal model spend lives here rather than on the API page, which is about
          what an *application* costs, and rather than AI Gateway, which reports the
          whole deployment and needs a permission data_scientist does not hold.
          Knowledge is where a person spends tokens, so it is where they see it. */}
      <MySpend />

      {/* Lineage spans collections, so it belongs to the page rather than to the
          selected one — the question it answers ("this table changed, what is now
          stale?") starts from a source, not from a collection. */}
      <Card>
        <CardHeader className="pb-2 flex-row items-center justify-between">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-primary" />Lineage
            </CardTitle>
            <CardDescription>What feeds each collection, and what a source change makes stale.</CardDescription>
          </div>
          <button onClick={() => setShowLineage(v => !v)}
                  className="text-[11px] text-muted-foreground hover:text-foreground">
            {showLineage ? "Hide" : "Show"}
          </button>
        </CardHeader>
        {showLineage && <CardContent className="pt-0"><LineagePanel /></CardContent>}
      </Card>
    </div>
  )
}

async function deleteCol(name: string, after: () => void, confirm: ReturnType<typeof useConfirm>, notify?: ReturnType<typeof useToast>["toast"]) {
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
  // Presets come from the server, with their numbers and what each is for. A copy of
  // that list here is a copy that goes stale.
  const [presets, setPresets] = useState<ChunkPreset[]>([])
  const [preset, setPreset] = useState("standard")
  useEffect(() => {
    let cancelled = false
    fetch("/api/ai/chunk-presets").then(r => (r.ok ? r.json() : null)).then(d => {
      if (cancelled || !d) return
      setPresets(d.presets || []); setPreset(d.default || "standard")
    }).catch(() => {})
    return () => { cancelled = true }
  }, [])
  const submit = async () => {
    if (!name.trim()) return
    setBusy(true); setE(null)
    try {
      const r = await fetch("/api/ai/collections", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), description: desc || undefined,
                               chunk_preset: preset }),
      })
      if (!r.ok) throw new Error((await r.json()).detail || "Create failed")
      setOpen(false); toast(`Collection "${name.trim()}" created`, "success"); setName(""); setDesc(""); onCreated()
    } catch (error) { setE(error instanceof Error ? error.message : "Create failed") }
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
          {presets.length > 0 && (
            <div className="space-y-1.5">
              <Label className="text-xs">How documents are split</Label>
              <div className="grid gap-1.5">
                {presets.map(p => (
                  <button key={p.name} type="button" onClick={() => setPreset(p.name)}
                    aria-pressed={preset === p.name}
                    className={`flex items-center justify-between rounded-md border px-2.5 py-2 text-left text-xs transition-colors ${
                      preset === p.name ? "border-primary/50 bg-primary/5" : "hover:bg-muted/40"}`}>
                    <span>
                      <span className="font-medium">{p.label}</span>
                      <span className="ml-1.5 text-muted-foreground">{p.hint}</span>
                    </span>
                    <span className="dp-num shrink-0 text-[10px] text-muted-foreground">
                      {p.chunk_size}/{p.chunk_overlap}
                    </span>
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-muted-foreground">
                Changeable later, but only for what you ingest after — chunks already
                stored keep the split they were made with.
              </p>
            </div>
          )}
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
  const ontologyOn = useCapability("ontology")
  return (
    <Card>
      <CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2">
        <Database className="h-4 w-4" />{name}</CardTitle>
        <CardDescription>Ingest documents, then search or ask with RAG.</CardDescription></CardHeader>
      <CardContent>
        {/* An empty collection has nothing to search — open on Ingest so the first step is obvious. */}
        <Tabs defaultValue={empty ? "ingest" : "search"}>
          <TabsList><TabsTrigger value="search"><Search className="h-3.5 w-3.5 mr-1" />Search / RAG</TabsTrigger>
            <TabsTrigger value="composition"><Layers className="h-3.5 w-3.5 mr-1" />Composition</TabsTrigger>
            <TabsTrigger value="ingest"><Upload className="h-3.5 w-3.5 mr-1" />Ingest</TabsTrigger>
            <TabsTrigger value="schedule"><Clock className="h-3.5 w-3.5 mr-1" />Schedule</TabsTrigger>
            {/* Only when the deployment has the capability. Without the flag every
                concepts call 404s, so an always-present tab would greet everyone with
                an error for a feature they have not turned on. The Concepts toggle in
                Search is gated the same way. */}
            {ontologyOn && <TabsTrigger value="concepts"><BookMarked className="h-3.5 w-3.5 mr-1" />Concepts</TabsTrigger>}
            <TabsTrigger value="compare"><ArrowDownWideNarrow className="h-3.5 w-3.5 mr-1" />Compare</TabsTrigger></TabsList>
          <TabsContent value="search"><SearchPanel name={name} /></TabsContent>
          <TabsContent value="composition"><CompositionPanel name={name} onChange={onChange} /></TabsContent>
          <TabsContent value="ingest"><IngestPanel name={name} onChange={onChange} /></TabsContent>
          <TabsContent value="schedule"><SchedulePanel name={name} /></TabsContent>
          {/* Deliberately in Knowledge rather than a page of its own: concepts change
              what Search returns, so the cause belongs next to the effect. */}
          {ontologyOn && <TabsContent value="concepts"><ConceptsPanel /></TabsContent>}
          <TabsContent value="compare"><ComparePanel name={name} /></TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

interface ScheduleState {
  enabled: boolean
  interval_minutes: number | null
  last_refreshed_at: string | null
  last_refresh_status: string | null
}

function SchedulePanel({ name }: { name: string }) {
  const isAdmin = getUser()?.role === "admin"
  const { toast } = useToast()
  const confirm = useConfirm()
  const [state, setState] = useState<ScheduleState | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => {
    setLoading(true); setErr(null)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}/schedule`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setState(await r.json())
    } catch (error) { setErr(error instanceof Error ? error.message : "Failed to load schedule") }
    setLoading(false)
  }, [name])
  useEffect(() => { const t = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(t) }, [load])
  const cancel = async () => {
    if (!(await confirm({ title: "Cancel schedule", message: "Stop the recurring re-embed for this collection?", confirmText: "Cancel schedule", destructive: true }))) return
    setBusy(true)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}/schedule`, { method: "DELETE" })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      toast("Schedule cancelled", "success"); load()
    } catch (error) { toast(error instanceof Error ? error.message : "Failed to cancel", "error") }
    setBusy(false)
  }
  if (loading) return <div className="pt-3 text-xs text-muted-foreground flex items-center gap-1.5"><Loader2 className="h-3.5 w-3.5 animate-spin" />Loading schedule…</div>
  if (err) return <div className="pt-3"><ErrorBox msg={err} /></div>
  if (!state?.enabled) return (
    <div className="pt-3 text-sm text-muted-foreground">
      No recurring re-embed is scheduled for this collection.
      {isAdmin ? " Set one up from the Ingest tab (choose a source, then “Schedule ingest”)." : " An administrator can set one up."}
    </div>
  )
  const okStatus = (state.last_refresh_status ?? "").toLowerCase().includes("ok") || (state.last_refresh_status ?? "").toLowerCase().includes("success")
  return (
    <div className="space-y-3 pt-3 text-sm">
      <div className="flex items-center gap-2">
        <Badge className="bg-[var(--dp-good)] text-white">Active</Badge>
        <span className="text-muted-foreground">re-embeds every <span className="dp-num">{state.interval_minutes}</span> min</span>
      </div>
      <div className="grid grid-cols-1 gap-1 text-xs text-muted-foreground">
        <div>Last run: {state.last_refreshed_at ? new Date(state.last_refreshed_at).toLocaleString() : "not yet"}</div>
        {state.last_refresh_status && (
          <div className="flex items-center gap-1">Status:
            <span className={okStatus ? "text-[var(--dp-good)]" : "text-[var(--dp-warn)]"}>{state.last_refresh_status}</span>
          </div>
        )}
      </div>
      {isAdmin && (
        <Button variant="outline" size="sm" onClick={cancel} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5 mr-1.5" />}Cancel schedule</Button>
      )}
    </div>
  )
}

// Render an answer: [n] citation chips that echo the numbered source list below,
// plus the Markdown the model routinely returns. It used to handle **bold** and
// nothing else, so a bulleted answer arrived as lines starting with a hyphen and a
// heading as a line starting with hashes.
function renderCitedAnswer(text: string) {
  return <Markdown text={text} citations />
}

// Concepts the backend expanded the query with (Phase 0 ontology slice).
interface ConceptUse { name: string; pii?: boolean; added?: string[] }

function SearchPanel({ name }: { name: string }) {
  const [q, setQ] = useState(""); const [mode, setMode] = useState<"search" | "rag">("rag")
  const [busy, setBusy] = useState(false); const [ans, setAns] = useState<string | null>(null)
  const [hits, setHits] = useState<Hit[]>([]); const [e, setE] = useState<string | null>(null)
  const [pii, setPii] = useState(0); const [hasAi, setHasAi] = useState(true)
  // Concept expansion — opt-in, only offered when the ontology capability is on.
  const ontologyEnabled = useCapability("ontology")
  const [expand, setExpand] = useState(false)
  const [concepts, setConcepts] = useState<ConceptUse[]>([])
  // Retrieval knobs. k was hardcoded here (5 for answers, 8 for search) and
  // reranking was an environment variable, so the role responsible for whether
  // search works could not change either without a redeploy.
  const [k, setK] = useState(5)
  const [rerank, setRerank] = useState<boolean | null>(null)
  const run = async () => {
    if (!q.trim()) return
    setBusy(true); setE(null); setAns(null); setHits([]); setPii(0); setHasAi(true); setConcepts([])
    const expandOn = ontologyEnabled && expand
    try {
      if (mode === "rag") {
        const r = await fetch("/api/ai/rag", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ collection: name, question: q, k, expand_concepts: expandOn, rerank }) })
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
        // has_ai=false ⇒ no model configured or the LLM call failed; the backend
        // returns search results only. Don't present that as a real answer.
        const d = await r.json(); setAns(d.answer); setHits(d.citations || []); setPii(d.pii_masked || 0); setHasAi(d.has_ai !== false); setConcepts(d.concepts || [])
      } else {
        const r = await fetch("/api/ai/search", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ collection: name, query: q, k, expand_concepts: expandOn, rerank }) })
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
        const d = await r.json(); setHits(d.results || []); setPii(d.pii_masked || 0); setConcepts(d.concepts || [])
      }
    } catch (error) { setE(error instanceof Error ? error.message : "Search failed") }
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
        {ontologyEnabled && (
          <button onClick={() => setExpand(x => !x)} aria-pressed={expand}
            title="Expand the query with curated concept synonyms/jargon before retrieval"
            className={`flex items-center gap-1 rounded-md border px-2.5 text-xs transition-colors ${expand ? "border-primary/50 bg-primary/10 text-primary" : "bg-background text-muted-foreground hover:text-foreground"}`}>
            <Sparkles className="h-3 w-3" />Concepts
          </button>
        )}
        <button onClick={() => setRerank(r => (r === false ? null : false))} aria-pressed={rerank !== false}
          title="Reranking reorders vector hits with a cross-encoder. Turn it off to see what it is contributing."
          className={`flex items-center gap-1 rounded-md border px-2.5 text-xs transition-colors ${rerank === false ? "bg-background text-muted-foreground hover:text-foreground" : "border-primary/50 bg-primary/10 text-primary"}`}>
          <ArrowDownWideNarrow className="h-3 w-3" />Rerank
        </button>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          k
          <input type="number" min={1} max={50} value={k}
            onChange={e => setK(Math.min(50, Math.max(1, Number(e.target.value) || 1)))}
            className="h-8 w-14 rounded-md border bg-background px-2 text-xs tabular-nums" />
        </label>
        <Button onClick={run} disabled={!q.trim() || busy}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquare className="h-4 w-4" />}</Button>
      </div>
      {/* PII signal stands alone only for Search (no answer); for a RAG answer it
          folds into the answer's trust bar so governance reads in one place. */}
      {pii > 0 && !(ans && hasAi) && (
        <div className="text-[11px] text-[var(--dp-good)] flex items-center gap-1"><ShieldCheck className="h-3 w-3" />{pii} PII item(s) masked before processing (guardrail)</div>
      )}
      {/* Search mode has no trust bar — show which concepts widened the query here. */}
      {concepts.length > 0 && !(ans && hasAi) && (
        <div className="flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
          expanded via
          {concepts.map(c => (
            <span key={c.name} title={`+${(c.added || []).join(", ") || "—"}`}
              className={`inline-flex items-center gap-0.5 rounded px-1 py-px text-[10px] font-medium ${c.pii ? "bg-[var(--dp-warn)]/10 text-[var(--dp-warn)]" : "bg-primary/10 text-primary"}`}>
              {c.name}{c.pii && <ShieldCheck className="h-2.5 w-2.5" />}
            </span>
          ))}
        </div>
      )}
      {e && <ErrorBox msg={e} />}

      {/* Signature: the grounded, governed answer — the product's core moment.
          Accent rail + hero type + inline citation chips, with a trust bar that
          makes "grounded · PII-masked · reranked" legible at a glance. */}
      {ans && hasAi && (() => {
        const reranked = hits.some(h => typeof h.rerank_score === "number")
        return (
          <Card className="dp-surface overflow-hidden border-primary/20">
            <div className="flex">
              <div className="w-1 shrink-0 bg-gradient-to-b from-primary to-[var(--chart-3)]" aria-hidden />
              <CardContent className="flex-1 py-3.5">
                <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-primary">
                  <Sparkles className="h-3.5 w-3.5" />Grounded answer
                </div>
                <div className="text-[15px] leading-7 text-foreground whitespace-pre-wrap">{renderCitedAnswer(ans)}</div>
                <div className="mt-3.5 flex flex-wrap items-center gap-x-3.5 gap-y-1.5 border-t pt-2.5 text-[11px] text-muted-foreground">
                  <span className="flex items-center gap-1"><FileText className="h-3 w-3" /><span className="dp-num font-medium text-foreground">{hits.length}</span>&nbsp;source{hits.length === 1 ? "" : "s"}</span>
                  {pii > 0 && <span className="flex items-center gap-1 text-[var(--dp-good)]"><ShieldCheck className="h-3 w-3" /><span className="dp-num font-medium">{pii}</span>&nbsp;PII masked</span>}
                  {reranked && <span className="flex items-center gap-1 text-primary"><Sparkles className="h-3 w-3" />reranked</span>}
                  {concepts.length > 0 && (
                    <span className="flex items-center gap-1" title={concepts.map(c => `${c.name}: +${(c.added || []).join(", ") || "—"}`).join("\n")}>
                      expanded via
                      {concepts.map(c => (
                        <span key={c.name} className={`inline-flex items-center gap-0.5 rounded px-1 py-px text-[10px] font-medium ${c.pii ? "bg-[var(--dp-warn)]/10 text-[var(--dp-warn)]" : "bg-primary/10 text-primary"}`}>
                          {c.name}{c.pii && <ShieldCheck className="h-2.5 w-2.5" />}
                        </span>
                      ))}
                    </span>
                  )}
                </div>
              </CardContent>
            </div>
          </Card>
        )
      })()}
      {ans && !hasAi && (
        <div className="rounded-md border border-[var(--dp-warn)]/40 bg-[var(--dp-warn)]/5 px-3 py-2 text-xs text-muted-foreground flex items-start gap-1.5">
          <AlertCircle className="h-3.5 w-3.5 text-[var(--dp-warn)] mt-0.5 shrink-0" />
          <span>No answer generated — the AI model isn&apos;t configured or the call failed. Showing retrieved results below only. Ask an administrator to configure a model in the AI Gateway to get cited answers.</span>
        </div>
      )}

      {hits.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] font-medium uppercase tracking-[0.1em] text-muted-foreground">{mode === "rag" ? "Sources" : "Results"}</p>
          {hits.map((h, i) => (
            <div key={i} className="rounded-lg border bg-card px-3 py-2.5 text-xs transition-colors hover:border-primary/30">
              <div className="mb-1.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                {/* number echoes the answer's inline [n] chips */}
                <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded bg-primary/10 dp-num text-[10px] font-semibold text-primary">{i + 1}</span>
                <span className="flex min-w-0 items-center gap-1 truncate"><FileText className="h-3 w-3 shrink-0" />{h.source || "n/a"}</span>
                <span className="ml-auto flex shrink-0 items-center gap-1">
                  {typeof h.rerank_score === "number" && (
                    <Badge variant="outline" className="dp-num text-[10px] border-primary/40 text-primary" title="Reranked relevance score">rerank {h.rerank_score.toFixed(3)}</Badge>
                  )}
                  <Badge variant="outline" className="dp-num text-[10px]" title="Cosine similarity">{h.score?.toFixed(3)}</Badge>
                </span>
              </div>
              <div className="line-clamp-3 leading-relaxed text-muted-foreground">{h.content}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function IngestPanel({ name, onChange }: { name: string; onChange: () => void }) {
  const catalogEnabled = useCapability("catalog")
  // Source ingest + schedule are admin-only on the backend (require_admin);
  // don't offer them to non-admins, who would only hit a 403.
  const isAdmin = getUser()?.role === "admin"
  const { toast } = useToast()
  const [tab, setTab] = useState<"text" | "source">("text")
  const [text, setText] = useState(""); const [src, setSrc] = useState("")
  const [stype, setStype] = useState<"iceberg" | "s3">("iceberg")
  const [schema, setSchema] = useState("default"); const [table, setTable] = useState(""); const [col, setCol] = useState("")
  const [bucket, setBucket] = useState(""); const [prefix, setPrefix] = useState("")
  const [busy, setBusy] = useState(false); const [e, setE] = useState<string | null>(null)
  // Keep the last ingest outcome on screen — a toast vanishes, but the run's
  // governance read (chunks embedded, PII masked) is worth leaving visible.
  const [result, setResult] = useState<{ docs?: number; chunks: number; pii: number } | null>(null)
  const [sched, setSched] = useState("@daily"); const [schedBusy, setSchedBusy] = useState(false)
  // Lakehouse picker: iceberg catalog tree (schemas→tables) + columns of the chosen table.
  const [tree, setTree] = useState<{ schema: string; tables: string[] }[]>([])
  const [cols, setCols] = useState<CatalogColumn[]>([])
  const sourceType = catalogEnabled ? stype : "s3"

  useEffect(() => {
    if (!catalogEnabled) return
    fetch("/api/catalog/schemas").then(r => r.json() as Promise<CatalogResponse>).then(d => {
      const catalogs = d.catalogs ?? []
      const activeCatalog = catalogs.find(catalog => catalog.name === "iceberg") ?? catalogs[0]
      const schemas = (activeCatalog?.schemas ?? []).map(item => ({ schema: item.name, tables: (item.tables ?? []).map(table => table.name) }))
      setTree(schemas)
    }).catch(() => {})
  }, [catalogEnabled])
  // When a table is picked, lazily fetch its columns to populate the text-column select.
  useEffect(() => {
    if (sourceType !== "iceberg" || !schema || !table) return
    const qs = new URLSearchParams({ catalog: "iceberg", schema, table })
    fetch(`/api/catalog/columns?${qs}`).then(r => r.json() as Promise<CatalogColumn[]>)
      .then((payload) => {
        const columns = Array.isArray(payload) ? payload : []
        setCols(columns)
        setCol(current => columns.length > 0 && !columns.some(column => column.name === current) ? columns[0].name : current)
      })
      .catch(() => setCols([]))
  }, [schema, sourceType, table])
  const sourceBody = () => sourceType === "iceberg"
    ? { type: "iceberg", schema, table, text_column: col }
    : { type: "s3", bucket, prefix }

  const ingestText = async () => {
    setBusy(true); setE(null)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}/ingest`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ documents: [{ source: src || "manual", text }] }) })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      const d = await r.json(); toast(`Ingested ${d.chunks} chunks (${d.pii_masked} PII masked)`, "success")
      setResult({ chunks: d.chunks, pii: d.pii_masked }); setText(""); onChange()
    } catch (error) { setE(error instanceof Error ? error.message : "Ingestion failed") }
    setBusy(false)
  }
  const ingestSource = async () => {
    setBusy(true); setE(null)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}/ingest-source`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sourceBody()) })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      const d = await r.json(); toast(`${d.documents} docs → ${d.chunks} chunks (${d.pii_masked} PII masked)`, "success")
      setResult({ docs: d.documents, chunks: d.chunks, pii: d.pii_masked }); onChange()
    } catch (error) { setE(error instanceof Error ? error.message : "Source ingestion failed") }
    setBusy(false)
  }
  const scheduleSource = async () => {
    setSchedBusy(true); setE(null)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(name)}/schedule`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schedule: sched, source: sourceBody() }) })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      const d = await r.json(); toast(`Schedule created — auto re-embeds every ${d.interval_minutes} min`, "success")
    } catch (error) { setE(error instanceof Error ? error.message : "Schedule creation failed") }
    setSchedBusy(false)
  }

  return (
    <div className="space-y-3 pt-3">
      <div className="flex rounded-md border overflow-hidden w-fit text-xs">
        {(["text", "source"] as const).map(t => (
          (t === "source" && !isAdmin) ? null : (
          <button key={t} onClick={() => setTab(t)} className={`px-3 py-1 ${tab === t ? "bg-primary text-primary-foreground" : "bg-background"}`}>
            {t === "text" ? "Paste text" : catalogEnabled ? "From catalog / S3" : "From S3"}</button>
          )
        ))}
      </div>
      {(tab === "text" || !isAdmin) ? (
        <>
          <Input value={src} onChange={e => setSrc(e.target.value)} placeholder="source label (optional)" className="text-sm" />
          <Textarea value={text} onChange={e => setText(e.target.value)} placeholder="Paste documents to embed…" className="min-h-[160px] text-sm" />
          <div className="flex items-center justify-between">
            <Button onClick={ingestText} disabled={!text.trim() || busy}>{busy && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}Ingest</Button>
            {text.trim() && <span className="text-[11px] tabular-nums text-muted-foreground">{text.length.toLocaleString()} chars · masked at ingest</span>}
          </div>
        </>
      ) : (
        <>
          {catalogEnabled && (
            <div className="flex rounded-md border overflow-hidden w-fit text-xs">
              {(["iceberg", "s3"] as const).map(t => (
                <button key={t} onClick={() => setStype(t)}
                  className={`px-3 py-1 ${stype === t ? "bg-primary text-primary-foreground" : "bg-background"}`}>{t}</button>
              ))}
            </div>
          )}
          {sourceType === "iceberg" ? (
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
          {(() => { const ready = sourceType === "iceberg" ? !!(table && col) : !!bucket; return (
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={ingestSource} disabled={busy || schedBusy || !ready}>
                {busy && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}Ingest from {sourceType}</Button>
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
          <p className="text-[11px] text-muted-foreground">
            Scheduled ingest re-embeds this source on the selected interval
            {sourceType === "iceberg" ? " and when a linked connector sync marks it stale." : "."}
          </p>
        </>
      )}
      {result && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-[var(--dp-good)]/25 bg-[var(--dp-good)]/[0.06] px-3 py-2 text-xs">
          <span className="flex items-center gap-1.5 font-medium text-[var(--dp-good)]">
            <CheckCircle2 className="h-3.5 w-3.5" />Ingested
          </span>
          {result.docs != null && <span className="text-muted-foreground"><b className="tabular-nums text-foreground">{result.docs.toLocaleString()}</b> docs</span>}
          <span className="text-muted-foreground"><b className="tabular-nums text-foreground">{result.chunks.toLocaleString()}</b> chunks embedded</span>
          <span className="text-muted-foreground"><b className="tabular-nums text-foreground">{result.pii.toLocaleString()}</b> PII masked</span>
          <span className="ml-auto text-[11px] text-muted-foreground">now searchable in this collection</span>
        </div>
      )}
      {e && <ErrorBox msg={e} />}
    </div>
  )
}
