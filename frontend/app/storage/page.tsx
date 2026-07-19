"use client"

import { useCallback, useEffect, useState } from "react"
import { useToast } from "@/lib/toast"
import { ErrorBox } from "@/components/ui/error-box"
import { useConfirm } from "@/lib/confirm"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import {
  HardDrive, Database, RefreshCw, Plus, Trash2, FolderOpen,
  FileText, ChevronRight, ChevronLeft, Package,
} from "lucide-react"
import { formatDistanceToNow } from "date-fns"

interface BucketStat {
  name: string
  created_at: string | null
  object_count: number
  total_size_bytes: number
  total_size_human: string
}

interface StorageOverview {
  endpoint: string
  bucket_count: number
  total_object_count: number
  total_size_bytes: number
  total_size_human: string
  buckets: BucketStat[]
}

interface S3Object {
  bucket: string
  key: string
  size_bytes: number
  size_human: string
  last_modified: string
  content_type?: string
}

function sizeBar(bytes: number, total: number) {
  const pct = total > 0 ? Math.min((bytes / total) * 100, 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
        <div className="h-full bg-primary/60 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[11px] text-muted-foreground w-10 text-right tabular-nums">
        {pct.toFixed(0)}%
      </span>
    </div>
  )
}

export default function StoragePage() {
  const [overview, setOverview] = useState<StorageOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedBucket, setSelectedBucket] = useState<string | null>(null)
  const [objects, setObjects] = useState<S3Object[]>([])
  const [objectsLoading, setObjectsLoading] = useState(false)
  const [objectsError, setObjectsError] = useState<string | null>(null)
  const [newBucketName, setNewBucketName] = useState("")
  const [creating, setCreating] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const loadOverview = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch("/api/storage/overview")
      if (!res.ok) throw new Error(`${res.status}`)
      setOverview(await res.json())
    } catch (e) {
      setOverview(null)
      setError(e instanceof Error ? `Failed to load storage overview (HTTP ${e.message})` : "Failed to load storage overview")
    } finally {
      setLoading(false)
    }
  }, [])

  const loadObjects = async (bucket: string) => {
    setObjectsLoading(true)
    setObjects([])
    setObjectsError(null)
    try {
      const res = await fetch(`/api/storage/buckets/${encodeURIComponent(bucket)}/objects?limit=100`)
      if (!res.ok) throw new Error(`${res.status}`)
      setObjects(await res.json())
    } catch (requestError) {
      setObjects([])
      setObjectsError(requestError instanceof Error ? `Failed to load objects (HTTP ${requestError.message})` : "Failed to load objects")
    } finally {
      setObjectsLoading(false)
    }
  }

  const handleSelectBucket = (name: string) => {
    setSelectedBucket(name)
    loadObjects(name)
  }

  const handleCreateBucket = async () => {
    if (!newBucketName.trim()) return
    setCreating(true)
    setActionError(null)
    try {
      const res = await fetch(`/api/storage/buckets/${encodeURIComponent(newBucketName.trim())}`, {
        method: "POST",
      })
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || "Failed to create bucket")
      }
      toast(`Bucket "${newBucketName.trim()}" created`, "success")
      setNewBucketName("")
      await loadOverview()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed")
    } finally {
      setCreating(false)
    }
  }

  const { toast } = useToast()
  const confirm = useConfirm()
  const handleDeleteBucket = async (name: string) => {
    if (!(await confirm({ title: "Delete bucket", message: `This deletes the "${name}" bucket. This cannot be undone.`, destructive: true, confirmText: "Delete" }))) return
    setActionError(null)
    try {
      const res = await fetch(`/api/storage/buckets/${encodeURIComponent(name)}`, { method: "DELETE" })
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || "Failed to delete")
      }
      if (selectedBucket === name) setSelectedBucket(null)
      toast(`Bucket "${name}" deleted`, "success")
      await loadOverview()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed")
    }
  }

  useEffect(() => {
    const initial = window.setTimeout(() => void loadOverview(), 0)
    return () => window.clearTimeout(initial)
  }, [loadOverview])

  // Native S3 buckets are provisioned by the cloud account/Terraform, so lifecycle
  // mutations fail closed. S3-compatible profiles retain in-app bucket management.
  const bucketLifecycleManaged = !overview || overview.endpoint === "aws-native"
  const storageLabel = !overview
    ? "Object storage"
    : overview.endpoint === "aws-native"
      ? "Amazon S3"
      : "S3-compatible storage"

  return (
    <div className="flex-1 space-y-5 px-6 py-5">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Object Storage</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            {storageLabel} through the S3 API
          </p>
        </div>
        <Button variant="outline" size="sm" className="gap-1.5 h-8 text-xs"
          onClick={loadOverview} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Error */}
      {error && <div role="alert" aria-live="polite"><ErrorBox msg={error} /></div>}

      {/* Stats strip: failed requests never fall through to fabricated zero values. */}
      {(loading || overview) && <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Endpoint",       value: loading ? null : storageLabel,       sub: overview?.endpoint ?? "", icon: HardDrive },
          { label: "Buckets",        value: loading ? null : overview?.bucket_count ?? 0, sub: "Total buckets", icon: Database },
          { label: "Total Objects",  value: loading ? null : (overview?.total_object_count ?? 0).toLocaleString(), sub: "Objects stored", icon: FileText },
          { label: "Total Size",     value: loading ? null : (overview?.total_size_human ?? "0 B"), sub: "Storage used", icon: Package },
        ].map(({ label, value, sub, icon: Icon }) => (
          <Card key={label}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-muted-foreground">{label}</span>
                <Icon className="h-3.5 w-3.5 text-muted-foreground" />
              </div>
              {loading
                ? <Skeleton className="h-6 w-20 mt-1" />
                : <div className="text-xl font-bold truncate">{value}</div>
              }
              <div className="text-[11px] text-muted-foreground mt-0.5 truncate">{sub}</div>
            </CardContent>
          </Card>
        ))}
      </div>}

      {/* Main content is rendered only after a successful overview response. */}
      {overview && <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-5">

        {/* Left: Bucket list */}
        <div className="space-y-3">
          {/* Create bucket — hidden when bucket lifecycle is managed by the AWS account/Terraform */}
          {bucketLifecycleManaged ? (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">New Bucket</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-[11px] text-muted-foreground">
                  Bucket lifecycle is managed by your AWS account/Terraform on this profile — create buckets there.
                </p>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">New Bucket</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex gap-2">
                  <Input
                    value={newBucketName}
                    onChange={e => setNewBucketName(e.target.value.toLowerCase().replace(/[^a-z0-9\-]/g, ""))}
                    className="h-8 text-sm font-mono"
                    placeholder="my-bucket"
                    onKeyDown={e => e.key === "Enter" && handleCreateBucket()}
                  />
                  <Button size="sm" className="h-8 shrink-0 gap-1"
                    onClick={handleCreateBucket}
                    disabled={creating || !newBucketName.trim()}>
                    {creating ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                  </Button>
                </div>
                {actionError && <div role="alert" aria-live="polite"><ErrorBox msg={actionError} /></div>}
                <p className="text-[11px] text-muted-foreground">
                  Lowercase letters, numbers, and hyphens only
                </p>
              </CardContent>
            </Card>
          )}

          {/* Bucket list */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center justify-between">
                Buckets
                {overview && (
                  <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                    {overview.bucket_count}
                  </Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {loading ? (
                <div className="p-4 space-y-2">
                  {Array(3).fill(0).map((_, i) => <Skeleton key={i} className="h-14 w-full" />)}
                </div>
              ) : !overview || overview.buckets.length === 0 ? (
                <div className="flex flex-col items-center py-10 text-center px-4">
                  <Database className="h-8 w-8 text-muted-foreground/30 mb-2" />
                  <p className="text-sm text-muted-foreground">No buckets yet</p>
                  <p className="text-xs text-muted-foreground/60 mt-1">
                    {bucketLifecycleManaged
                      ? "Create a bucket in your AWS account/Terraform, then refresh"
                      : "Create your first bucket above"}
                  </p>
                </div>
              ) : (
                <div className="divide-y">
                  {overview.buckets.map(b => (
                    <div
                      key={b.name}
                      className={`group flex items-stretch transition-colors hover:bg-muted/50
                        ${selectedBucket === b.name ? "bg-muted/60" : ""}`}
                    >
                      <button
                        type="button"
                        onClick={() => handleSelectBucket(b.name)}
                        className="flex min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left"
                        aria-pressed={selectedBucket === b.name}
                      >
                        <FolderOpen className={`h-4 w-4 shrink-0 ${
                          selectedBucket === b.name ? "text-primary" : "text-muted-foreground"
                        }`} />
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="flex items-center justify-between gap-2">
                            <span className="truncate text-sm font-medium">{b.name}</span>
                            <span className="shrink-0 text-[11px] text-muted-foreground">
                              {b.total_size_human}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                            <span>{b.object_count.toLocaleString()} objects</span>
                            {b.created_at && (
                              <span>
                                {formatDistanceToNow(new Date(b.created_at), { addSuffix: true })}
                              </span>
                            )}
                          </div>
                          {overview.total_size_bytes > 0 && sizeBar(b.total_size_bytes, overview.total_size_bytes)}
                        </div>
                        <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-muted-foreground/50
                          ${selectedBucket === b.name ? "text-primary" : ""}`} />
                      </button>
                      {!bucketLifecycleManaged && (
                        <button
                          type="button"
                          onClick={() => handleDeleteBucket(b.name)}
                          className="mr-2 self-center rounded p-2 text-muted-foreground opacity-0 transition-opacity hover:text-destructive focus:opacity-100 group-hover:opacity-100"
                          aria-label={`Delete bucket ${b.name}`}
                          title={`Delete bucket ${b.name}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right: Object browser */}
        <Card className="flex flex-col overflow-hidden">
          <CardHeader className="pb-3 shrink-0">
            <div className="flex items-center gap-2">
              {selectedBucket && (
                <Button variant="ghost" size="icon" className="h-7 w-7"
                  onClick={() => setSelectedBucket(null)}>
                  <ChevronLeft className="h-3.5 w-3.5" />
                </Button>
              )}
              <div>
                <CardTitle className="text-sm">
                  {selectedBucket ? (
                    <span className="flex items-center gap-1.5">
                      <FolderOpen className="h-4 w-4 text-primary" />
                      {selectedBucket}
                    </span>
                  ) : "Object Browser"}
                </CardTitle>
                {selectedBucket && (
                  <CardDescription className="text-[11px] mt-0.5">
                    {objectsLoading ? "Loading..." : `${objects.length} objects`}
                  </CardDescription>
                )}
              </div>
            </div>
          </CardHeader>

          <CardContent className="flex-1 overflow-auto p-0">
            {!selectedBucket ? (
              <div className="flex flex-col items-center justify-center h-48 text-center px-4">
                <FolderOpen className="h-10 w-10 text-muted-foreground/20 mb-3" />
                <p className="text-sm text-muted-foreground">Select a bucket to view its objects</p>
              </div>
            ) : objectsLoading ? (
              <div className="p-4 space-y-2">
                {Array(5).fill(0).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
              </div>
            ) : objectsError ? (
              <div className="p-4" role="alert" aria-live="polite">
                <ErrorBox
                  msg={objectsError}
                  action={<Button size="sm" variant="outline" onClick={() => loadObjects(selectedBucket)}>Retry</Button>}
                />
              </div>
            ) : objects.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-center px-4">
                <FileText className="h-8 w-8 text-muted-foreground/20 mb-2" />
                <p className="text-sm text-muted-foreground">This bucket is empty</p>
              </div>
            ) : (
              <Table>
                <TableHeader className="sticky top-0 bg-muted/60 backdrop-blur-sm">
                  <TableRow>
                    <TableHead className="text-xs">Key</TableHead>
                    <TableHead className="text-xs text-right w-24">Size</TableHead>
                    <TableHead className="text-xs w-40">Last Modified</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {objects.map(obj => (
                    <TableRow key={obj.key} className="hover:bg-muted/30">
                      <TableCell className="text-xs font-mono truncate max-w-[400px]" title={obj.key}>
                        <span className="flex items-center gap-1.5">
                          <FileText className="h-3 w-3 text-muted-foreground shrink-0" />
                          {obj.key}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs text-right tabular-nums text-muted-foreground">
                        {obj.size_human}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDistanceToNow(new Date(obj.last_modified), { addSuffix: true })}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>}
    </div>
  )
}
