"use client"

import { useEffect, useState, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import {
  FileCode,
  ExternalLink,
  Download,
  Edit,
  ArrowLeft,
  AlertCircle,
} from "lucide-react"
import Link from "next/link"

interface NotebookCell {
  cell_type: "code" | "markdown" | "raw"
  source: string[]
  outputs?: any[]
  execution_count?: number
}

interface NotebookData {
  cells: NotebookCell[]
  metadata: {
    kernelspec?: {
      display_name: string
      language: string
      name: string
    }
  }
}

function NotebookViewer() {
  const searchParams = useSearchParams()
  const path = searchParams.get("path")
  const [notebook, setNotebook] = useState<NotebookData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (path) {
      fetchNotebook(path)
    }
  }, [path])

  const fetchNotebook = async (notebookPath: string) => {
    try {
      setLoading(true)
      setError(null)

      // In production, this would fetch from /api/notebooks/content?path={path}
      // For now, show a mock notebook structure
      const mockNotebook: NotebookData = {
        cells: [
          {
            cell_type: "markdown",
            source: ["# Data Exploration\n", "\n", "This notebook demonstrates data exploration using DuckDB and Iceberg tables."],
          },
          {
            cell_type: "code",
            source: ["import duckdb\n", "import pandas as pd\n", "\n", "# Connect to DuckDB\n", "conn = duckdb.connect()"],
            execution_count: 1,
            outputs: [],
          },
          {
            cell_type: "code",
            source: [
              "# Query Iceberg table\n",
              "query = \"\"\"\n",
              "SELECT *\n",
              "FROM iceberg_scan('s3://datapond/warehouse/db.table')\n",
              "LIMIT 10\n",
              "\"\"\"\n",
              "df = conn.execute(query).df()\n",
              "df.head()",
            ],
            execution_count: 2,
            outputs: [
              {
                output_type: "execute_result",
                data: {
                  "text/plain": ["   col1  col2  col3\n", "0     1     A    10\n", "1     2     B    20\n", "..."],
                },
              },
            ],
          },
          {
            cell_type: "markdown",
            source: ["## Visualization\n", "\n", "Let's create some plots to visualize the data."],
          },
          {
            cell_type: "code",
            source: [
              "import matplotlib.pyplot as plt\n",
              "\n",
              "# Create a simple plot\n",
              "plt.figure(figsize=(10, 6))\n",
              "plt.plot(df['col1'], df['col3'])\n",
              "plt.xlabel('Column 1')\n",
              "plt.ylabel('Column 3')\n",
              "plt.title('Sample Visualization')\n",
              "plt.show()",
            ],
            execution_count: 3,
            outputs: [
              {
                output_type: "display_data",
                data: {
                  "text/plain": ["<Figure size 1000x600 with 1 Axes>"],
                },
              },
            ],
          },
        ],
        metadata: {
          kernelspec: {
            display_name: "Python 3 (ipykernel)",
            language: "python",
            name: "python3",
          },
        },
      }

      setNotebook(mockNotebook)
    } catch (err) {
      setError("Failed to load notebook")
      console.error("Error fetching notebook:", err)
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = () => {
    // In production, download the .ipynb file
    const link = document.createElement("a")
    link.href = `/api/notebooks/download?path=${encodeURIComponent(path || "")}`
    link.download = path?.split("/").pop() || "notebook.ipynb"
    link.click()
  }

  const handleEdit = () => {
    // Open in JupyterLab
    window.open(`http://datapond.local/jupyter/lab/tree${path}?token=jupyter`, "_blank")
  }

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Skeleton className="h-5 w-[300px]" />
        <Skeleton className="h-10 w-[200px]" />
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-[200px]" />
          ))}
        </div>
      </div>
    )
  }

  if (error || !notebook) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink href="/dashboard">Home</BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbLink href="/notebooks">Notebooks</BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>View</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {error || "Notebook not found"}
          </AlertDescription>
        </Alert>

        <Link href="/notebooks">
          <Button>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Notebooks
          </Button>
        </Link>
      </div>
    )
  }

  const notebookName = path?.split("/").pop() || "Untitled"
  const kernelName = notebook.metadata.kernelspec?.display_name || "Unknown"

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
            <BreadcrumbLink href="/notebooks">Notebooks</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{notebookName}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/notebooks">
            <Button variant="ghost" size="icon-sm">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h2 className="text-3xl font-bold tracking-tight">{notebookName}</h2>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant="secondary">{kernelName}</Badge>
              <span className="text-sm text-muted-foreground">{path}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleDownload}>
            <Download className="mr-2 h-4 w-4" />
            Download
          </Button>
          <Button variant="outline" size="sm" onClick={handleEdit}>
            <Edit className="mr-2 h-4 w-4" />
            Edit in JupyterLab
          </Button>
        </div>
      </div>

      {/* Notebook Cells */}
      <div className="space-y-4">
        {notebook.cells.map((cell, idx) => (
          <Card key={idx}>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge variant={cell.cell_type === "code" ? "default" : "secondary"}>
                    {cell.cell_type}
                  </Badge>
                  {cell.cell_type === "code" && cell.execution_count && (
                    <span className="text-xs text-muted-foreground">
                      [{cell.execution_count}]
                    </span>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {cell.cell_type === "markdown" ? (
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  {cell.source.map((line, lineIdx) => (
                    <p key={lineIdx}>{line}</p>
                  ))}
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Code input */}
                  <pre className="bg-muted p-4 rounded-lg overflow-x-auto">
                    <code className="text-sm">
                      {cell.source.join("")}
                    </code>
                  </pre>

                  {/* Code output */}
                  {cell.outputs && cell.outputs.length > 0 && (
                    <div className="border-l-4 border-green-500 pl-4">
                      <div className="text-xs text-muted-foreground mb-2">Output:</div>
                      {cell.outputs.map((output, outputIdx) => (
                        <pre key={outputIdx} className="bg-muted/50 p-4 rounded-lg overflow-x-auto">
                          <code className="text-sm">
                            {output.data?.["text/plain"]?.join("") || JSON.stringify(output, null, 2)}
                          </code>
                        </pre>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Export Options */}
      <Card>
        <CardHeader>
          <CardTitle>Export Options</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <Button variant="outline" size="sm">
              <Download className="mr-2 h-4 w-4" />
              Export as HTML
            </Button>
            <Button variant="outline" size="sm">
              <Download className="mr-2 h-4 w-4" />
              Export as PDF
            </Button>
            <Button variant="outline" size="sm">
              <Download className="mr-2 h-4 w-4" />
              Export as Python Script
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default function NotebookViewPage() {
  return (
    <Suspense fallback={
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Skeleton className="h-5 w-[300px]" />
        <Skeleton className="h-10 w-[200px]" />
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-[200px]" />
          ))}
        </div>
      </div>
    }>
      <NotebookViewer />
    </Suspense>
  )
}
