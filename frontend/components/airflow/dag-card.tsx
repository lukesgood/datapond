"use client"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Play, Pause, Calendar, CheckCircle2, XCircle,
  Clock, Workflow, TrendingUp, Link as LinkIcon, Trash2, Pencil,
} from "lucide-react"
import Link from "next/link"

interface DagCardProps {
  dag_id: string
  is_paused: boolean
  description?: string
  schedule_interval?: string
  last_run_state?: "success" | "failed" | "running" | "none"
  last_run_time?: string
  success_rate?: number
  savedStatus?: string
  onTrigger: (dag_id: string) => void
  onTogglePause: (dag_id: string, is_paused: boolean) => void
  onDelete?: (dag_id: string) => void
  onEdit?: (dag_id: string) => void
}

function StateIndicator({ state }: { state?: string }) {
  if (state === "success")
    return <span className="flex items-center gap-1 text-xs text-emerald-600"><CheckCircle2 className="h-3.5 w-3.5" />Success</span>
  if (state === "failed")
    return <span className="flex items-center gap-1 text-xs text-red-500"><XCircle className="h-3.5 w-3.5" />Failed</span>
  if (state === "running")
    return <span className="flex items-center gap-1 text-xs text-blue-500"><Clock className="h-3.5 w-3.5 animate-pulse" />Running</span>
  return <span className="text-xs text-muted-foreground">No runs yet</span>
}

export function DagCard({
  dag_id, is_paused, description, schedule_interval,
  last_run_state, last_run_time, success_rate,
  savedStatus, onTrigger, onTogglePause, onDelete, onEdit,
}: DagCardProps) {
  return (
    <div className={`
      rounded-lg border bg-card p-4 flex flex-col gap-3
      hover:shadow-sm transition-shadow
      ${is_paused ? "opacity-70" : ""}
    `}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Workflow className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="text-sm font-semibold truncate" title={dag_id}>{dag_id}</span>
        </div>
        <div className="flex items-center gap-1">
          {savedStatus && (
            <Badge
              variant="outline"
              className={`text-[10px] h-5 px-1.5 ${
                savedStatus === "deployed" ? "border-emerald-300 text-emerald-700 bg-emerald-50" :
                savedStatus === "draft" ? "border-amber-300 text-amber-700 bg-amber-50" : ""
              }`}
            >
              {savedStatus}
            </Badge>
          )}
          <Badge
            variant={is_paused ? "outline" : "default"}
            className={`shrink-0 text-[10px] h-5 px-1.5 ${!is_paused ? "bg-emerald-600 hover:bg-emerald-600" : ""}`}
          >
            {is_paused ? "Paused" : "Active"}
          </Badge>
        </div>
      </div>

      {/* Description */}
      {description ? (
        <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">{description}</p>
      ) : (
        <p className="text-xs text-muted-foreground/40 italic">No description</p>
      )}

      {/* Meta row */}
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        {schedule_interval && (
          <span className="flex items-center gap-1">
            <Calendar className="h-3.5 w-3.5" />
            {schedule_interval}
          </span>
        )}
        {success_rate !== undefined && (
          <span className="flex items-center gap-1">
            <TrendingUp className="h-3.5 w-3.5" />
            {success_rate.toFixed(0)}%
          </span>
        )}
        <span className="ml-auto">
          <StateIndicator state={last_run_state} />
        </span>
      </div>

      {/* Success rate bar */}
      {success_rate !== undefined && (
        <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              success_rate >= 90 ? "bg-emerald-500" :
              success_rate >= 70 ? "bg-yellow-500" : "bg-red-500"
            }`}
            style={{ width: `${success_rate}%` }}
          />
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-2 pt-1">
        <Button variant="outline" size="sm" className="flex-1 h-7 text-xs gap-1.5"
          render={<Link href={`/pipelines/${dag_id}`} />}>
          <LinkIcon className="h-3 w-3" />
          Details
        </Button>
        <Button
          variant="outline" size="sm"
          className="h-7 w-7 p-0"
          onClick={() => onTrigger(dag_id)}
          disabled={is_paused}
          aria-label="Trigger run" title="Trigger run"
        >
          <Play className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="outline" size="sm"
          className="h-7 w-7 p-0"
          onClick={() => onTogglePause(dag_id, !is_paused)}
          title={is_paused ? "Resume" : "Pause"}
        >
          {is_paused
            ? <Play className="h-3.5 w-3.5 text-emerald-600" />
            : <Pause className="h-3.5 w-3.5" />
          }
        </Button>
        {onEdit && (
          <Button
            variant="outline" size="sm"
            className="h-7 w-7 p-0"
            onClick={() => onEdit(dag_id)}
            aria-label="Edit pipeline" title="Edit pipeline"
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>
        )}
        {onDelete && (
          <Button
            variant="outline" size="sm"
            className="h-7 w-7 p-0 hover:bg-red-50 hover:border-red-200 hover:text-red-600"
            onClick={() => onDelete(dag_id)}
            aria-label="Delete pipeline" title="Delete pipeline"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
    </div>
  )
}
