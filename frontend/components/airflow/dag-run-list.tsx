"use client"

import { Badge } from "@/components/ui/badge"
import { CheckCircle2, XCircle, Clock, PlayCircle, Timer, Workflow } from "lucide-react"
import Link from "next/link"
import { formatDistance } from "date-fns"

interface DagRun {
  dag_run_id: string
  dag_id: string
  execution_date: string
  start_date?: string
  end_date?: string
  state: string
  run_type: string
}

interface DagRunListProps {
  runs: DagRun[]
  showDagId?: boolean
}

function StateBadge({ state }: { state: string }) {
  if (state === "success")
    return <span className="flex items-center gap-1 text-[11px] font-medium text-green-600"><CheckCircle2 className="h-3 w-3" />Success</span>
  if (state === "failed")
    return <span className="flex items-center gap-1 text-[11px] font-medium text-red-500"><XCircle className="h-3 w-3" />Failed</span>
  if (state === "running")
    return <span className="flex items-center gap-1 text-[11px] font-medium text-primary"><Clock className="h-3 w-3 animate-spin" />Running</span>
  if (state === "queued")
    return <span className="flex items-center gap-1 text-[11px] font-medium text-yellow-600"><PlayCircle className="h-3 w-3" />Queued</span>
  return <Badge variant="secondary" className="text-[10px] h-4">{state}</Badge>
}

function duration(start?: string, end?: string): string | null {
  if (!start) return null
  const ms = (end ? new Date(end) : new Date()).getTime() - new Date(start).getTime()
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  const h = Math.floor(m / 60)
  if (h > 0) return `${h}h ${m % 60}m`
  if (m > 0) return `${m}m ${s % 60}s`
  return `${s}s`
}

function timeAgo(d: string) {
  try { return formatDistance(new Date(d), new Date(), { addSuffix: true }) }
  catch { return d }
}

export function DagRunList({ runs, showDagId = false }: DagRunListProps) {
  return (
    <div className="flex flex-col min-h-0">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3 shrink-0">
        <Timer className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Recent Runs
        </span>
        <Badge variant="secondary" className="text-[10px] h-4 px-1.5 ml-auto">
          {runs.length}
        </Badge>
      </div>

      {/* Empty state */}
      {runs.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-center">
          <Workflow className="h-7 w-7 text-muted-foreground/20 mb-2" />
          <p className="text-xs text-muted-foreground">No runs yet</p>
          <p className="text-[11px] text-muted-foreground/50 mt-0.5">
            Trigger a pipeline to see results
          </p>
        </div>
      ) : (
        <div className="space-y-1 overflow-y-auto">
          {runs.map((run) => (
            <Link
              key={run.dag_run_id}
              href={`/jobs/${run.dag_run_id}?dag_id=${run.dag_id}`}
            >
              <div className="rounded-md px-2.5 py-2 hover:bg-muted/60
                              transition-colors cursor-pointer border border-transparent
                              hover:border-border">
                {/* Top: dag_id (if shown) + state */}
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="text-xs font-medium truncate min-w-0 flex-1">
                    {showDagId ? run.dag_id : run.dag_run_id.slice(0, 18)}
                  </span>
                  <StateBadge state={run.state} />
                </div>

                {/* Bottom: started + duration */}
                <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                  <span>{run.start_date ? timeAgo(run.start_date) : "—"}</span>
                  {run.start_date && (
                    <span className="flex items-center gap-1 shrink-0">
                      <Timer className="h-2.5 w-2.5" />
                      {duration(run.start_date, run.end_date) ?? "…"}
                    </span>
                  )}
                </div>

                {/* Running progress */}
                {run.state === "running" && (
                  <div className="mt-1.5 h-0.5 w-full rounded-full bg-muted overflow-hidden">
                    <div className="h-full w-1/2 bg-primary animate-pulse rounded-full" />
                  </div>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
