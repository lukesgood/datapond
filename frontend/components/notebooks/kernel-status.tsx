"use client"

import { useState, useEffect, useCallback } from "react"
import { Circle, Square, RefreshCw, XCircle } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"

interface Kernel {
  id: string
  name: string
  last_activity?: string
  execution_state?: "idle" | "busy" | "starting" | string
  connections: number
}

interface KernelStatusProps {
  onRefresh?: () => void
}

export function KernelStatus({ onRefresh }: KernelStatusProps) {
  const [kernels, setKernels] = useState<Kernel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actingOn, setActingOn] = useState<string | null>(null)

  const fetchKernels = useCallback(async () => {
    try {
      setError(null)
      const response = await fetch("/api/notebooks/kernels/list")
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: unknown } | null
        throw new Error(typeof body?.detail === "string" ? body.detail : `Failed to load kernels (HTTP ${response.status})`)
      }
      setKernels(await response.json() as Kernel[])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load kernels")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const initial = setTimeout(() => { void fetchKernels() }, 0)
    const interval = setInterval(() => { void fetchKernels() }, 5000)
    return () => {
      clearTimeout(initial)
      clearInterval(interval)
    }
  }, [fetchKernels])

  const handleRefresh = () => {
    void fetchKernels()
    onRefresh?.()
  }

  const kernelAction = async (kernelId: string, action: "stop" | "restart") => {
    setActingOn(kernelId)
    setError(null)
    try {
      const encoded = encodeURIComponent(kernelId)
      const response = await fetch(
        action === "stop"
          ? `/api/notebooks/kernels/${encoded}`
          : `/api/notebooks/kernels/${encoded}/restart`,
        { method: action === "stop" ? "DELETE" : "POST" },
      )
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: unknown } | null
        throw new Error(typeof body?.detail === "string" ? body.detail : `Kernel ${action} failed (HTTP ${response.status})`)
      }
      await fetchKernels()
      onRefresh?.()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : `Kernel ${action} failed`)
    } finally {
      setActingOn(null)
    }
  }

  const handleStopKernel = async (kernelId: string) => kernelAction(kernelId, "stop")
  const handleRestartKernel = async (kernelId: string) => kernelAction(kernelId, "restart")

  const getStateIcon = (state: Kernel["execution_state"]) => {
    switch (state) {
      case "idle":
        return <Circle className="h-3 w-3 text-green-500 fill-green-500" />
      case "busy":
        return <Circle className="h-3 w-3 text-yellow-500 fill-yellow-500 animate-pulse" />
      case "starting":
        return <Circle className="h-3 w-3 text-blue-500 fill-blue-500 animate-pulse" />
      default:
        return <Circle className="h-3 w-3 text-gray-400 fill-gray-400" />
    }
  }

  const getStateLabel = (state: Kernel["execution_state"]) => {
    switch (state) {
      case "idle":
        return "Idle"
      case "busy":
        return "Busy"
      case "starting":
        return "Starting"
      default:
        return state || "Unknown"
    }
  }

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Running Kernels</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {[...Array(2)].map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">
            Running Kernels ({kernels.length})
          </CardTitle>
          <Button variant="ghost" size="icon-sm" onClick={handleRefresh}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {error && <p className="mb-3 text-sm text-destructive">{error}</p>}
        {kernels.length > 0 ? (
          <div className="space-y-2">
            {kernels.map((kernel) => (
              <div
                key={kernel.id}
                className="border rounded-lg p-3 space-y-2 hover:bg-accent/50 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      {getStateIcon(kernel.execution_state)}
                      <span className="font-medium text-sm truncate">
                        {kernel.name}
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Last activity: {kernel.last_activity ? new Date(kernel.last_activity).toLocaleString() : "Unknown"}
                    </div>
                  </div>

                  <Badge variant="secondary" className="text-xs">
                    {getStateLabel(kernel.execution_state)}
                  </Badge>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleRestartKernel(kernel.id)}
                    disabled={actingOn === kernel.id}
                  >
                    <RefreshCw className="mr-2 h-3 w-3" />
                    Restart
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleStopKernel(kernel.id)}
                    disabled={actingOn === kernel.id}
                  >
                    <Square className="mr-2 h-3 w-3" />
                    Stop
                  </Button>
                  <div className="flex-1" />
                  <span className="text-xs text-muted-foreground">
                    {kernel.connections} connection{kernel.connections !== 1 ? "s" : ""}
                  </span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-muted-foreground">
            <XCircle className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No running kernels</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
