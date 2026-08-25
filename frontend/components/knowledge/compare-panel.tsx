"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AlertCircle, ArrowRight, Loader2 } from "lucide-react"

type Hit = { content: string; source?: string; score?: number; rerank_score?: number }
type Settings = { k: number; rerank: boolean | null; expand: boolean }
type Side = { hits: Hit[]; ms: number } | null

/** Two retrieval settings, same query, side by side.
 *
 *  Deliberately a comparison and not a measurement. Saying which setting is *better*
 *  needs labelled queries — someone deciding, for a set of questions, which documents
 *  should have come back — and this product has no such data. What it can do without
 *  inventing anything is show what actually changed: which chunks only one side found,
 *  and how far the shared ones moved.
 *
 *  That is the question behind "should I turn reranking on": not a score, but whether
 *  it pulls in different documents and whether those look right to the person who
 *  knows the corpus.
 */
export function ComparePanel({ name }: { name: string }) {
  const [q, setQ] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [a, setA] = useState<Side>(null)
  const [b, setB] = useState<Side>(null)
  const [sa, setSa] = useState<Settings>({ k: 8, rerank: null, expand: false })
  const [sb, setSb] = useState<Settings>({ k: 8, rerank: false, expand: false })

  const one = async (s: Settings): Promise<Side> => {
    const t0 = performance.now()
    const r = await fetch("/api/ai/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ collection: name, query: q, k: s.k,
                             rerank: s.rerank, expand_concepts: s.expand }),
    })
    if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
    return { hits: (await r.json()).results || [], ms: Math.round(performance.now() - t0) }
  }

  const run = async () => {
    if (!q.trim() || busy) return
    setBusy(true); setErr(null); setA(null); setB(null)
    try {
      // Sequential, not parallel: two concurrent embeds against the same gateway make
      // the timings meaningless, and the timing is half of what is being compared.
      setA(await one(sa))
      setB(await one(sb))
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Comparison failed")
    } finally {
      setBusy(false)
    }
  }

  const key = (h: Hit) => `${h.source ?? ""}::${h.content.slice(0, 80)}`
  const inA = new Set((a?.hits ?? []).map(key))
  const inB = new Set((b?.hits ?? []).map(key))
  const onlyA = (a?.hits ?? []).filter(h => !inB.has(key(h))).length
  const onlyB = (b?.hits ?? []).filter(h => !inA.has(key(h))).length
  const shared = (a?.hits ?? []).filter(h => inB.has(key(h))).length

  return (
    <div className="space-y-3 pt-3">
      <p className="text-xs text-muted-foreground">
        Runs the same query under two settings and shows what changed — which chunks
        only one side found, and where the shared ones ranked. It does not say which
        side is better; that needs queries someone has labelled, which this deployment
        does not have.
      </p>

      <div className="flex gap-2">
        <Input value={q} onChange={e => setQ(e.target.value)}
               onKeyDown={e => { if (e.key === "Enter") void run() }}
               placeholder="A question your users would ask…" className="text-xs" />
        <Button onClick={() => void run()} disabled={!q.trim() || busy} className="gap-1.5">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
          Compare
        </Button>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <Knobs label="A" s={sa} onChange={setSa} />
        <Knobs label="B" s={sb} onChange={setSb} />
      </div>

      {err && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />{err}
        </div>
      )}

      {a && b && (
        <>
          <div className="grid grid-cols-3 gap-3">
            {[["Only in A", onlyA], ["In both", shared], ["Only in B", onlyB]].map(([k, v]) => (
              <div key={k as string} className="rounded-lg border p-3">
                <div className="text-[11px] text-muted-foreground">{k}</div>
                <div className="text-lg font-semibold tabular-nums">{v}</div>
              </div>
            ))}
          </div>
          {onlyA === 0 && onlyB === 0 && (
            <p className="text-xs text-muted-foreground">
              Both settings returned the same chunks. Whatever you changed made no
              difference to this query.
            </p>
          )}
          <div className="grid gap-3 md:grid-cols-2">
            <Results title={`A · ${a.ms}ms`} hits={a.hits} other={inB} keyOf={key} />
            <Results title={`B · ${b.ms}ms`} hits={b.hits} other={inA} keyOf={key} />
          </div>
        </>
      )}
    </div>
  )
}

function Knobs({ label, s, onChange }: {
  label: string; s: Settings; onChange: (s: Settings) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border p-2.5 text-xs">
      <span className="font-semibold">{label}</span>
      <label className="flex items-center gap-1 text-muted-foreground">
        k
        <input type="number" min={1} max={50} value={s.k}
               onChange={e => onChange({ ...s, k: Math.min(50, Math.max(1, Number(e.target.value) || 1)) })}
               className="h-7 w-14 rounded border bg-background px-1.5 tabular-nums" />
      </label>
      <Toggle on={s.rerank !== false} label="Rerank"
              onClick={() => onChange({ ...s, rerank: s.rerank === false ? null : false })} />
      <Toggle on={s.expand} label="Concepts"
              onClick={() => onChange({ ...s, expand: !s.expand })} />
    </div>
  )
}

function Toggle({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} aria-pressed={on}
            className={`rounded-md border px-2 py-1 transition-colors ${
              on ? "border-primary/50 bg-primary/10 text-primary"
                 : "bg-background text-muted-foreground hover:text-foreground"}`}>
      {label}
    </button>
  )
}

function Results({ title, hits, other, keyOf }: {
  title: string; hits: Hit[]; other: Set<string>; keyOf: (h: Hit) => string
}) {
  return (
    <div className="rounded-lg border">
      <div className="border-b px-3 py-2 text-xs font-medium">{title}</div>
      <div className="divide-y">
        {hits.length === 0 && <p className="px-3 py-4 text-xs text-muted-foreground">No results.</p>}
        {hits.map((h, i) => {
          const only = !other.has(keyOf(h))
          return (
            <div key={i} className={`px-3 py-2 text-[11px] ${only ? "bg-primary/5" : ""}`}>
              <div className="mb-0.5 flex items-center gap-2">
                <span className="tabular-nums text-muted-foreground">#{i + 1}</span>
                {only && <span className="rounded bg-primary/15 px-1 text-[10px] text-primary">only here</span>}
                {h.source && <span className="truncate font-mono text-muted-foreground">{h.source}</span>}
              </div>
              <p className="line-clamp-2 text-muted-foreground">{h.content}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}
