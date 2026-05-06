"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  FlaskConical,
  TrendingUp,
  GitBranch,
  Clock,
  MoreVertical,
  Play,
  Archive,
  Trash2,
} from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useRouter } from "next/navigation"

interface ExperimentCardProps {
  experiment: {
    experiment_id: string
    name: string
    lifecycle_stage: string
    creation_time?: number
    last_update_time?: number
    tags?: Record<string, string>
  }
  runCount?: number
  onDelete?: (experimentId: string) => void
  onArchive?: (experimentId: string) => void
}

export function ExperimentCard({
  experiment,
  runCount = 0,
  onDelete,
  onArchive,
}: ExperimentCardProps) {
  const router = useRouter()

  const getStatusBadge = () => {
    if (experiment.lifecycle_stage === "deleted") {
      return <Badge variant="destructive">Archived</Badge>
    }
    if (runCount > 0) {
      return <Badge className="bg-green-600">Active</Badge>
    }
    return <Badge variant="outline">No Runs</Badge>
  }

  const formatDate = (timestamp?: number) => {
    if (!timestamp) return "Unknown"
    const date = new Date(timestamp)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 60) return `${diffMins} min ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString()
  }

  return (
    <Card className="hover:shadow-md transition-shadow cursor-pointer group">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <FlaskConical className="h-5 w-5 text-purple-500 flex-shrink-0" />
            <CardTitle className="text-base truncate">{experiment.name}</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {getStatusBadge()}
            <DropdownMenu>
              <DropdownMenuTrigger
                className="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 hover:bg-accent hover:text-accent-foreground h-8 w-8 p-0 opacity-0 group-hover:opacity-100"
              >
                <MoreVertical className="h-4 w-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => router.push(`/experiments/${experiment.experiment_id}`)}>
                  <TrendingUp className="mr-2 h-4 w-4" />
                  View Details
                </DropdownMenuItem>
                <DropdownMenuItem>
                  <Play className="mr-2 h-4 w-4" />
                  Create Run
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => onArchive?.(experiment.experiment_id)}
                  disabled={experiment.lifecycle_stage === "deleted"}
                >
                  <Archive className="mr-2 h-4 w-4" />
                  Archive
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => onDelete?.(experiment.experiment_id)}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Experiment ID:</span>
            <span className="font-mono text-xs">{experiment.experiment_id}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Runs:</span>
            <div className="flex items-center gap-1">
              <GitBranch className="h-3 w-3" />
              <span className="font-medium">{runCount}</span>
            </div>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Created:</span>
            <div className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              <span className="font-medium">{formatDate(experiment.creation_time)}</span>
            </div>
          </div>
          {experiment.tags && Object.keys(experiment.tags).length > 0 && (
            <div className="flex flex-wrap gap-1 pt-2">
              {Object.entries(experiment.tags).slice(0, 3).map(([key, value]) => (
                <Badge key={key} variant="outline" className="text-xs">
                  {key}: {value}
                </Badge>
              ))}
            </div>
          )}
        </div>

        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => router.push(`/experiments/${experiment.experiment_id}`)}
        >
          <TrendingUp className="mr-2 h-4 w-4" />
          View Details
        </Button>
      </CardContent>
    </Card>
  )
}
