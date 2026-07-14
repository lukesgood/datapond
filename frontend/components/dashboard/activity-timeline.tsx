"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { CheckCircle2, Info, RefreshCw, Database, Zap } from "lucide-react"
import { formatDistanceToNow } from "date-fns"

interface ActivityTimelineProps {
  className?: string
}

// Generate mock activity events
const generateActivityEvents = () => {
  const now = new Date()

  return [
    {
      id: 1,
      type: "success" as const,
      title: "Aurora pgvector connection healthy",
      description: "All connections active",
      timestamp: new Date(now.getTime() - 2 * 60 * 1000), // 2 minutes ago
      icon: RefreshCw
    },
    {
      id: 2,
      type: "success" as const,
      title: "Query executed",
      description: "Analytics query completed successfully",
      timestamp: new Date(now.getTime() - 15 * 60 * 1000), // 15 minutes ago
      icon: Database
    },
    {
      id: 3,
      type: "success" as const,
      title: "Collection embedded",
      description: "Knowledge base re-embedded",
      timestamp: new Date(now.getTime() - 62 * 60 * 1000), // 1 hour ago
      icon: Zap
    },
    {
      id: 4,
      type: "info" as const,
      title: "Connector synced",
      description: "Incremental sync completed",
      timestamp: new Date(now.getTime() - 3 * 60 * 60 * 1000), // 3 hours ago
      icon: CheckCircle2
    },
    {
      id: 5,
      type: "info" as const,
      title: "Table cataloged",
      description: "New Iceberg table registered",
      timestamp: new Date(now.getTime() - 6 * 60 * 60 * 1000), // 6 hours ago
      icon: Info
    }
  ]
}

export function ActivityTimeline({ className }: ActivityTimelineProps) {
  const events = generateActivityEvents()

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Recent Activity</CardTitle>
        <CardDescription>
          Platform events and system notifications
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {events.map((event, index) => {
          const EventIcon = event.icon

          return (
            <div key={event.id} className="flex items-start gap-3">
              {/* Icon */}
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                <EventIcon className="h-4 w-4 text-muted-foreground" />
              </div>

              {/* Content */}
              <div className="flex-1 space-y-1">
                <p className="text-sm font-medium leading-none">
                  {event.title}
                </p>
                <p className="text-xs text-muted-foreground">
                  {event.description}
                </p>
                <p className="text-xs text-muted-foreground">
                  {formatDistanceToNow(event.timestamp, { addSuffix: true })}
                </p>
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
