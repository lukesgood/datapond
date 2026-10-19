"use client"

import { useState } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Loading, SectionError } from "@/components/agents/section"
import { useJson } from "@/components/agents/use-json"
import {
  callerOptions, isProblem, toolCallsUrl, type ActorSummary, type ToolCall,
} from "@/lib/tool-calls"

const WINDOWS = { "24h": 24 * 3_600_000, "7d": 7 * 24 * 3_600_000, "30d": 30 * 24 * 3_600_000 } as const
type Win = keyof typeof WINDOWS

/** Every caller's tool calls, newest first: what each one read, what it was refused,
 *  how many nearer chunks a rule withheld from it, and what it cited. The per-agent
 *  view of the same rows is the agent's own page. */
export function ToolCallsTab() {
  const sinceFor = (w: Win) => new Date(Date.now() - WINDOWS[w]).toISOString()
  // State, not computed in render: a `since` that moved every render would be a new
  // URL, and so a new request, every time (see components/agents/activity-section).
  const [win, setWin] = useState<Win>("24h")
  const [since, setSince] = useState(() => sinceFor("24h"))
  const [actor, setActor] = useState("")
  const calls = useJson<{ rows: ToolCall[]; total: number; capped: boolean }>(toolCallsUrl(since, actor))
  const summary = useJson<{ by_actor: ActorSummary[] }>(
    `/api/audit/tool-calls/summary?since=${encodeURIComponent(since)}`)
  const callers = callerOptions(summary.data?.by_actor ?? [])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {(Object.keys(WINDOWS) as Win[]).map(w => (
            <Button key={w} size="sm" variant={w === win ? "secondary" : "ghost"} className="h-7 text-xs"
                    onClick={() => { setWin(w); setSince(sinceFor(w)) }}>Last {w}</Button>
          ))}
        </div>
        <select value={actor} onChange={e => setActor(e.target.value)} aria-label="Caller"
                className="h-7 min-w-48 rounded-md border bg-background px-2 text-xs">
          <option value="">All callers</option>
          {callers.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
          {/* A chosen caller stays selectable after the window changes. */}
          {actor && !callers.some(c => c.id === actor) && <option value={actor}>{actor.slice(0, 8)}…</option>}
        </select>
        <p className="text-2xs text-muted-foreground">
          Search, cited answers, metrics and SQL from agents and people, refused calls included. A call
          with a disabled or revoked key is refused before its caller is known.
        </p>
      </div>

      {calls.loading ? <Loading what="tool calls" /> : calls.error && !calls.data ? (
        <SectionError message={`Tool calls could not be loaded: ${calls.error}`} onRetry={calls.reload} />
      ) : !calls.data || calls.data.rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No tool calls in this window.</p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border text-xs">
            <div className="grid min-w-[56rem] grid-cols-[9rem_10rem_7rem_4.5rem_1fr_3rem_4rem_3rem_1fr] gap-3 border-b px-3 py-1.5 text-2xs text-muted-foreground">
              <span>Time</span><span>Caller</span><span>Tool</span><span>Outcome</span><span>Resource</span>
              <span className="text-right">Hits</span><span className="text-right">Withheld</span>
              <span className="text-right">PII</span><span>Cited</span>
            </div>
            <div className="min-w-[56rem] divide-y">
              {calls.data.rows.map(r => {
                const bad = isProblem(r.outcome)
                return (
                  <div key={r.id} className={`grid grid-cols-[9rem_10rem_7rem_4.5rem_1fr_3rem_4rem_3rem_1fr] items-center gap-3 px-3 py-1.5 ${bad ? "bg-destructive/5" : ""}`}>
                    <span className="text-muted-foreground">{new Date(r.occurred_at).toLocaleString()}</span>
                    <span className="truncate" title={r.actor_id ?? undefined}>
                      {r.actor_kind === "service" && r.actor_id
                        ? <Link href={`/agents/${r.actor_id}`} className="text-primary hover:underline">{r.actor_username}</Link>
                        : r.actor_username}
                    </span>
                    <span className="truncate font-mono">{r.tool}</span>
                    <span className={bad ? "font-medium text-destructive" : ""}>{r.outcome}</span>
                    <span className="truncate" title={r.resource.join(", ")}>{r.resource.join(", ") || "—"}</span>
                    <span className="text-right tabular-nums">{r.hit_count ?? "—"}</span>
                    <span className="text-right tabular-nums">{r.chunks_withheld ?? "—"}</span>
                    <span className="text-right tabular-nums">{r.pii_masked ?? "—"}</span>
                    <span className="truncate" title={r.citation_sources.join(", ")}>{r.citation_sources.join(", ") || "—"}</span>
                  </div>
                )
              })}
            </div>
          </div>
          {calls.data.capped && (
            <p className="text-2xs text-muted-foreground">
              Showing the latest {calls.data.rows.length} of {calls.data.total}. The full window is in
              Reports → Agent tool calls.
            </p>
          )}
        </>
      )}
    </div>
  )
}
