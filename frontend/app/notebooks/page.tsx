"use client"

import { useEffect, useState } from "react"
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
import { JupyterEmbed } from "@/components/notebooks/jupyter-embed"
import { KernelStatus } from "@/components/notebooks/kernel-status"
import { serviceUrls } from "@/lib/urls"

interface NotebookItem {
  name: string
  path: string
  last_modified: string
  size?: string
  type: "notebook" | "file"
  kernel?: string
}

export default function NotebooksPage() {
  const [notebooks, setNotebooks] = useState<NotebookItem[]>([])
  const [filteredNotebooks, setFilteredNotebooks] = useState<NotebookItem[]>([])
  const [loading, setLoading] = useState(true)
  const [jupyterStatus, setJupyterStatus] = useState<"healthy" | "unhealthy" | "unknown">("unknown")
  const [selectedNotebook, setSelectedNotebook] = useState<NotebookItem | null>(null)
  const [showJupyter, setShowJupyter] = useState(false)
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid")
  const [searchQuery, setSearchQuery] = useState("")
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newNotebookName, setNewNotebookName] = useState("")
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [notebookToDelete, setNotebookToDelete] = useState<NotebookItem | null>(null)

  const fetchNotebooks = async () => {
    try {
      setLoading(true)
      // Check JupyterLab status
      const statusRes = await fetch("/api/services")
      const servicesData = await statusRes.json()
      const jupyter = servicesData.find((s: any) => s.name === "jupyterlab")
      setJupyterStatus(jupyter?.status || "unknown")

      // Fetch notebook list from JupyterLab Contents API
      const [rootRes, workRes] = await Promise.all([
        fetch("/jupyter/api/contents?token=jupyter"),
        fetch("/jupyter/api/contents/work?token=jupyter"),
      ])

      const rootData = rootRes.ok ? await rootRes.json() : { content: [] }
      const workData = workRes.ok ? await workRes.json() : { content: [] }

      const allItems = [
        ...(rootData.content || []),
        ...(workData.content || []).map((f: any) => ({ ...f, path: `work/${f.path}` })),
      ].filter((f: any) => f.type !== "directory")

      const items: NotebookItem[] = allItems.map((f: any) => ({
        name: f.name,
        path: f.path,
        last_modified: f.last_modified
          ? new Date(f.last_modified).toLocaleString()
          : "Unknown",
        size: f.size != null ? `${Math.round(f.size / 1024)} KB` : "—",
        type: f.name.endsWith(".ipynb") ? "notebook" : "file",
        kernel: "Python 3",
      }))

      setNotebooks(items)
      setFilteredNotebooks(items)
    } catch (error) {
      console.error("Failed to fetch notebooks:", error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchNotebooks()
  }, [])

  useEffect(() => {
    if (searchQuery.trim() === "") {
      setFilteredNotebooks(notebooks)
    } else {
      const filtered = notebooks.filter((notebook) =>
        notebook.name.toLowerCase().includes(searchQuery.toLowerCase())
      )
      setFilteredNotebooks(filtered)
    }
  }, [searchQuery, notebooks])

  const openJupyter = () => {
    window.open(serviceUrls.jupyter(), "_blank")
  }

  const openNotebook = (notebook: NotebookItem) => {
    window.open(`${serviceUrls.jupyter()}/lab/tree/${notebook.path}`, "_blank")
  }

  const handleCreateNotebook = async () => {
    if (!newNotebookName.trim()) return

    const name = newNotebookName.endsWith(".ipynb")
      ? newNotebookName
      : `${newNotebookName}.ipynb`

    try {
      const res = await fetch("/jupyter/api/contents?token=jupyter", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "notebook", path: name }),
      })
      if (res.ok) {
        setNewNotebookName("")
        setShowCreateDialog(false)
        await fetchNotebooks()
        // Open the newly created notebook
        window.open(`${serviceUrls.jupyter()}/lab/tree/${name}`, "_blank")
        return
      }
    } catch (error) {
      console.error("Failed to create notebook via API:", error)
    }

    // Fallback: local state update
    const newNotebook: NotebookItem = {
      name,
      path: name,
      last_modified: new Date().toLocaleString(),
      size: "0 KB",
      type: "notebook",
      kernel: "Python 3",
    }
    setNotebooks([newNotebook, ...notebooks])
    setNewNotebookName("")
    setShowCreateDialog(false)
    window.open(`http://datapond.local/jupyter/lab/tree/${name}`, "_blank")
  }

  const handleDeleteNotebook = async () => {
    if (!notebookToDelete) return

    try {
      await fetch(
        `/jupyter/api/contents/${encodeURIComponent(notebookToDelete.path)}?token=jupyter`,
        { method: "DELETE" }
      )
      await fetchNotebooks()
    } catch (error) {
      console.error("Failed to delete notebook via API:", error)
      // Fallback: remove from local state
      setNotebooks(notebooks.filter((n) => n.path !== notebookToDelete.path))
    }

    setNotebookToDelete(null)
    setShowDeleteDialog(false)
  }

  const handleDuplicateNotebook = async (notebook: NotebookItem) => {
    // In production, this would call /api/notebooks/{path}/duplicate
    const nameParts = notebook.name.split(".")
    const ext = nameParts.pop()
    const baseName = nameParts.join(".")
    const newName = `${baseName}_copy.${ext}`

    const duplicatedNotebook: NotebookItem = {
      ...notebook,
      name: newName,
      path: `/notebooks/${newName}`,
      last_modified: "Just now",
    }

    setNotebooks([duplicatedNotebook, ...notebooks])
  }

  const handleUploadNotebook = () => {
    // In production, this would open a file picker and upload to /api/notebooks/upload
    const input = document.createElement("input")
    input.type = "file"
    input.accept = ".ipynb"
    input.onchange = (e: any) => {
      const file = e.target.files[0]
      if (file) {
        const newNotebook: NotebookItem = {
          name: file.name,
          path: `/notebooks/${file.name}`,
          last_modified: "Just now",
          size: `${Math.round(file.size / 1024)} KB`,
          type: "notebook",
          kernel: "Python 3",
        }
        setNotebooks([newNotebook, ...notebooks])
      }
    }
    input.click()
  }

  const recentNotebooks = filteredNotebooks.slice(0, 10)

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

      {/* Status Alert */}
      {jupyterStatus === "unhealthy" && (
        <Alert variant="destructive">
          <Info className="h-4 w-4" />
          <AlertDescription>
            JupyterLab is currently unavailable. Please check the service status in the Dashboard.
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
            <div className="text-lg font-bold">
              {notebooks.length > 0 ? notebooks[0].last_modified : "N/A"}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="recent" className="space-y-4">
        <div className="flex items-center justify-between">
          <TabsList>
            <TabsTrigger value="recent">Recent</TabsTrigger>
            <TabsTrigger value="all">All Notebooks</TabsTrigger>
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
            <div className={viewMode === "grid" ? "grid gap-4 md:grid-cols-2 lg:grid-cols-3" : "space-y-2"}>
              {recentNotebooks.map((notebook) => (
                <NotebookCard
                  key={notebook.path}
                  notebook={notebook}
                  onOpen={openNotebook}
                  onDelete={(nb) => {
                    setNotebookToDelete(nb)
                    setShowDeleteDialog(true)
                  }}
                  onDuplicate={handleDuplicateNotebook}
                />
              ))}
            </div>
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
                  onDelete={(nb) => {
                    setNotebookToDelete(nb)
                    setShowDeleteDialog(true)
                  }}
                  onDuplicate={handleDuplicateNotebook}
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

      {/* Jupyter Embed Dialog */}
      <JupyterEmbed
        notebook={selectedNotebook}
        open={showJupyter}
        onClose={() => {
          setShowJupyter(false)
          setSelectedNotebook(null)
        }}
      />

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
            <Button onClick={handleCreateNotebook} disabled={!newNotebookName.trim()}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Notebook</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete "{notebookToDelete?.name}"? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setShowDeleteDialog(false)
                setNotebookToDelete(null)
              }}
            >
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteNotebook}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
