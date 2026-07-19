"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { CheckCircle2, XCircle, Loader2, ExternalLink } from "lucide-react"

type ServiceStatus = "healthy" | "unhealthy" | "unknown" | "managed"
type BadgeVariant = React.ComponentProps<typeof Badge>["variant"]

interface ServiceCardProps {
  name: string
  status: ServiceStatus
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
  version,
}: ServiceCardProps) {
  const statusConfig: Record<ServiceStatus, {
    icon: React.ComponentType<{ className?: string }>
    badge: BadgeVariant
    label: string
  }> = {
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
      icon: ExternalLink,
      badge: "outline",
      label: "Configured"
    }
  }

  const config = statusConfig[status]
  const Icon = config.icon

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
        <Badge variant={config.badge}>
          {config.label}
        </Badge>
        {version && (
          <span className="ml-2 text-xs text-muted-foreground font-mono">{version}</span>
        )}

      </CardContent>
    </Card>
  )
}
