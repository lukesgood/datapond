"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { CheckCircle2, XCircle, Loader2, ExternalLink, TrendingUp } from "lucide-react"

interface ServiceCardProps {
  name: string
  status: "healthy" | "unhealthy" | "unknown" | "managed"
  description?: string
  url?: string
  version?: string
  uptime?: string
  responseTime?: string
}

export function ServiceCard({
  name,
  status,
  description,
  url,
  version,
  uptime,
  responseTime
}: ServiceCardProps) {
  const statusConfig = {
    healthy: {
      icon: CheckCircle2,
      badge: "default",
      label: "Operational"
    },
    unhealthy: {
      icon: XCircle,
      badge: "destructive",
      label: "Down"
    },
    unknown: {
      icon: Loader2,
      badge: "secondary",
      label: "Unknown"
    },
    managed: {
      icon: CheckCircle2,
      badge: "outline",
      label: "AWS managed"
    }
  }

  const config = statusConfig[status]
  const Icon = config.icon

  // Mock uptime percentage (would come from real data)
  const mockUptime = status === "healthy" ? 99.2 + Math.random() * 0.7 : status === "unhealthy" ? 85.5 + Math.random() * 10 : 0

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <CardTitle className="text-sm font-medium">{name}</CardTitle>
            {description && (
              <CardDescription className="text-xs">
                {description}
              </CardDescription>
            )}
          </div>
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted">
            <Icon className={`h-4 w-4 text-muted-foreground ${status === "unknown" ? "animate-spin" : ""}`} />
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <Badge variant={config.badge as any}>
          {config.label}
        </Badge>
        {version && (
          <span className="ml-2 text-xs text-muted-foreground font-mono">{version}</span>
        )}

        {status !== "unknown" && status !== "managed" && (
          <div className="flex items-center justify-between text-xs mt-3">
            <span className="text-muted-foreground">Uptime</span>
            <span className="font-medium">
              {mockUptime.toFixed(1)}%
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
