"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorBox } from "@/components/ui/error-box"
import { AlertTriangle, Info, RefreshCw, ShieldAlert } from "lucide-react"
import { InfraTabs } from "@/components/infra/infra-tabs"
import { causeNote, severityRank, summarizeOccurrences } from "@/lib/system-events"

interface EventRow {
  id: string
  kind: string
  severity: string
  source: string
  object: string
  message: string
  details: Record<string, unknown>
  first_seen: string
  last_seen: string
  occurrences: number
}

interface EventsResponse {
  events: EventRow[]
  counts: Record<string, number>
  window_hours: number
}

const SEVERITY = {
  critical: { label: "Critical", Icon: ShieldAlert,   cls: "bg-destructive/10 text-destructive border-destructive/30" },
  warning:  { label: "Warning",  Icon: AlertTriangle, cls: "bg-[var(--dp-warn)]/10 text-[var(--dp-warn)] border-[var(--dp-warn)]/30" },
  info:     { label: "Info",     Icon: Info,          cls: "bg-muted text-muted-foreground border-transparent" },
} as const

// Kubernetes reason names are not what an operator calls the thing.
const KIND_LABEL: Record<string, string> = {
  pod_restart: "Restarted",
  oom_kill: "Out of memory",
  probe_failure: "Health check failed",
  image_pull_failure: "Image pull failed",
  schedule_failure: "Could not schedule",
  mount_failure: "Volume mount failed",
  crash_backoff: "Crash loop",
  eviction: "Evicted",
  node_not_ready: "Node not ready",
  node_reboot: "Node restarted",
  container_failure: "Container failed",
  unknown: "Warning",
}

const WINDOWS = [
  { label: "24h", hours: 24 },
  { label: "7d", hours: 168 },
  { label: "30d", hours: 720 },
] as const

function when(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString()
}

export function EventsPanel() {
  const [data, setData] = useState<EventsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hours, setHours] = useState<number>(168)
  const [severity, setSeverity] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ hours: String(hours) })
      if (severity) params.set("severity", severity)
      const res = await fetch(`/api/system/events?${params}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (requestError) {
      setData(null)
      setError(requestError instanceof Error
        ? `Failed to load system events (${requestError.message})`
        : "Failed to load system events")
    } finally { setLoading(false) }
  }, [hours, severity])

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0)
    const interval = window.setInterval(() => void load(), 30000)
    return () => { window.clearTimeout(initial); window.clearInterval(interval) }
  }, [load])

  // Severity first, then most recent. The API orders by recency alone, which buries a
  // critical from this morning under a warning from a minute ago.
  const events = useMemo(() => [...(data?.events ?? [])].sort((a, b) =>
    severityRank(a.severity) - severityRank(b.severity) ||
    Date.parse(b.last_seen) - Date.parse(a.last_seen)), [data])

  const counts = data?.counts ?? {}

  return (
    <div className="flex flex-col" style={{ minHeight: "calc(100vh - 56px)" }}>
      <div className="flex items-center gap-1.5 border-b px-3 h-11 shrink-0 bg-background">
        <InfraTabs active="events" />
        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5">
            {WINDOWS.map((w) => (
              <button
                key={w.hours}
                type="button"
                onClick={() => setHours(w.hours)}
                aria-current={hours === w.hours ? "true" : undefined}
                className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                  hours === w.hours ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                }`}
              >{w.label}</button>
            ))}
          </div>
          <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5" onClick={load} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span className="hidden md:inline">{loading ? "Refreshing" : "Refresh"}</span>
          </Button>
        </div>
      </div>

      <div className="p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {(["critical", "warning", "info"] as const).map((s) => {
            const meta = SEVERITY[s]
            const on = severity === s
            return (
              <button
                key={s}
                type="button"
                onClick={() => setSeverity(on ? null : s)}
                aria-pressed={on}
                className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${meta.cls} ${on ? "ring-2 ring-ring" : "opacity-80 hover:opacity-100"}`}
              >
                <meta.Icon className="h-3.5 w-3.5" />
                {meta.label}
                <span className="tabular-nums">{counts[s] ?? 0}</span>
              </button>
            )
          })}
          <p className="text-xs text-muted-foreground ml-auto">
            Infrastructure state changes. Pod logs are under Services; queries under Analytics.
          </p>
        </div>

        {error && <ErrorBox msg={error} />}

        {loading && !data && (
          <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div>
        )}

        {data && events.length === 0 && (
          <div className="rounded-md border border-dashed p-8 text-center">
            <p className="text-sm font-medium">No events in this window</p>
            <p className="text-xs text-muted-foreground mt-1">
              Nothing is collected while the backend is down, so an empty window is not
              proof that nothing happened.
            </p>
          </div>
        )}

        <div className="space-y-2">
          {events.map((e) => {
            const meta = SEVERITY[e.severity as keyof typeof SEVERITY] ?? SEVERITY.info
            const note = causeNote(e)
            return (
              <div key={e.id} className="rounded-md border p-3 flex gap-3">
                <meta.Icon className={`h-4 w-4 mt-0.5 shrink-0 ${e.severity === "critical" ? "text-destructive" : e.severity === "warning" ? "text-[var(--dp-warn)]" : "text-muted-foreground"}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className="text-sm font-medium">{KIND_LABEL[e.kind] ?? e.kind}</span>
                    <code className="text-xs text-muted-foreground truncate">{e.object}</code>
                    <Badge variant="outline" className="text-[10px] h-4 px-1.5">{e.source}</Badge>
                    <span className="text-xs text-muted-foreground ml-auto tabular-nums">{when(e.last_seen)}</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1 break-words">{e.message}</p>
                  {note && <p className="text-xs mt-1 text-[var(--dp-warn)]">{note}</p>}
                  <p className="text-[11px] text-muted-foreground mt-1">
                    {summarizeOccurrences(e.occurrences, e.first_seen, e.last_seen)}
                    {e.occurrences > 1 && <> · first {when(e.first_seen)}</>}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
