"use client"
import { CapabilityGate } from "@/lib/capabilities"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useToast } from "@/lib/toast"
import { useConfirm } from "@/lib/confirm"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Input } from "@/components/ui/input"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  FileCode,
  ExternalLink,
  Clock,
  FileText,
  Info,
  Play,
  RefreshCw,
  Plus,
  Grid3x3,
  List,
  Search,
  Upload,
} from "lucide-react"
import { NotebookCard } from "@/components/notebooks/notebook-card"
import { KernelStatus } from "@/components/notebooks/kernel-status"
import { serviceUrls } from "@/lib/urls"

interface ServiceStatus {
  name: string
  status?: "healthy" | "unhealthy" | "unknown" | "managed"
}

interface BackendNotebook {
  name: string
  path: string
  last_modified?: string
  size?: number
  type: string
}

interface NotebookListResponse {
  notebooks: BackendNotebook[]
  total: number
}

function notebookApiPath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/")
}

async function apiError(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => null) as { detail?: unknown } | null
  return typeof body?.detail === "string" ? body.detail : `${fallback} (HTTP ${response.status})`
}

interface NotebookItem {
  name: string
  path: string
  last_modified: string
  modified_ts?: number // raw epoch ms for honest recency sort; 0/undefined when unknown
  size?: string
  type: string
  kernel?: string
}

const RECENT_LIMIT = 10

function NotebooksPageInner() {
  const { toast } = useToast()
  const confirm = useConfirm()
  const [notebooks, setNotebooks] = useState<NotebookItem[]>([])
  const [loading, setLoading] = useState(true)
  const [jupyterStatus, setJupyterStatus] = useState<"healthy" | "unhealthy" | "unknown" | "managed">("unknown")
  const [error, setError] = useState<string | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid")
  const [searchQuery, setSearchQuery] = useState("")
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newNotebookName, setNewNotebookName] = useState("")
  const [notebookToRename, setNotebookToRename] = useState<NotebookItem | null>(null)
  const [renamePath, setRenamePath] = useState("")

  const fetchNotebooks = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [statusRes, notebooksRes] = await Promise.all([
        fetch("/api/services"),
        fetch("/api/notebooks?recursive=true"),
      ])
      if (statusRes.ok) {
        const services = await statusRes.json() as ServiceStatus[]
        const jupyter = services.find((service) => service.name === "jupyterlab")
        setJupyterStatus(jupyter?.status || "unknown")
      } else {
        setJupyterStatus("unknown")
      }
      if (!notebooksRes.ok) {
        throw new Error(await apiError(notebooksRes, "Failed to load notebooks"))
      }
      const data = await notebooksRes.json() as NotebookListResponse
      if (!Array.isArray(data.notebooks)) throw new Error("Notebook API returned an invalid response")
      setNotebooks(data.notebooks.map((notebook) => ({
        name: notebook.name,
        path: notebook.path,
        last_modified: notebook.last_modified
          ? new Date(notebook.last_modified).toLocaleString()
          : "Unknown",
        modified_ts: notebook.last_modified ? Date.parse(notebook.last_modified) || 0 : 0,
        size: notebook.size != null ? `${Math.round(notebook.size / 1024)} KB` : "—",
        type: notebook.type,
        kernel: "Python 3",
      })))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load notebooks")
      setNotebooks([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => { void fetchNotebooks() }, 0)
    return () => window.clearTimeout(timer)
  }, [fetchNotebooks])

  const filteredNotebooks = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    return query
      ? notebooks.filter((notebook) => notebook.name.toLowerCase().includes(query))
      : notebooks
  }, [notebooks, searchQuery])

  const openJupyter = () => {
    window.open(serviceUrls.jupyter(), "_blank", "noopener,noreferrer")
  }

  const openNotebook = (notebook: NotebookItem) => {
    window.open(`/notebooks/view?path=${encodeURIComponent(notebook.path)}`, "_blank", "noopener,noreferrer")
  }

  const handleCreateNotebook = async () => {
    if (!newNotebookName.trim()) return
    const name = newNotebookName.trim().endsWith(".ipynb")
      ? newNotebookName.trim()
      : `${newNotebookName.trim()}.ipynb`
    setBusyAction("create")
    setError(null)
    try {
      const response = await fetch("/api/notebooks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "notebook", path: name }),
      })
      if (!response.ok) throw new Error(await apiError(response, "Failed to create notebook"))
      setNewNotebookName("")
      setShowCreateDialog(false)
      toast(`Notebook "${name}" created`, "success")
      await fetchNotebooks()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to create notebook")
    } finally {
      setBusyAction(null)
    }
  }

  const handleRenameNotebook = async () => {
    if (!notebookToRename || !renamePath.trim()) return
    const newPath = renamePath.trim().endsWith(".ipynb") ? renamePath.trim() : `${renamePath.trim()}.ipynb`
    setBusyAction(`rename:${notebookToRename.path}`)
    setError(null)
    try {
      const response = await fetch(`/api/notebooks/${notebookApiPath(notebookToRename.path)}/rename`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_path: newPath }),
      })
      if (!response.ok) throw new Error(await apiError(response, "Failed to rename notebook"))
      toast(`Notebook renamed to "${newPath}"`, "success")
      setNotebookToRename(null)
      setRenamePath("")
      await fetchNotebooks()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to rename notebook")
    } finally {
      setBusyAction(null)
    }
  }

  const handleDeleteNotebook = async (notebook: NotebookItem) => {
    const ok = await confirm({
      title: "Delete Notebook",
      message: `This deletes the notebook "${notebook.name}" and cannot be undone.`,
      destructive: true,
      confirmText: "Delete",
    })
    if (!ok) return
    setBusyAction(`delete:${notebook.path}`)
    setError(null)
    try {
      const response = await fetch(`/api/notebooks/${notebookApiPath(notebook.path)}`, { method: "DELETE" })
      if (!response.ok) throw new Error(await apiError(response, "Failed to delete notebook"))
      toast(`Notebook "${notebook.name}" deleted`, "success")
      await fetchNotebooks()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to delete notebook")
    } finally {
      setBusyAction(null)
    }
  }

  const handleDuplicateNotebook = async (notebook: NotebookItem) => {
    setBusyAction(`duplicate:${notebook.path}`)
    setError(null)
    try {
      const response = await fetch(`/api/notebooks/${notebookApiPath(notebook.path)}/duplicate`, { method: "POST" })
      if (!response.ok) throw new Error(await apiError(response, "Failed to duplicate notebook"))
      toast(`Notebook "${notebook.name}" duplicated`, "success")
      await fetchNotebooks()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to duplicate notebook")
    } finally {
      setBusyAction(null)
    }
  }

  const handleDownloadNotebook = async (notebook: NotebookItem) => {
    setBusyAction(`download:${notebook.path}`)
    setError(null)
    try {
      const response = await fetch(`/api/notebooks/download?path=${encodeURIComponent(notebook.path)}`)
      if (!response.ok) throw new Error(await apiError(response, "Failed to download notebook"))
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement("a")
      link.href = url
      link.download = notebook.name
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to download notebook")
    } finally {
      setBusyAction(null)
    }
  }

  const handleUploadNotebook = () => {
    const input = document.createElement("input")
    input.type = "file"
    input.accept = ".ipynb,application/x-ipynb+json,application/json"
    input.onchange = async (event: Event) => {
      if (!(event.target instanceof HTMLInputElement)) return
      const file = event.target.files?.[0]
      if (!file) return
      setBusyAction("upload")
      setError(null)
      try {
        const form = new FormData()
        form.append("file", file)
        form.append("path", file.name)
        const response = await fetch("/api/notebooks/upload", { method: "POST", body: form })
        if (!response.ok) throw new Error(await apiError(response, "Failed to upload notebook"))
        toast(`Notebook "${file.name}" uploaded`, "success")
        await fetchNotebooks()
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Failed to upload notebook")
      } finally {
        setBusyAction(null)
      }
    }
    input.click()
  }

  // "Recent" must actually mean most-recently-modified — sort by real timestamp, not API order.
  const recentSorted = useMemo(
    () => [...filteredNotebooks].sort((a, b) => (b.modified_ts ?? 0) - (a.modified_ts ?? 0)),
    [filteredNotebooks],
  )
  const recentNotebooks = recentSorted.slice(0, RECENT_LIMIT)
  const recentCapped = recentSorted.length > RECENT_LIMIT
  // Newest across all notebooks for the stat card (don't assume list is pre-sorted).
  const newestNotebook = useMemo(
    () => notebooks.reduce<NotebookItem | null>(
      (acc, n) => (acc === null || (n.modified_ts ?? 0) > (acc.modified_ts ?? 0) ? n : acc),
      null,
    ),
    [notebooks],
  )

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Skeleton className="h-5 w-[200px]" />
        <div className="space-y-2">
          <Skeleton className="h-8 w-[150px]" />
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
            <BreadcrumbPage>Notebooks</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Notebooks</h2>
          <p className="text-muted-foreground">
            Interactive data science environment with JupyterLab
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={fetchNotebooks}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleUploadNotebook}
            disabled={busyAction === "upload"}
          >
            <Upload className="mr-2 h-4 w-4" />
            Upload
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={openJupyter}
            disabled={jupyterStatus !== "healthy"}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            Open JupyterLab
          </Button>
          <Button
            size="sm"
            onClick={() => setShowCreateDialog(true)}
          >
            <Plus className="mr-2 h-4 w-4" />
            New Notebook
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <Info className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {jupyterStatus === "unhealthy" ? (
        <Alert variant="destructive">
          <Info className="h-4 w-4" />
          <AlertDescription>
            JupyterLab is unavailable. Notebook API actions will fail until the service recovers.
          </AlertDescription>
        </Alert>
      ) : (
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            Interactive JupyterLab opens as an external tool and may require its own authentication. DataPond does not inject a Jupyter token into browser URLs.
          </AlertDescription>
        </Alert>
      )}

      {/* Statistics Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">JupyterLab Status</CardTitle>
              <Play className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              {jupyterStatus === "healthy" ? (
                <Badge variant="default" className="bg-green-600">Running</Badge>
              ) : (
                <Badge variant="destructive">Offline</Badge>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Notebooks</CardTitle>
              <FileCode className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{notebooks.filter(n => n.type === "notebook").length}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Files</CardTitle>
              <FileText className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{notebooks.filter(n => n.type === "file").length}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Last Modified</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            {newestNotebook ? (
              <>
                <div className="text-lg font-bold tabular-nums truncate">{newestNotebook.last_modified}</div>
                <div className="text-xs text-muted-foreground truncate" title={newestNotebook.name}>{newestNotebook.name}</div>
              </>
            ) : (
              <div className="text-lg font-bold text-muted-foreground">N/A</div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="recent" className="space-y-4">
        <div className="flex items-center justify-between">
          <TabsList>
            <TabsTrigger value="recent">Recent</TabsTrigger>
            <TabsTrigger value="all" className="gap-1.5">
              All Notebooks
              {notebooks.length > 0 && (
                <span className="tabular-nums text-xs text-muted-foreground">{filteredNotebooks.length}</span>
              )}
            </TabsTrigger>
            <TabsTrigger value="kernels">Running Kernels</TabsTrigger>
          </TabsList>

          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search notebooks..."
                className="pl-8 w-[250px]"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <div className="flex border rounded-lg">
              <Button
                variant={viewMode === "grid" ? "default" : "ghost"}
                size="icon-sm"
                onClick={() => setViewMode("grid")}
              >
                <Grid3x3 className="h-4 w-4" />
              </Button>
              <Button
                variant={viewMode === "list" ? "default" : "ghost"}
                size="icon-sm"
                onClick={() => setViewMode("list")}
              >
                <List className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        <TabsContent value="recent" className="space-y-4">
          {recentNotebooks.length > 0 ? (
            <>
            {recentCapped && (
              // Never let a capped list read as complete.
              <p className="text-xs text-muted-foreground">
                Showing the {RECENT_LIMIT} most recently modified of {filteredNotebooks.length}. See <span className="font-medium text-foreground">All Notebooks</span> for the full list.
              </p>
            )}
            <div className={viewMode === "grid" ? "grid gap-4 md:grid-cols-2 lg:grid-cols-3" : "space-y-2"}>
              {recentNotebooks.map((notebook) => (
                <NotebookCard
                  key={notebook.path}
                  notebook={notebook}
                  onOpen={openNotebook}
                  onRename={(nb) => {
                    setNotebookToRename(nb)
                    setRenamePath(nb.path)
                  }}
                  onDelete={handleDeleteNotebook}
                  onDuplicate={handleDuplicateNotebook}
                  onDownload={handleDownloadNotebook}
                  busy={busyAction?.endsWith(`:${notebook.path}`) ?? false}
                />
              ))}
            </div>
            </>
          ) : (
            <Card>
              <CardContent className="text-center py-12 text-muted-foreground">
                <FileCode className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p className="text-lg font-medium mb-2">No notebooks found</p>
                <p className="text-sm mb-4">Create your first notebook to get started</p>
                <Button onClick={() => setShowCreateDialog(true)}>
                  <Plus className="mr-2 h-4 w-4" />
                  Create Notebook
                </Button>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="all" className="space-y-4">
          {filteredNotebooks.length > 0 ? (
            <div className={viewMode === "grid" ? "grid gap-4 md:grid-cols-2 lg:grid-cols-3" : "space-y-2"}>
              {filteredNotebooks.map((notebook) => (
                <NotebookCard
                  key={notebook.path}
                  notebook={notebook}
                  onOpen={openNotebook}
                  onRename={(nb) => {
                    setNotebookToRename(nb)
                    setRenamePath(nb.path)
                  }}
                  onDelete={handleDeleteNotebook}
                  onDuplicate={handleDuplicateNotebook}
                  onDownload={handleDownloadNotebook}
                  busy={busyAction?.endsWith(`:${notebook.path}`) ?? false}
                />
              ))}
            </div>
          ) : (
            <Card>
              <CardContent className="text-center py-12 text-muted-foreground">
                <FileCode className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p className="text-lg font-medium mb-2">No notebooks found</p>
                <p className="text-sm mb-4">
                  {searchQuery ? "Try a different search term" : "Create your first notebook to get started"}
                </p>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="kernels">
          <KernelStatus onRefresh={fetchNotebooks} />
        </TabsContent>
      </Tabs>

      <Dialog open={notebookToRename !== null} onOpenChange={(open) => {
        if (!open && busyAction?.startsWith("rename:") !== true) {
          setNotebookToRename(null)
          setRenamePath("")
        }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename Notebook</DialogTitle>
            <DialogDescription>Enter a relative notebook path ending in .ipynb.</DialogDescription>
          </DialogHeader>
          <Input
            value={renamePath}
            onChange={(event) => setRenamePath(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void handleRenameNotebook()
            }}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => {
              setNotebookToRename(null)
              setRenamePath("")
            }} disabled={busyAction?.startsWith("rename:")}>Cancel</Button>
            <Button onClick={handleRenameNotebook} disabled={!renamePath.trim() || busyAction?.startsWith("rename:")}>Rename</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create Notebook Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New Notebook</DialogTitle>
            <DialogDescription>
              Enter a name for your new Jupyter notebook.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <Input
              placeholder="my_notebook.ipynb"
              value={newNotebookName}
              onChange={(e) => setNewNotebookName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  handleCreateNotebook()
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setShowCreateDialog(false)
                setNewNotebookName("")
              }}
            >
              Cancel
            </Button>
            <Button onClick={handleCreateNotebook} disabled={!newNotebookName.trim() || busyAction === "create"}>
              {busyAction === "create" ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  )
}

export default function NotebooksPage() {
  return (
    <CapabilityGate capability="notebooks">
      <NotebooksPageInner />
    </CapabilityGate>
  )
}
