"use client"

import { useState, useEffect, useRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  Search,
  Download,
  Trash2,
  Play,
  Pause,
  WrapText,
  Hash,
} from "lucide-react"

interface LogsViewerProps {
  logs: string[]
  isStreaming: boolean
  onToggleStream: (streaming: boolean) => void
}

type LogLevel = "all" | "error" | "warn" | "info"

export function LogsViewer({
  logs,
  isStreaming,
  onToggleStream,
}: LogsViewerProps) {
  const [searchTerm, setSearchTerm] = useState("")
  const [logLevel, setLogLevel] = useState<LogLevel>("all")
  const [autoScroll, setAutoScroll] = useState(true)
  const [showLineNumbers, setShowLineNumbers] = useState(true)
  const [wrapLines, setWrapLines] = useState(false)
  const logsEndRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when logs update
  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [logs, autoScroll])

  // Detect log level from log line
  const detectLogLevel = (log: string): LogLevel => {
    const lowerLog = log.toLowerCase()
    if (lowerLog.includes("error") || lowerLog.includes("fatal")) return "error"
    if (lowerLog.includes("warn") || lowerLog.includes("warning")) return "warn"
    return "info"
  }

  // Get color class based on log level
  const getLogColor = (log: string) => {
    const level = detectLogLevel(log)
    switch (level) {
      case "error":
        return "text-red-400"
      case "warn":
        return "text-yellow-400"
      default:
        return "text-slate-300"
    }
  }

  // Filter logs based on search and level
  const filteredLogs = logs.filter((log) => {
    const matchesSearch = searchTerm
      ? log.toLowerCase().includes(searchTerm.toLowerCase())
      : true
    const matchesLevel =
      logLevel === "all" ? true : detectLogLevel(log) === logLevel
    return matchesSearch && matchesLevel
  })

  // Highlight search term in log
  const highlightSearch = (log: string) => {
    if (!searchTerm) return log

    const parts = log.split(new RegExp(`(${searchTerm})`, "gi"))
    return parts.map((part, i) =>
      part.toLowerCase() === searchTerm.toLowerCase() ? (
        <span key={i} className="bg-yellow-500 text-black">
          {part}
        </span>
      ) : (
        part
      )
    )
  }

  // Download logs as text file
  const downloadLogs = () => {
    const content = logs.join("\n")
    const blob = new Blob([content], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `service-logs-${new Date().toISOString()}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // Handle scroll to toggle auto-scroll
  const handleScroll = () => {
    if (!containerRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50
    setAutoScroll(isAtBottom)
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <CardTitle className="flex items-center gap-2">
            Logs
            <Badge variant="secondary">{filteredLogs.length}</Badge>
          </CardTitle>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                type="text"
                placeholder="Search logs..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-8 w-[200px]"
              />
            </div>

            {/* Log level filter */}
            <div className="flex gap-1">
              {(["all", "error", "warn", "info"] as LogLevel[]).map((level) => (
                <Button
                  key={level}
                  variant={logLevel === level ? "default" : "outline"}
                  size="xs"
                  onClick={() => setLogLevel(level)}
                >
                  {level.toUpperCase()}
                </Button>
              ))}
            </div>

            {/* Controls */}
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => setShowLineNumbers(!showLineNumbers)}
              title={showLineNumbers ? "Hide line numbers" : "Show line numbers"}
            >
              <Hash className="h-4 w-4" />
            </Button>

            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => setWrapLines(!wrapLines)}
              title={wrapLines ? "Disable word wrap" : "Enable word wrap"}
            >
              <WrapText className="h-4 w-4" />
            </Button>

            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => onToggleStream(!isStreaming)}
              title={isStreaming ? "Pause streaming" : "Start streaming"}
            >
              {isStreaming ? (
                <Pause className="h-4 w-4" />
              ) : (
                <Play className="h-4 w-4" />
              )}
            </Button>

            <Button
              variant="outline"
              size="icon-sm"
              onClick={downloadLogs}
              title="Download logs"
            >
              <Download className="h-4 w-4" />
            </Button>

            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => {
                // Parent should handle clearing logs
              }}
              title="Clear logs"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="max-h-[500px] overflow-auto font-mono text-xs bg-slate-950 text-slate-50 p-4 rounded-lg"
        >
          {filteredLogs.length > 0 ? (
            filteredLogs.map((log, idx) => (
              <div
                key={idx}
                className={`py-0.5 ${wrapLines ? "break-words" : "whitespace-pre"}`}
              >
                {showLineNumbers && (
                  <span className="text-slate-500 select-none mr-4 inline-block w-12 text-right">
                    {idx + 1}
                  </span>
                )}
                <span className={getLogColor(log)}>{highlightSearch(log)}</span>
              </div>
            ))
          ) : (
            <div className="text-slate-400 text-center py-8">
              {logs.length === 0
                ? "No logs available. Logs will appear here when the service generates output."
                : "No logs match your search criteria."}
            </div>
          )}
          <div ref={logsEndRef} />
        </div>

        {!autoScroll && (
          <div className="mt-2 text-center">
            <Button
              variant="outline"
              size="xs"
              onClick={() => {
                setAutoScroll(true)
                logsEndRef.current?.scrollIntoView({ behavior: "smooth" })
              }}
            >
              Scroll to bottom
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
