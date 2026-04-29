"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Activity, CheckCircle2, XCircle, Loader2 } from "lucide-react"

interface ServiceCardProps {
  name: string
  status: "healthy" | "unhealthy" | "unknown"
  description?: string
  url?: string
  version?: string
}

export function ServiceCard({ name, status, description, url, version }: ServiceCardProps) {
  const statusConfig = {
    healthy: {
      icon: CheckCircle2,
      color: "text-green-500",
      bgColor: "bg-green-500/10",
      badge: "default",
      label: "Healthy"
    },
    unhealthy: {
      icon: XCircle,
      color: "text-red-500",
      bgColor: "bg-red-500/10",
      badge: "destructive",
      label: "Unhealthy"
    },
    unknown: {
      icon: Loader2,
      color: "text-gray-500",
      bgColor: "bg-gray-500/10",
      badge: "secondary",
      label: "Unknown"
    }
  }

  const config = statusConfig[status]
  const Icon = config.icon

  return (
    <Card className="hover:shadow-lg transition-shadow">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{name}</CardTitle>
        <Tooltip>
          <TooltipTrigger>
            <div className={`rounded-full p-2 ${config.bgColor}`}>
              <Icon className={`h-4 w-4 ${config.color} ${status === "unknown" ? "animate-spin" : ""}`} />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>Status: {config.label}</p>
          </TooltipContent>
        </Tooltip>
      </CardHeader>
      <CardContent>
        {description && (
          <CardDescription className="text-xs mb-2">{description}</CardDescription>
        )}
        <div className="flex items-center justify-between">
          <Badge variant={config.badge as any}>{config.label}</Badge>
          {version && (
            <span className="text-xs text-muted-foreground">v{version}</span>
          )}
        </div>
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-primary hover:underline mt-2 block"
          >
            View Details →
          </a>
        )}
      </CardContent>
    </Card>
  )
}
