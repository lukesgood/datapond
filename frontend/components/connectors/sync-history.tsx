"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { CheckCircle2, XCircle, Loader2, Clock } from "lucide-react"

interface SyncRun {
  id: string
  status: "running" | "success" | "failed"
  started_at: string
  completed_at?: string
  rows_synced?: number
  error_message?: string
  duration?: number
}

interface SyncHistoryProps {
  runs: SyncRun[]
}

export function SyncHistory({ runs }: SyncHistoryProps) {
  const formatDateTime = (dateString: string) => {
    const date = new Date(dateString)
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    }).format(date)
  }

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}m ${remainingSeconds}s`
  }

  const getStatusConfig = (status: string) => {
    switch (status) {
      case "success":
        return {
          icon: CheckCircle2,
          color: "text-green-500",
          bgColor: "bg-green-500/10",
          label: "Success"
        }
      case "failed":
        return {
          icon: XCircle,
          color: "text-red-500",
          bgColor: "bg-red-500/10",
          label: "Failed"
        }
      case "running":
        return {
          icon: Loader2,
          color: "text-blue-500",
          bgColor: "bg-blue-500/10",
          label: "Running"
        }
      default:
        return {
          icon: Clock,
          color: "text-muted-foreground",
          bgColor: "bg-muted",
          label: status
        }
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sync History</CardTitle>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            No sync history available
          </div>
        ) : (
          <div className="space-y-4">
            {runs.map((run, index) => {
              const config = getStatusConfig(run.status)
              const Icon = config.icon

              return (
                <div
                  key={run.id}
                  className="flex items-start gap-4 pb-4 border-b last:border-0 last:pb-0"
                >
                  {/* Timeline dot */}
                  <div className="relative flex flex-col items-center">
                    <div
                      className={`flex h-10 w-10 items-center justify-center rounded-full ${config.bgColor}`}
                    >
                      <Icon
                        className={`h-5 w-5 ${config.color} ${
                          run.status === "running" ? "animate-spin" : ""
                        }`}
                      />
                    </div>
                    {index < runs.length - 1 && (
                      <div className="w-0.5 h-full bg-border absolute top-10" />
                    )}
                  </div>

                  {/* Content */}
                  <div className="flex-1 space-y-1 pt-1">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Badge
                          variant={
                            run.status === "success"
                              ? "default"
                              : run.status === "failed"
                              ? "destructive"
                              : "secondary"
                          }
                        >
                          {config.label}
                        </Badge>
                        <span className="text-sm text-muted-foreground">
                          {formatDateTime(run.started_at)}
                        </span>
                      </div>
                      {run.duration && (
                        <span className="text-xs text-muted-foreground flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {formatDuration(run.duration)}
                        </span>
                      )}
                    </div>

                    {run.rows_synced !== undefined && (
                      <p className="text-sm">
                        <span className="font-medium">
                          {run.rows_synced.toLocaleString()}
                        </span>{" "}
                        rows synced
                      </p>
                    )}

                    {run.error_message && (
                      <p className="text-sm text-destructive">{run.error_message}</p>
                    )}

                    {run.completed_at && (
                      <p className="text-xs text-muted-foreground">
                        Completed at {formatDateTime(run.completed_at)}
                      </p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
