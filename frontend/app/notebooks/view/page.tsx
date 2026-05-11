"use client"

import { useEffect, useState, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  Breadcrumb, BreadcrumbItem, BreadcrumbLink,
  BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { FileCode, ExternalLink, Download, Edit, ArrowLeft, AlertCircle } from "lucide-react"
import Link from "next/link"
import { serviceUrls } from "@/lib/urls"

interface NotebookCell {
  cell_type: "code" | "markdown" | "raw"
  source: string | string[]
  outputs?: any[]
  execution_count?: number | null
  id?: string
}

interface NotebookData {
  cells: NotebookCell[]
  metadata: {
    kernelspec?: { display_name: string; language: string; name: string }
  }
}

function cellSource(cell: NotebookCell): string {
  return Array.isArray(cell.source) ? cell.source.join("") : (cell.source ?? "")
}

function renderOutput(output: any): string {
  if (output.output_type === "stream") {
    return Array.isArray(output.text) ? output.text.join("") : (output.text ?? "")
  }
  if (output.data) {
    if (output.data["text/plain"]) {
      return Array.isArray(output.data["text/plain"])
        ? output.data["text/plain"].join("")
        : output.data["text/plain"]
    }
  }
  if (output.ename) {
    return `${output.ename}: ${output.evalue}`
  }
  return JSON.stringify(output, null, 2)
}

function MarkdownCell({ source }: { source: string }) {
  // Simple markdown rendering: headers, bold, code, lists
  const lines = source.split("\n")
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none px-1">
      {lines.map((line, i) => {
        if (line.startsWith("### ")) return <h3 key={i} className="text-base font-semibold mt-3 mb-1">{line.slice(4)}</h3>
        if (line.startsWith("## "))  return <h2 key={i} className="text-lg font-bold mt-4 mb-1">{line.slice(3)}</h2>
        if (line.startsWith("# "))   return <h1 key={i} className="text-xl font-bold mt-4 mb-2">{line.slice(2)}</h1>
        if (line.startsWith("- ") || line.startsWith("* ")) {
          return <li key={i} className="ml-4 text-sm list-disc">{line.slice(2)}</li>
        }
        if (line.trim() === "") return <div key={i} className="h-2" />
        // Inline code
        const parts = line.split(/(`[^`]+`)/)
        return (
          <p key={i} className="text-sm leading-relaxed">
            {parts.map((part, j) =>
              part.startsWith("`") && part.endsWith("`")
                ? <code key={j} className="bg-muted px-1 py-0.5 rounded text-xs font-mono">{part.slice(1, -1)}</code>
                : part
            )}
          </p>
        )
      })}
    </div>
  )
}

function NotebookViewer() {
  const searchParams = useSearchParams()
  const path = searchParams.get("path")
  const [notebook, setNotebook] = useState<NotebookData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (path) fetchNotebook(path)
  }, [path])

  const fetchNotebook = async (notebookPath: string) => {
    try {
      setLoading(true)
      setError(null)

      const res = await fetch(`/api/notebooks/${encodeURIComponent(notebookPath)}`)
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()

      // NotebookContent schema: {path, name, content: {cells, metadata, ...}}
      const nbContent = data.content ?? data
      if (!nbContent?.cells) throw new Error("Invalid notebook format")

      setNotebook({ cells: nbContent.cells, metadata: nbContent.metadata ?? {} })
    } catch (err: any) {
      setError(err.message || "Failed to load notebook")
    } finally {
      setLoading(false)
    }
  }

  const handleEdit = () => {
    window.open(`${serviceUrls.jupyter()}/lab/tree/${path}`, "_blank")
  }

  if (loading) {
    return (
      <div className="flex-1 space-y-4 px-6 py-5">
        <Skeleton className="h-4 w-64" />
        <Skeleton className="h-8 w-48" />
        {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-40" />)}
      </div>
    )
  }

  if (error || !notebook) {
    return (
      <div className="flex-1 space-y-4 px-6 py-5">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem><BreadcrumbLink href="/notebooks">Notebooks</BreadcrumbLink></BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error || "Notebook not found"}</AlertDescription>
        </Alert>
        <Link href="/notebooks"><Button variant="outline" size="sm" className="gap-1.5"><ArrowLeft className="h-3.5 w-3.5" />Back</Button></Link>
      </div>
    )
  }

  const notebookName = path?.split("/").pop() || "Untitled"
  const kernelName = notebook.metadata.kernelspec?.display_name || "Python 3"
  const codeCount = notebook.cells.filter(c => c.cell_type === "code").length

  return (
    <div className="flex-1 space-y-4 px-6 py-5">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/notebooks">Notebooks</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>{notebookName}</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/notebooks">
            <Button variant="ghost" size="sm" className="h-7 w-7 p-0">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h2 className="text-xl font-bold">{notebookName}</h2>
            <div className="flex items-center gap-2 mt-0.5">
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0">{kernelName}</Badge>
              <span className="text-xs text-muted-foreground">{notebook.cells.length} cells · {codeCount} code</span>
              {path && <span className="text-xs text-muted-foreground font-mono">{path}</span>}
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="h-7 text-xs gap-1.5" onClick={handleEdit}>
            <Edit className="h-3.5 w-3.5" />Edit in JupyterLab
          </Button>
          <Button variant="outline" size="sm" className="h-7 text-xs gap-1.5"
            onClick={() => window.open(serviceUrls.jupyter(), "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />Open JupyterLab
          </Button>
        </div>
      </div>

      {/* Cells */}
      <div className="space-y-3">
        {notebook.cells.map((cell, idx) => {
          const src = cellSource(cell)
          if (!src.trim() && cell.cell_type !== "code") return null

          return (
            <Card key={cell.id ?? idx} className="overflow-hidden">
              {/* Cell header */}
              <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/30 border-b">
                <Badge
                  variant={cell.cell_type === "code" ? "default" : "secondary"}
                  className="text-[10px] px-1.5 py-0 h-4"
                >
                  {cell.cell_type}
                </Badge>
                {cell.cell_type === "code" && (
                  <span className="text-[10px] text-muted-foreground font-mono">
                    In [{cell.execution_count ?? " "}]
                  </span>
                )}
              </div>

              <CardContent className="p-0">
                {cell.cell_type === "markdown" ? (
                  <div className="px-4 py-3">
                    <MarkdownCell source={src} />
                  </div>
                ) : (
                  <div>
                    {/* Source */}
                    <pre className="px-4 py-3 overflow-x-auto bg-[#1e1e2e] text-[#cdd6f4] text-xs leading-relaxed font-mono">
                      <code>{src}</code>
                    </pre>

                    {/* Outputs */}
                    {cell.outputs && cell.outputs.length > 0 && (
                      <div className="border-t">
                        {cell.outputs.map((output, oi) => {
                          const isError = output.output_type === "error"
                          const isImage = output.data?.["image/png"]

                          if (isImage) {
                            return (
                              <div key={oi} className="p-3">
                                <img
                                  src={`data:image/png;base64,${output.data["image/png"]}`}
                                  alt="output"
                                  className="max-w-full rounded"
                                />
                              </div>
                            )
                          }

                          return (
                            <pre key={oi} className={`px-4 py-2 text-xs font-mono overflow-x-auto ${
                              isError ? "bg-destructive/10 text-destructive" : "bg-muted/30 text-muted-foreground"
                            }`}>
                              {renderOutput(output)}
                            </pre>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

export default function NotebookViewPage() {
  return (
    <Suspense fallback={
      <div className="flex-1 space-y-4 px-6 py-5">
        {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-40" />)}
      </div>
    }>
      <NotebookViewer />
    </Suspense>
  )
}
