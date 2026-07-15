"use client"

import { useEffect, useState, useRef } from "react"
import { useConfirm } from "@/lib/confirm"
import { useParams, useRouter } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import {
  Activity,
  RefreshCw,
  Power,
  AlertCircle,
  CheckCircle2,
  Clock,
  Cpu,
  MemoryStick,
  HardDrive,
  ExternalLink,
  Layers,
} from "lucide-react"
import { LogsViewer } from "@/components/services/logs-viewer"
import { MetricsChart, type ServiceMetricsData } from "@/components/services/metrics-chart"
import { PodList } from "@/components/services/pod-list"

// Only services that actually expose a sub-path console. Trino / SeaweedFS UIs
// don't support sub-path hosting and AWS-managed services have no in-cluster UI.
const EXTERNAL_URLS: Record<string, string> = {
  jupyterlab:   "/jupyter",
  mlflow:       "/mlflow",
  openmetadata: "/openmetadata",
  airflow:      "/airflow",
}

interface ServiceDetail {
  name: string
  status: "healthy" | "unhealthy" | "unknown" | "managed"
  url?: string
  version?: string
  description?: string
  replicas?: number
  cpu_usage?: number
  memory_usage?: number
  uptime?: string
  namespace?: string
  labels?: Record<string, string>
  annotations?: Record<string, string>
  ports?: Array<{ name: string; port: number; protocol: string }>
  env?: Record<string, string>
}

interface Pod {
  name: string
  status: "Running" | "Pending" | "Failed" | "Succeeded" | "Unknown"
  restarts: number
  age: string
  cpu_usage?: number
  memory_usage?: number
}

// Raw shape returned by GET /api/services/{service}/pods (backend PodInfo) —
// note "phase", not "status".
interface RawPod {
  name: string
  phase: Pod["status"]
  ready: boolean
  restarts: number
  age: string
  node?: string
  ip?: string
}

export default function ServiceDetailPage() {
  const params = useParams()
  const router = useRouter()
  const serviceId = params.id as string

  const [service, setService] = useState<ServiceDetail | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [pods, setPods] = useState<Pod[]>([])
  const [metrics, setMetrics] = useState<ServiceMetricsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [metricsLoading, setMetricsLoading] = useState(false)
  const [isRestarting, setIsRestarting] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [showScaleDialog, setShowScaleDialog] = useState(false)
  const [scaleValue, setScaleValue] = useState(1)
  const [activeTab, setActiveTab] = useState("overview")
  const [selectedPod, setSelectedPod] = useState<string | null>(null)
  const [logsLoading, setLogsLoading] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  const fetchServiceDetail = async () => {
    try {
      setLoading(true)
      const response = await fetch(`/api/services/${serviceId}`)
      if (!response.ok) {
        // 404 (unknown service) or any other error — show the "not found" state
        // rather than rendering a blank/zeroed-out page.
        setService(null)
        return
      }
      const data = await response.json()
      setService(data)
      setScaleValue(data.replicas || 1)
    } catch (error) {
      console.error("Failed to fetch service details:", error)
      setService(null)
    } finally {
      setLoading(false)
    }
  }

  const fetchLogs = async (podName?: string | null) => {
    try {
      setLogsLoading(true)
      const params = new URLSearchParams({ lines: "200" })
      if (podName) params.set("pod", podName)
      const response = await fetch(`/api/services/${serviceId}/logs?${params}`)
      const data = await response.json()
      if (data.lines && Array.isArray(data.lines)) {
        setLogs(data.lines)
      }
    } catch (error) {
      console.error("Failed to fetch logs:", error)
    } finally {
      setLogsLoading(false)
    }
  }

  const fetchPods = async () => {
    try {
      const response = await fetch(`/api/services/${serviceId}/pods`)
      if (!response.ok) {
        // e.g. 404 when the service currently has no pods — nothing to show.
        setPods([])
        return
      }
      // GET /pods returns a bare array of PodInfo (field is "phase", not "status").
      const data: RawPod[] = await response.json()
      if (Array.isArray(data)) {
        setPods(
          data.map((p) => ({
            name: p.name,
            status: p.phase,
            restarts: p.restarts,
            age: p.age,
          }))
        )
      }
    } catch (error) {
      console.error("Failed to fetch pods:", error)
    }
  }

  const fetchMetrics = async () => {
    try {
      setMetricsLoading(true)
      const response = await fetch(`/api/services/${serviceId}/metrics`)
      const data = await response.json()
      setMetrics(data)
    } catch (error) {
      console.error("Failed to fetch metrics:", error)
    } finally {
      setMetricsLoading(false)
    }
  }

  const confirm = useConfirm()
  const handleRestart = async () => {
    if (!(await confirm({ title: "Restart service", message: "Restart this service?", confirmText: "Restart" }))) return

    setIsRestarting(true)
    try {
      const response = await fetch(`/api/services/${serviceId}/restart`, {
        method: "POST",
      })
      if (response.ok) {
        setTimeout(() => {
          fetchServiceDetail()
          fetchPods()
          setIsRestarting(false)
        }, 2000)
      }
    } catch (error) {
      console.error("Failed to restart service:", error)
      setIsRestarting(false)
    }
  }

  const handleScale = async () => {
    try {
      const response = await fetch(`/api/services/${serviceId}/scale`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ replicas: scaleValue }),
      })
      if (response.ok) {
        setShowScaleDialog(false)
        fetchServiceDetail()
        fetchPods()
      }
    } catch (error) {
      console.error("Failed to scale service:", error)
    }
  }

  const handleDeletePod = async (podName: string) => {
    try {
      const response = await fetch(`/api/services/${serviceId}/pods/${podName}`, {
        method: "DELETE",
      })
      if (response.ok) {
        fetchPods()
      }
    } catch (error) {
      console.error("Failed to delete pod:", error)
    }
  }

  const toggleLogStreaming = (streaming: boolean) => {
    setIsStreaming(streaming)

    if (streaming) {
      // Start WebSocket connection
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
      const host = window.location.host
      const ws = new WebSocket(
        `${protocol}//${host}/api/services/${serviceId}/logs/stream`
      )

      ws.onopen = () => {
        console.log("WebSocket connected")
      }

      ws.onmessage = (event) => {
        setLogs((prev) => [...prev.slice(-999), event.data])
      }

      ws.onerror = (error) => {
        console.error("WebSocket error:", error)
        setIsStreaming(false)
      }

      ws.onclose = () => {
        console.log("WebSocket closed")
        setIsStreaming(false)
      }

      wsRef.current = ws
    } else {
      // Close WebSocket
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }

  useEffect(() => {
    fetchServiceDetail()
    fetchLogs()
    fetchPods()
    fetchMetrics()

    const serviceInterval = setInterval(fetchServiceDetail, 30000)
    const podsInterval = setInterval(fetchPods, 5000)
    const metricsInterval = setInterval(fetchMetrics, 10000)

    return () => {
      clearInterval(serviceInterval)
      clearInterval(podsInterval)
      clearInterval(metricsInterval)
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [serviceId])

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "healthy":
      case "managed":
        return <CheckCircle2 className="h-4 w-4 text-[var(--dp-good)]" />
      case "unhealthy":
        return <AlertCircle className="h-4 w-4 text-destructive" />
      default:
        return <Clock className="h-4 w-4 text-muted-foreground" />
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "healthy":
        return <Badge variant="default" className="bg-[var(--dp-good)] text-white">Healthy</Badge>
      case "unhealthy":
        return <Badge variant="destructive">Unhealthy</Badge>
      case "managed":
        return (
          <Badge variant="outline" className="border-[var(--dp-good)] text-[var(--dp-good)]">
            <CheckCircle2 className="mr-1 h-3 w-3" />
            AWS managed
          </Badge>
        )
      default:
        return <Badge variant="secondary">Unknown</Badge>
    }
  }

  const isManaged = service?.status === "managed"

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Skeleton className="h-5 w-[250px]" />
        <div className="space-y-2">
          <Skeleton className="h-8 w-[200px]" />
          <Skeleton className="h-4 w-[300px]" />
        </div>
        <div className="grid gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-[120px]" />
          ))}
        </div>
        <Skeleton className="h-[400px]" />
      </div>
    )
  }

  if (!service) {
    return (
      <div className="flex-1 p-8 pt-6">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Service not found</AlertTitle>
          <AlertDescription>
            The service "{serviceId}" could not be found.
          </AlertDescription>
        </Alert>
        <Button className="mt-4" onClick={() => router.push("/dashboard")}>
          Back to Dashboard
        </Button>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="/dashboard">Home</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink href="/services">Services</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{service.name}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight capitalize">
              {service.name}
            </h1>
            {getStatusBadge(service.status)}
          </div>
          <p className="text-muted-foreground">
            {service.description || `Monitor and manage ${service.name} service`}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              fetchServiceDetail()
              fetchPods()
              fetchMetrics()
            }}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          {!isManaged && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowScaleDialog(true)}
              >
                <Layers className="mr-2 h-4 w-4" />
                Scale
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleRestart}
                disabled={isRestarting}
              >
                <Power
                  className={`mr-2 h-4 w-4 ${isRestarting ? "animate-spin" : ""}`}
                />
                {isRestarting ? "Restarting..." : "Restart"}
              </Button>
            </>
          )}
          {!isManaged && EXTERNAL_URLS[service.name] && (
            <Button
              variant="default"
              size="sm"
              onClick={() => window.open(EXTERNAL_URLS[service.name], "_blank")}
            >
              <ExternalLink className="mr-2 h-4 w-4" />
              Open UI
            </Button>
          )}
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Status</CardTitle>
              <Activity className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              {getStatusIcon(service.status)}
              <span className="text-2xl font-bold capitalize">{service.status}</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">CPU Usage</CardTitle>
              <Cpu className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {service.cpu_usage ? `${service.cpu_usage.toFixed(1)}%` : "N/A"}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Memory</CardTitle>
              <MemoryStick className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {service.memory_usage ? `${service.memory_usage.toFixed(1)}%` : "N/A"}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Replicas</CardTitle>
              <HardDrive className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{service.replicas || 1}</div>
          </CardContent>
        </Card>
      </div>

      {/* Managed services have no in-cluster pods to inspect or control */}
      {isManaged ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Managed by AWS</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Managed by AWS — no pod controls. This service runs as an AWS-managed
              resource, so scaling, restarts, pod inspection, and log streaming are
              handled by AWS and are not available here.
            </p>
          </CardContent>
        </Card>
      ) : (
      <>
      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList>
          <TabsTrigger value="logs">Logs</TabsTrigger>
          <TabsTrigger value="metrics">Metrics</TabsTrigger>
          <TabsTrigger value="pods">Pods</TabsTrigger>
          <TabsTrigger value="config">Configuration</TabsTrigger>
        </TabsList>

        <TabsContent value="logs" className="space-y-4">
          {selectedPod && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground bg-muted/40 rounded px-3 py-1.5">
              <span>Showing logs for pod:</span>
              <span className="font-mono font-medium text-foreground">{selectedPod}</span>
              <button
                className="ml-auto text-xs underline hover:no-underline"
                onClick={() => { setSelectedPod(null); fetchLogs(null) }}
              >
                Show all pods
              </button>
            </div>
          )}
          {logsLoading ? (
            <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">
              <div className="h-4 w-4 border-2 border-primary border-t-transparent rounded-full animate-spin mr-2" />
              Loading logs…
            </div>
          ) : (
            <LogsViewer
              logs={logs}
              isStreaming={isStreaming}
              onToggleStream={toggleLogStreaming}
            />
          )}
        </TabsContent>

        <TabsContent value="metrics" className="space-y-4">
          <MetricsChart metrics={metrics} loading={metricsLoading} />
        </TabsContent>

        <TabsContent value="pods" className="space-y-4">
          <PodList
            pods={pods}
            onViewLogs={(podName) => {
              setSelectedPod(podName)
              fetchLogs(podName)
              setActiveTab("logs")
            }}
            onDeletePod={handleDeletePod}
            onRefresh={fetchPods}
          />
        </TabsContent>

        <TabsContent value="config" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Service Configuration</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div>
                  <h3 className="font-medium mb-2">Basic Information</h3>
                  <div className="space-y-2">
                    <div className="grid grid-cols-3 gap-2 py-2 border-b text-sm">
                      <span className="font-medium">Version</span>
                      <span className="col-span-2">{service.version || "N/A"}</span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 py-2 border-b text-sm">
                      <span className="font-medium">Namespace</span>
                      <span className="col-span-2">
                        {service.namespace || "datapond"}
                      </span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 py-2 border-b text-sm">
                      <span className="font-medium">URL</span>
                      <span className="col-span-2">
                        {EXTERNAL_URLS[service.name] ? (
                          <a
                            href={EXTERNAL_URLS[service.name]}
                            target="_blank"
                            rel="noreferrer"
                            className="text-primary hover:underline"
                          >
                            {EXTERNAL_URLS[service.name]}
                          </a>
                        ) : (
                          "N/A"
                        )}
                      </span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 py-2 border-b text-sm">
                      <span className="font-medium">Uptime</span>
                      <span className="col-span-2">{service.uptime || "N/A"}</span>
                    </div>
                  </div>
                </div>

                {service.ports && service.ports.length > 0 && (
                  <div>
                    <h3 className="font-medium mb-2">Service Ports</h3>
                    <div className="space-y-2">
                      {service.ports.map((port, idx) => (
                        <div
                          key={idx}
                          className="grid grid-cols-3 gap-2 py-2 border-b text-sm"
                        >
                          <span className="font-medium">{port.name}</span>
                          <span className="col-span-2">
                            {port.port} ({port.protocol})
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {service.labels && Object.keys(service.labels).length > 0 && (
                  <div>
                    <h3 className="font-medium mb-2">Labels</h3>
                    <div className="font-mono text-xs bg-muted p-3 rounded space-y-1">
                      {Object.entries(service.labels).map(([key, value]) => (
                        <div key={key}>
                          <span className="text-muted-foreground">{key}:</span>{" "}
                          {value}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {service.env && Object.keys(service.env).length > 0 && (
                  <div>
                    <h3 className="font-medium mb-2">
                      Environment Variables (Read-only)
                    </h3>
                    <div className="font-mono text-xs bg-muted p-3 rounded space-y-1 max-h-[300px] overflow-auto">
                      {Object.entries(service.env).map(([key, value]) => (
                        <div key={key}>
                          <span className="text-muted-foreground">{key}:</span>{" "}
                          {value}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
      </>
      )}

      {/* Scale Dialog */}
      <Dialog open={showScaleDialog} onOpenChange={setShowScaleDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Scale Service</DialogTitle>
            <DialogDescription>
              Set the number of replicas for {service.name}
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <label className="text-sm font-medium mb-2 block">
              Number of Replicas
            </label>
            <Input
              type="number"
              min="0"
              max="10"
              value={scaleValue}
              onChange={(e) => setScaleValue(parseInt(e.target.value) || 1)}
            />
            <p className="text-xs text-muted-foreground mt-2">
              Current replicas: {service.replicas || 1}
            </p>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowScaleDialog(false)}
            >
              Cancel
            </Button>
            <Button onClick={handleScale}>Scale</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
