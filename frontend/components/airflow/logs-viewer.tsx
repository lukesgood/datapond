"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Download,
  RefreshCw,
  Search,
  X,
} from "lucide-react"

interface LogsViewerProps {
  taskId: string
  dagId: string
  runId: string
  tryNumber?: number
  isOpen: boolean
  onClose: () => void
  autoRefresh?: boolean
}

export function LogsViewer({
  taskId,
  dagId,
  runId,
  tryNumber = 1,
  isOpen,
  onClose,
  autoRefresh = false,
}: LogsViewerProps) {
  const [logs, setLogs] = useState<string>("")
  const [loading, setLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState("")
  const [filteredLogs, setFilteredLogs] = useState<string>("")

  const fetchLogs = async () => {
    setLoading(true)
    try {
      const response = await fetch(
        `/api/airflow/tasks/${taskId}/logs?dag_id=${dagId}&run_id=${runId}&try_number=${tryNumber}`
      )
      const data = await response.json()
      setLogs(data.content || "No logs available")
    } catch (error) {
      console.error("Failed to fetch logs:", error)
      setLogs("Failed to load logs")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isOpen) {
      fetchLogs()
    }
  }, [isOpen, taskId, dagId, runId, tryNumber])

  useEffect(() => {
    if (autoRefresh && isOpen) {
      const interval = setInterval(fetchLogs, 5000)
      return () => clearInterval(interval)
    }
  }, [autoRefresh, isOpen])

  useEffect(() => {
    if (searchTerm) {
      const lines = logs.split("\n")
      const filtered = lines.filter((line) =>
        line.toLowerCase().includes(searchTerm.toLowerCase())
      )
      setFilteredLogs(filtered.join("\n"))
    } else {
      setFilteredLogs(logs)
    }
  }, [searchTerm, logs])

  const downloadLogs = () => {
    const blob = new Blob([logs], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${dagId}-${taskId}-${runId}-logs.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[80vh]">
        <DialogHeader>
          <DialogTitle>
            Task Logs: {taskId}
            <span className="text-sm text-muted-foreground ml-2">
              (Try {tryNumber})
            </span>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Controls */}
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search logs..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-9"
              />
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={fetchLogs}
              disabled={loading}
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
            <Button variant="outline" size="sm" onClick={downloadLogs}>
              <Download className="h-4 w-4" />
            </Button>
          </div>

          {/* Logs content */}
          <Card>
            <CardContent className="p-4">
              <pre className="text-xs font-mono bg-black text-green-400 p-4 rounded-lg overflow-auto max-h-[50vh] whitespace-pre-wrap break-words">
                {loading ? "Loading logs..." : filteredLogs || "No logs available"}
              </pre>
            </CardContent>
          </Card>

          {searchTerm && (
            <div className="text-sm text-muted-foreground">
              Showing {filteredLogs.split("\n").length} of {logs.split("\n").length} lines
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
