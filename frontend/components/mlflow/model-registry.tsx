"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import {
  Package,
  Search,
  ArrowUpCircle,
  Archive,
  MoreVertical,
  ExternalLink,
  GitBranch,
  Clock,
} from "lucide-react"
import { useState, useEffect, useCallback } from "react"
import { serviceUrls } from "@/lib/urls"

interface ModelVersion {
  name: string
  version: string
  creation_timestamp: number
  last_updated_timestamp?: number
  current_stage: string
  description?: string
  run_id?: string
  source?: string
  status: string
}

interface RegisteredModel {
  name: string
  creation_timestamp: number
  last_updated_timestamp?: number
  description?: string
  latest_versions?: ModelVersion[]
  tags?: Record<string, string>
}

export function ModelRegistry() {
  const [models, setModels] = useState<RegisteredModel[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")
  const [stageFilter, setStageFilter] = useState<string>("all")
  const [error, setError] = useState<string | null>(null)

  const fetchModels = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch("/api/mlflow/registered-models")
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: unknown } | null
        throw new Error(typeof body?.detail === "string" ? body.detail : `Failed to load models (HTTP ${response.status})`)
      }
      const data = await response.json() as RegisteredModel[]
      if (!Array.isArray(data)) throw new Error("Invalid model registry response")
      setModels(data)
    } catch (caught) {
      setModels([])
      setError(caught instanceof Error ? caught.message : "Failed to load models")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => { void fetchModels() }, 0)
    return () => clearTimeout(timer)
  }, [fetchModels])

  const getStageBadge = (stage: string) => {
    switch (stage) {
      case "Production":
        return <Badge className="bg-green-600">Production</Badge>
      case "Staging":
        return <Badge className="bg-blue-600">Staging</Badge>
      case "Archived":
        return <Badge variant="outline">Archived</Badge>
      default:
        return <Badge variant="outline">None</Badge>
    }
  }

  const promoteModel = async (modelName: string, version: string, stage: string) => {
    setError(null)
    try {
      const response = await fetch("/api/mlflow/model-versions/transition-stage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: modelName, version, stage }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: unknown } | null
        throw new Error(typeof body?.detail === "string" ? body.detail : `Model transition failed (HTTP ${response.status})`)
      }
      await fetchModels()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Model transition failed")
    }
  }

  const formatDate = (timestamp?: number) => {
    if (!timestamp) return "Unknown"
    const date = new Date(timestamp)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffDays === 0) return "Today"
    if (diffDays === 1) return "Yesterday"
    if (diffDays < 7) return `${diffDays} days ago`
    return date.toLocaleDateString()
  }

  const filteredModels = models.filter((model) => {
    const matchesSearch = model.name.toLowerCase().includes(searchQuery.toLowerCase())
    if (!matchesSearch) return false

    if (stageFilter === "all") return true

    return model.latest_versions?.some((v) => v.current_stage === stageFilter)
  })

  if (loading) {
    return (
      <Card>
        <CardContent className="py-8 text-center">
          <p className="text-muted-foreground">Loading models...</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {error && (
        <Card>
          <CardContent className="py-3 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}
      {/* Search and Filters */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex gap-4">
            <div className="flex-1">
              <div className="relative">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search models..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8"
                />
              </div>
            </div>
            <Select value={stageFilter} onValueChange={(value) => setStageFilter(value || "all")}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Filter by stage" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Stages</SelectItem>
                <SelectItem value="Production">Production</SelectItem>
                <SelectItem value="Staging">Staging</SelectItem>
                <SelectItem value="Archived">Archived</SelectItem>
                <SelectItem value="None">None</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Models List */}
      {filteredModels.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center">
            <Package className="h-12 w-12 mx-auto text-muted-foreground opacity-50 mb-3" />
            <p className="text-muted-foreground">
              {searchQuery ? "No models match your search" : "No registered models yet"}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {filteredModels.map((model) => (
            <Card key={model.name}>
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <Package className="h-5 w-5 text-purple-500" />
                      <CardTitle className="text-lg">{model.name}</CardTitle>
                    </div>
                    {model.description && (
                      <p className="text-sm text-muted-foreground">{model.description}</p>
                    )}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => window.open(
                      `${serviceUrls.mlflow()}/#/models/${encodeURIComponent(model.name)}`,
                      "_blank",
                      "noopener,noreferrer",
                    )}
                  >
                    <ExternalLink className="mr-2 h-4 w-4" />
                    Open in MLflow
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {/* Model Metadata */}
                  <div className="flex gap-6 text-sm">
                    <div>
                      <span className="text-muted-foreground">Created:</span>{" "}
                      <span className="font-medium">{formatDate(model.creation_timestamp)}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Updated:</span>{" "}
                      <span className="font-medium">
                        {formatDate(model.last_updated_timestamp)}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Versions:</span>{" "}
                      <span className="font-medium">{model.latest_versions?.length || 0}</span>
                    </div>
                  </div>

                  {/* Versions Table */}
                  {model.latest_versions && model.latest_versions.length > 0 && (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Version</TableHead>
                          <TableHead>Stage</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Created</TableHead>
                          <TableHead className="text-right">Actions</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {model.latest_versions.map((version) => (
                          <TableRow key={version.version}>
                            <TableCell className="font-medium">v{version.version}</TableCell>
                            <TableCell>{getStageBadge(version.current_stage)}</TableCell>
                            <TableCell>
                              <Badge variant="outline" className="bg-green-50">
                                {version.status}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-sm text-muted-foreground">
                              <div className="flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                {formatDate(version.creation_timestamp)}
                              </div>
                            </TableCell>
                            <TableCell className="text-right">
                              <DropdownMenu>
                                <DropdownMenuTrigger className="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 hover:bg-accent hover:text-accent-foreground h-9 px-3">
                                  <MoreVertical className="h-4 w-4" />
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  <DropdownMenuItem
                                    onClick={() =>
                                      promoteModel(model.name, version.version, "Staging")
                                    }
                                    disabled={version.current_stage === "Staging"}
                                  >
                                    <ArrowUpCircle className="mr-2 h-4 w-4" />
                                    Promote to Staging
                                  </DropdownMenuItem>
                                  <DropdownMenuItem
                                    onClick={() =>
                                      promoteModel(model.name, version.version, "Production")
                                    }
                                    disabled={version.current_stage === "Production"}
                                  >
                                    <ArrowUpCircle className="mr-2 h-4 w-4 text-green-600" />
                                    Promote to Production
                                  </DropdownMenuItem>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem
                                    onClick={() =>
                                      promoteModel(model.name, version.version, "Archived")
                                    }
                                  >
                                    <Archive className="mr-2 h-4 w-4" />
                                    Archive
                                  </DropdownMenuItem>
                                  {version.run_id && (
                                    <>
                                      <DropdownMenuSeparator />
                                      <DropdownMenuItem>
                                        <GitBranch className="mr-2 h-4 w-4" />
                                        View Source Run
                                      </DropdownMenuItem>
                                    </>
                                  )}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
