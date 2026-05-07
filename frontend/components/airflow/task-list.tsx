"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  CheckCircle2,
  XCircle,
  Clock,
  FileText,
  Timer,
  Play,
  Activity,
} from "lucide-react"

interface TaskInstance {
  task_id: string
  dag_id: string
  execution_date: string
  start_date?: string
  end_date?: string
  duration?: number
  state?: string
  try_number?: number
  max_tries?: number
  operator?: string
}

interface TaskListProps {
  tasks: TaskInstance[]
  onViewLogs: (taskId: string) => void
}

export function TaskList({ tasks, onViewLogs }: TaskListProps) {
  const getStateIcon = (state?: string) => {
    switch (state) {
      case "success":
        return <CheckCircle2 className="h-4 w-4 text-green-500" />
      case "failed":
        return <XCircle className="h-4 w-4 text-red-500" />
      case "running":
        return <Clock className="h-4 w-4 text-primary animate-spin" />
      case "queued":
        return <Play className="h-4 w-4 text-yellow-500" />
      case "upstream_failed":
        return <XCircle className="h-4 w-4 text-orange-500" />
      case "skipped":
        return <Activity className="h-4 w-4 text-gray-500" />
      default:
        return <Clock className="h-4 w-4 text-gray-500" />
    }
  }

  const getStateBadge = (state?: string) => {
    switch (state) {
      case "success":
        return <Badge className="bg-green-600">Success</Badge>
      case "failed":
        return <Badge variant="destructive">Failed</Badge>
      case "running":
        return <Badge className="bg-primary">Running</Badge>
      case "queued":
        return <Badge className="bg-yellow-600">Queued</Badge>
      case "upstream_failed":
        return <Badge className="bg-orange-600">Upstream Failed</Badge>
      case "skipped":
        return <Badge variant="secondary">Skipped</Badge>
      default:
        return <Badge variant="outline">{state || "Unknown"}</Badge>
    }
  }

  const formatDuration = (duration?: number) => {
    if (!duration) return "N/A"
    const seconds = Math.floor(duration)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)

    if (hours > 0) {
      return `${hours}h ${minutes % 60}m`
    } else if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`
    } else {
      return `${seconds}s`
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Task Instances</CardTitle>
      </CardHeader>
      <CardContent>
        {tasks.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            No tasks found
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map((task) => (
              <Card key={task.task_id} className="hover:shadow-sm transition-shadow">
                <CardContent className="p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex-1 space-y-2">
                      <div className="flex items-center gap-3">
                        {getStateIcon(task.state)}
                        <div className="flex-1">
                          <div className="font-medium">{task.task_id}</div>
                          {task.operator && (
                            <div className="text-xs text-muted-foreground">
                              {task.operator}
                            </div>
                          )}
                        </div>
                        {getStateBadge(task.state)}
                      </div>

                      <div className="grid grid-cols-3 gap-4 text-sm">
                        <div>
                          <span className="text-muted-foreground flex items-center gap-1">
                            <Timer className="h-3 w-3" />
                            Duration:
                          </span>
                          <span className="ml-1 font-medium">
                            {formatDuration(task.duration)}
                          </span>
                        </div>
                        {task.try_number && (
                          <div>
                            <span className="text-muted-foreground">Try:</span>
                            <span className="ml-1 font-medium">
                              {task.try_number}/{task.max_tries || "?"}
                            </span>
                          </div>
                        )}
                        {task.start_date && (
                          <div>
                            <span className="text-muted-foreground">Started:</span>
                            <span className="ml-1 font-medium text-xs">
                              {new Date(task.start_date).toLocaleTimeString()}
                            </span>
                          </div>
                        )}
                      </div>

                      {task.state === "running" && (
                        <div className="mt-2">
                          <div className="h-1 bg-secondary rounded-full overflow-hidden">
                            <div className="h-full bg-primary animate-pulse w-2/3" />
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="ml-4">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onViewLogs(task.task_id)}
                      >
                        <FileText className="h-4 w-4 mr-1" />
                        Logs
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
