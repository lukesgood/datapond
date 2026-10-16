"use client"

import { useState } from "react"
import { Activity } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Loading, Section, SectionError } from "./section"
import { useJson } from "./use-json"

type Call = {
  id: string | number; occurred_at: string; tool: string; outcome: string
  resource: string[]; hit_count: number | null; chunks_withheld: number | null; pii_masked: number | null
}

const WINDOWS = { "24h": 24 * 3_600_000, "7d": 7 * 24 * 3_600_000 } as const

/** The agent's last 50 tool calls. Refusals are highlighted: "why was it refused" is
 *  the usual reason to open this page. */
export function ActivitySection({ accountId }: { accountId: string }) {
  const sinceFor = (w: keyof typeof WINDOWS) => new Date(Date.now() - WINDOWS[w]).toISOString()
  // `since` is state set when a window is chosen, not computed in render: one that moved
  // on every render would be a new URL, and so a new request, every time. Choosing the
  // active window again re-reads it.
  const [win, setWin] = useState<keyof typeof WINDOWS>("24h")
  const [since, setSince] = useState(() => sinceFor("24h"))
  const calls = useJson<{ rows: Call[]; total: number; capped: boolean }>(
    `/api/audit/tool-calls?actor_id=${encodeURIComponent(accountId)}&since=${encodeURIComponent(since)}&limit=50`)

  return (
    <Section title="Activity" icon={<Activity className="h-4 w-4 text-primary" />}
             description="Calls with a disabled or revoked key are refused before the caller is known and do not appear here.">
      <div className="flex gap-1">
        {(Object.keys(WINDOWS) as (keyof typeof WINDOWS)[]).map(w => (
          <Button key={w} size="sm" variant={w === win ? "secondary" : "ghost"} className="h-7 text-xs"
                  onClick={() => { setWin(w); setSince(sinceFor(w)) }}>Last {w}</Button>
        ))}
      </div>
      {calls.loading ? <Loading what="calls" /> : calls.error && !calls.data ? (
        <SectionError message={`Activity could not be loaded: ${calls.error}`} onRetry={calls.reload} />
      ) : !calls.data || calls.data.rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No tool calls in this window.</p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border text-xs">
            <div className="grid min-w-[40rem] grid-cols-[9rem_1fr_5rem_1fr_3rem_4rem_3.5rem] gap-3 border-b px-3 py-1.5 text-2xs text-muted-foreground">
              <span>Time</span><span>Tool</span><span>Outcome</span><span>Resource</span>
              <span className="text-right">Hits</span><span className="text-right">Withheld</span><span className="text-right">PII</span>
            </div>
            <div className="min-w-[40rem] divide-y">
              {calls.data.rows.map(r => {
                const bad = r.outcome === "refused" || r.outcome === "error"
                return (
                  <div key={r.id} className={`grid grid-cols-[9rem_1fr_5rem_1fr_3rem_4rem_3.5rem] items-center gap-3 px-3 py-1.5 ${bad ? "bg-destructive/5" : ""}`}>
                    <span className="text-muted-foreground">{new Date(r.occurred_at).toLocaleString()}</span>
                    <span className="truncate font-mono">{r.tool}</span>
                    <span className={bad ? "font-medium text-destructive" : ""}>{r.outcome}</span>
                    <span className="truncate" title={r.resource.join(", ")}>{r.resource.join(", ") || "—"}</span>
                    <span className="text-right tabular-nums">{r.hit_count ?? "—"}</span>
                    <span className="text-right tabular-nums">{r.chunks_withheld ?? "—"}</span>
                    <span className="text-right tabular-nums">{r.pii_masked ?? "—"}</span>
                  </div>
                )
              })}
            </div>
          </div>
          {calls.data.capped && (
            <p className="text-2xs text-muted-foreground">
              Showing the latest {calls.data.rows.length} of {calls.data.total}.
            </p>
          )}
        </>
      )}
    </Section>
  )
}
