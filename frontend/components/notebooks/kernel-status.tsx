"use client"

import { useState, useEffect } from "react"
import { Circle, Square, RefreshCw, XCircle } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"

interface Kernel {
  id: string
  name: string
  last_activity: string
  execution_state: "idle" | "busy" | "starting"
  connections: number
}

interface KernelStatusProps {
  onRefresh?: () => void
}

export function KernelStatus({ onRefresh }: KernelStatusProps) {
  const [kernels, setKernels] = useState<Kernel[]>([])
  const [loading, setLoading] = useState(true)

  const fetchKernels = async () => {
    try {
      setLoading(true)
      // In production, this would fetch from /api/notebooks/kernels
      const mockKernels: Kernel[] = [
        {
          id: "kernel-1",
          name: "Python 3 (ipykernel)",
          last_activity: "2 minutes ago",
          execution_state: "idle",
          connections: 1,
        },
        {
          id: "kernel-2",
          name: "Python 3 (ipykernel)",
          last_activity: "Just now",
          execution_state: "busy",
          connections: 1,
        },
      ]
      setKernels(mockKernels)
    } catch (error) {
      console.error("Failed to fetch kernels:", error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchKernels()
    // Poll every 5 seconds for kernel status
    const interval = setInterval(fetchKernels, 5000)
    return () => clearInterval(interval)
  }, [])

  const handleRefresh = () => {
    fetchKernels()
    if (onRefresh) onRefresh()
  }

  const handleStopKernel = async (kernelId: string) => {
    // In production, this would call /api/notebooks/kernels/{id}/stop
    console.log("Stopping kernel:", kernelId)
    await new Promise((resolve) => setTimeout(resolve, 500))
    setKernels((prev) => prev.filter((k) => k.id !== kernelId))
  }

  const handleRestartKernel = async (kernelId: string) => {
    // In production, this would call /api/notebooks/kernels/{id}/restart
    console.log("Restarting kernel:", kernelId)
    setKernels((prev) =>
      prev.map((k) =>
        k.id === kernelId ? { ...k, execution_state: "starting" as const } : k
      )
    )
    await new Promise((resolve) => setTimeout(resolve, 1000))
    setKernels((prev) =>
      prev.map((k) =>
        k.id === kernelId ? { ...k, execution_state: "idle" as const } : k
      )
    )
  }

  const getStateIcon = (state: Kernel["execution_state"]) => {
    switch (state) {
      case "idle":
        return <Circle className="h-3 w-3 text-green-500 fill-green-500" />
      case "busy":
        return <Circle className="h-3 w-3 text-yellow-500 fill-yellow-500 animate-pulse" />
      case "starting":
        return <Circle className="h-3 w-3 text-blue-500 fill-blue-500 animate-pulse" />
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
                      Last activity: {kernel.last_activity}
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
                    disabled={kernel.execution_state === "starting"}
                  >
                    <RefreshCw className="mr-2 h-3 w-3" />
                    Restart
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleStopKernel(kernel.id)}
                    disabled={kernel.execution_state === "starting"}
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
