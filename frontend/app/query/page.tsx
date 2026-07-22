"use client"

import { useState, useRef, useCallback, useEffect, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Play, Save, History, Settings, ChevronRight, ChevronLeft,
  FlaskConical, Code2, Database, Trash2, AlignLeft,
  TableProperties, BarChart2, AlertCircle, FileCode,
  Sparkles, Loader2, X, Copy, Check,
} from "lucide-react"
import { Input } from "@/components/ui/input"
import dynamic from "next/dynamic"
import { SchemaTree } from "@/components/query/schema-tree"
import { QueryResults } from "@/components/query/query-results"
import { addToQueryHistory } from "@/components/query/query-history"
import { QueryHistorySidebar } from "@/components/query/query-history-sidebar"
import { ChartSelector } from "@/components/query/chart-selector"
import { ChartConfigPanel } from "@/components/query/chart-config-panel"
import type { ChartType } from "@/components/query/chart-renderer"

const SqlEditor = dynamic(() => import("@/components/query/sql-editor").then(m => ({ default: m.SqlEditor })), {
  ssr: false,
  loading: () => <div className="h-full flex items-center justify-center text-sm text-muted-foreground">Loading editor...</div>,
})
const ChartRenderer = dynamic(() => import("@/components/query/chart-renderer").then(m => ({ default: m.ChartRenderer })), { ssr: false })
const SaveDashboardModal = dynamic(() => import("@/components/query/save-dashboard-modal").then(m => ({ default: m.SaveDashboardModal })), { ssr: false })
const LogToMlflowModal = dynamic(() => import("@/components/query/log-to-mlflow-modal").then(m => ({ default: m.LogToMlflowModal })), { ssr: false })
const OpenInNotebookModal = dynamic(() => import("@/components/query/open-in-notebook-modal").then(m => ({ default: m.OpenInNotebookModal })), { ssr: false })
import { useToast } from "@/lib/toast"
import { useCapability, CapabilityGate } from "@/lib/capabilities"
import { AnalyticsTabs } from "@/components/query/analytics-tabs"
import { DashboardsGallery } from "@/components/dashboards/dashboards-gallery"

interface QueryResult {
  columns: string[]
  rows: unknown[][]
  execution_time_ms: number
  truncated?: boolean
}

type QueryStatus = "idle" | "running" | "success" | "error"
type RightPanel = "history" | "chart-config" | null

const DEFAULT_QUERY = "-- Write your SQL here\nSELECT 1 AS hello;"

function QueryPageInner() {
  const [query, setQuery]                   = useState(() => {
    if (typeof window === "undefined") return DEFAULT_QUERY
    const linkedSql = new URLSearchParams(window.location.search).get("sql")
    return linkedSql?.trim() ? linkedSql : DEFAULT_QUERY
  })
  const [queryStatus, setQueryStatus]       = useState<QueryStatus>("idle")
  const [results, setResults]               = useState<QueryResult | null>(null)
  // The exact editor text that produced `results` — lets us flag when the
  // editor has drifted from the shown result set (SQL ⇄ results legibility).
  const [executedQuery, setExecutedQuery]   = useState<string | null>(null)
  const [copied, setCopied]                 = useState(false)
  const [error, setError]                   = useState<string | null>(null)
  const [chartType, setChartType]           = useState<ChartType>("table")
  const [xAxis, setXAxis]                   = useState("")
  const [yAxis, setYAxis]                   = useState("")
  const [showGrid, setShowGrid]             = useState(true)
  const [showLegend, setShowLegend]         = useState(true)
  const [saveDashboardOpen, setSaveDashboardOpen] = useState(false)
  const [logToMlflowOpen, setLogToMlflowOpen]       = useState(false)
  const [openInNotebookOpen, setOpenInNotebookOpen] = useState(false)
  const [rightPanel, setRightPanel]         = useState<RightPanel>(null)
  const [schemaOpen, setSchemaOpen]         = useState(true)
  const [schemaWidth, setSchemaWidth]       = useState(224)
  const [editorHeight, setEditorHeight]     = useState(240)
  const [engineName, setEngineName]         = useState("Trino")
  const [engineStatus, setEngineStatus]     = useState<"healthy" | "unhealthy" | "unknown" | "managed">("unknown")

  // AI Assistant
  const [aiQuestion, setAiQuestion]         = useState("")
  const [aiLoading, setAiLoading]           = useState(false)
  const [aiExplanation, setAiExplanation]   = useState<string | null>(null)

  const isResizingSchema   = useRef(false)
  const isResizingEditor   = useRef(false)
  const { toast } = useToast()
  const notebooksEnabled = useCapability("notebooks")
  const experimentsEnabled = useCapability("experiments")

  // Fetch the active query engine + its status on mount
  useEffect(() => {
    fetch("/api/capabilities").then(r => r.ok ? r.json() : null).then(caps => {
      const eng = caps?.query_engine === "athena" ? "Athena" : "Trino"
      setEngineName(eng)
      const svcName = eng === "Athena" ? "Amazon Athena" : "trino"
      fetch("/api/services").then(r => r.json())
        .then((services: { name: string; status: string }[]) => {
          const svc = services.find(s => s.name === svcName)
          const status = svc?.status
          setEngineStatus(status === "healthy" || status === "unhealthy" || status === "managed" ? status : "unknown")
        })
        .catch(() => setEngineStatus("unknown"))
    }).catch(() => {})
  }, [])

  // ── Schema panel horizontal resize ──────────────────────────────────────────
  const startSchemaResize = (e: React.MouseEvent) => {
    e.preventDefault()
    isResizingSchema.current = true
    const startX = e.clientX
    const startW = schemaWidth
    const onMove = (ev: MouseEvent) => {
      if (!isResizingSchema.current) return
      setSchemaWidth(Math.min(480, Math.max(160, startW + ev.clientX - startX)))
    }
    const onUp = () => {
      isResizingSchema.current = false
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup", onUp)
    }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
  }

  // ── Editor/Results vertical resize ──────────────────────────────────────────
  const startEditorResize = (e: React.MouseEvent) => {
    e.preventDefault()
    isResizingEditor.current = true
    const startY = e.clientY
    const startH = editorHeight
    const onMove = (ev: MouseEvent) => {
      if (!isResizingEditor.current) return
      setEditorHeight(Math.min(600, Math.max(120, startH + ev.clientY - startY)))
    }
    const onUp = () => {
      isResizingEditor.current = false
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup", onUp)
    }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
  }

  // ── AI SQL generation ────────────────────────────────────────────────────────
  const handleAskAI = async () => {
    if (!aiQuestion.trim() || aiLoading) return
    setAiLoading(true)
    setAiExplanation(null)
    try {
      const res = await fetch("/api/ai/sql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: aiQuestion }),
      })
      if (!res.ok) throw new Error("AI request failed")
      const data = await res.json()
      setQuery(data.sql)
      setAiExplanation(data.explanation)
      if (!data.has_ai) {
        toast("Configure an AI provider in Settings → AI to enable AI SQL generation", "info")
      }
    } catch (error) {
      toast(error instanceof Error ? error.message : "AI request failed", "error")
    } finally {
      setAiLoading(false)
    }
  }

  // ── Query execution ──────────────────────────────────────────────────────────
  const executeQuery = useCallback(async () => {
    const stripped = query
      .split("\n")
      .filter(line => !line.trim().startsWith("--") && line.trim() !== "")
      .join("\n")
      .trim()
      .replace(/;+$/, "")
      .trim()
    if (!stripped) return

    setQueryStatus("running")
    setError(null)
    setResults(null)

    try {
      const response = await fetch("/api/queries/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: stripped }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || data.error || "Query execution failed")

      setResults(data)
      setExecutedQuery(query)
      setQueryStatus("success")
      addToQueryHistory(query)
      // Reset chart axes whenever the new result set's columns no longer
      // contain the currently-selected axis (e.g. a second query with
      // different columns) — otherwise Recharts silently renders empty.
      const cols: string[] = data.columns ?? []
      setXAxis(prev => (prev && cols.includes(prev)) ? prev : (cols[0] ?? ""))
      setYAxis(prev => (prev && cols.includes(prev)) ? prev : (cols[1] ?? ""))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
      setQueryStatus("error")
    }
  }, [query])

  // Global ⌘/Ctrl+Enter runs the query from anywhere on the page. Monaco owns
  // this binding while focused (it stops propagation), so skip when the editor
  // has focus to avoid a double execution.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        const el = document.activeElement as HTMLElement | null
        if (el?.closest(".monaco-editor")) return
        e.preventDefault()
        executeQuery()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [executeQuery])

  const copySql = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(query)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      toast("Couldn't copy to clipboard", "error")
    }
  }, [query, toast])

  const handleTableSelect = (catalog: string, schema: string, table: string) => {
    // 2-part name resolves under each engine's default catalog (Athena
    // AwsDataCatalog / Trino iceberg) — avoids a wrong hardcoded catalog prefix.
    setQuery(`SELECT *\nFROM ${schema}.${table}\nLIMIT 100;`)
  }

  const handleQuerySelect = (selectedQuery: string) => {
    setQuery(selectedQuery)
    setRightPanel(null)
    toast("Query loaded", "success")
  }

  const togglePanel = (panel: RightPanel) => {
    setRightPanel(prev => prev === panel ? null : panel)
  }

  const getChartData = () => {
    if (!results?.rows?.length) return []
    return results.rows.map(row => {
      const obj: Record<string, unknown> = {}
      results.columns.forEach((col, i) => { obj[col] = row[i] })
      return obj
    })
  }

  // Simple SQL formatter (basic prettify)
  const formatQuery = () => {
    const keywords = ["SELECT", "FROM", "WHERE", "JOIN", "LEFT JOIN", "RIGHT JOIN",
      "INNER JOIN", "GROUP BY", "ORDER BY", "HAVING", "LIMIT", "UNION", "WITH",
      "ON", "AND", "OR", "NOT", "IN", "AS", "DISTINCT", "COUNT", "SUM", "AVG",
      "MAX", "MIN", "CASE", "WHEN", "THEN", "ELSE", "END"]
    let formatted = query.replace(/\s+/g, " ").trim()
    keywords.forEach(kw => {
      formatted = formatted.replace(new RegExp(`\\b${kw}\\b`, "gi"), `\n${kw}`)
    })
    setQuery(formatted.trim())
  }

  const hasResults = results && results.rows.length > 0
  const isRunning  = queryStatus === "running"
  // Editor text has drifted from what produced the visible results.
  const resultsStale = !!results && executedQuery !== null && query.trim() !== executedQuery.trim()

  return (
    <div className="flex flex-col overflow-hidden bg-background" style={{ height: "calc(100vh - 56px)" }}>

      {/* ── Top app toolbar ─────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1.5 border-b px-3 h-11 shrink-0 bg-background">
        {/* Left: status */}
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <AnalyticsTabs active="editor" />
          <div className="h-4 w-px bg-border hidden sm:block" />
          {isRunning && (
            <Badge variant="secondary" className="text-xs gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse inline-block" />
              Executing...
            </Badge>
          )}
          {queryStatus === "success" && results && (
            <Badge className="dp-num text-xs text-white bg-[var(--dp-good)] hover:bg-[var(--dp-good)] gap-1">
              <TableProperties className="h-3 w-3" />
              {results.truncated ? "first " : ""}{results.rows.length.toLocaleString()} rows · {
                results.execution_time_ms < 1000
                  ? `${Math.round(results.execution_time_ms)}ms`
                  : `${(results.execution_time_ms / 1000).toFixed(2)}s`
              }
            </Badge>
          )}
          {queryStatus === "error" && (
            <Badge variant="destructive" className="text-xs gap-1">
              <AlertCircle className="h-3 w-3" />
              Error
            </Badge>
          )}
        </div>

        {/* Right: actions */}
        <div className="flex items-center gap-0.5 shrink-0">
          <Button
            variant="ghost" size="sm" className="h-8 text-xs gap-1.5"
            onClick={() => setSaveDashboardOpen(true)}
            disabled={!hasResults || isRunning}
            aria-label="Save as dashboard" title="Save as dashboard"
          >
            <Save className="h-3.5 w-3.5" />
            <span className="hidden md:inline">Save</span>
          </Button>

          {hasResults && notebooksEnabled && (
            <Button
              variant="ghost" size="sm" className="h-8 text-xs gap-1.5"
              onClick={() => setOpenInNotebookOpen(true)}
              aria-label="Open in Jupyter Notebook" title="Open in Jupyter Notebook"
            >
              <FileCode className="h-3.5 w-3.5" />
              <span className="hidden md:inline">Notebook</span>
            </Button>
          )}

          {hasResults && experimentsEnabled && (
            <Button
              variant="ghost" size="sm" className="h-8 text-xs gap-1.5"
              onClick={() => setLogToMlflowOpen(true)}
              aria-label="Log results to MLflow" title="Log results to MLflow"
            >
              <FlaskConical className="h-3.5 w-3.5" />
              <span className="hidden md:inline">Log</span>
            </Button>
          )}

          <div className="h-4 w-px bg-border mx-0.5" />

          <Button
            variant={rightPanel === "history" ? "secondary" : "ghost"}
            size="sm" className="h-8 text-xs gap-1.5"
            onClick={() => togglePanel("history")}
            aria-label="Query history" title="Query history"
          >
            <History className="h-3.5 w-3.5" />
            <span className="hidden md:inline">History</span>
          </Button>

          {hasResults && chartType !== "table" && (
            <Button
              variant={rightPanel === "chart-config" ? "secondary" : "ghost"}
              size="sm" className="h-8 text-xs gap-1.5"
              onClick={() => togglePanel("chart-config")}
              aria-label="Chart settings" title="Chart settings"
            >
              <Settings className="h-3.5 w-3.5" />
              <span className="hidden md:inline">Chart</span>
            </Button>
          )}

          <div className="h-4 w-px bg-border mx-0.5" />

          <Button
            onClick={executeQuery}
            disabled={isRunning}
            size="sm"
            className="h-8 text-xs gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <Play className={`h-3.5 w-3.5 ${isRunning ? "animate-pulse" : ""}`} />
            Run
            <kbd className="hidden lg:inline-flex items-center text-[10px] opacity-70
                           bg-primary-foreground/20 border border-primary-foreground/30
                           rounded px-1 py-px font-mono">⌘↵</kbd>
          </Button>
        </div>
      </div>

      {/* ── AI Assistant bar ────────────────────────────────────────────────── */}
      <div className="shrink-0 border-b bg-primary/5 px-3 py-2 flex items-center gap-2">
        <Sparkles className="h-3.5 w-3.5 text-primary shrink-0" />
        <Input
          placeholder="Ask AI: e.g. 'Show top 5 customers by total order value'"
          value={aiQuestion}
          onChange={e => setAiQuestion(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleAskAI()}
          className="h-7 text-xs flex-1 bg-background"
        />
        <Button
          size="sm" variant="outline" className="h-7 text-xs gap-1.5 shrink-0"
          onClick={handleAskAI}
          disabled={!aiQuestion.trim() || aiLoading}
        >
          {aiLoading
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <Sparkles className="h-3.5 w-3.5" />}
          {aiLoading ? "Generating…" : "Generate SQL"}
        </Button>
        {aiExplanation && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground max-w-xs truncate">
            <span className="truncate">{aiExplanation}</span>
            <button onClick={() => setAiExplanation(null)}>
              <X className="h-3 w-3 hover:text-foreground" />
            </button>
          </div>
        )}
      </div>

      {/* ── Main body ───────────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left: Schema tree */}
        <div
          className="shrink-0 flex border-r relative bg-muted/20"
          style={{ width: schemaOpen ? schemaWidth : 36 }}
        >
          {schemaOpen ? (
            <>
              <div className="flex flex-col flex-1 overflow-hidden">
                <div className="flex items-center justify-between px-3 h-9 border-b shrink-0">
                  <div className="flex items-center gap-1.5">
                    <Database className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs font-medium text-muted-foreground">Schema</span>
                  </div>
                  <Button variant="ghost" size="sm" className="h-6 w-6 p-0"
                    onClick={() => setSchemaOpen(false)} aria-label="Collapse" title="Collapse">
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <div className="flex-1 overflow-auto">
                  <SchemaTree onTableSelect={handleTableSelect} />
                </div>
              </div>
              <div
                onMouseDown={startSchemaResize}
                className="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize
                           hover:bg-primary/50 active:bg-primary/70 transition-colors z-10"
                aria-label="Drag to resize" title="Drag to resize"
              />
            </>
          ) : (
            <Button
              variant="ghost" size="sm"
              className="h-9 w-9 p-0 m-0 rounded-none text-muted-foreground"
              onClick={() => setSchemaOpen(true)} aria-label="Expand schema" title="Expand schema">
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>

        {/* Center: Editor + Results */}
        <div className="flex flex-col flex-1 overflow-hidden">

          {/* ── Editor section ───────────────────────────────────────────────── */}
          <div className="shrink-0 flex flex-col border-b" style={{ height: editorHeight }}>
            {/* Editor header */}
            <div className="flex items-center justify-between px-3 h-9 border-b bg-muted/30 shrink-0">
              <div className="flex items-center gap-2">
                <Code2 className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs font-medium">SQL Editor</span>
                <div className="h-3.5 w-px bg-border" />
                <Badge
                  variant="outline"
                  className="text-[10px] h-4 px-1.5 font-normal gap-1"
                  title={`Query engine: ${engineName} (${engineStatus})`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full inline-block ${
                    engineStatus === "healthy" ? "bg-[var(--dp-good)]" :
                    engineStatus === "unhealthy" ? "bg-destructive" : "bg-[var(--dp-warn)]"
                  }`} />
                  {engineName}
                </Badge>
              </div>
              <div className="flex items-center gap-0.5">
                <Button
                  variant="ghost" size="sm" className="h-6 px-2 text-[11px] gap-1
                    text-muted-foreground hover:text-foreground"
                  onClick={copySql}
                  aria-label="Copy SQL to clipboard" title="Copy SQL to clipboard"
                >
                  {copied
                    ? <Check className="h-3 w-3 text-[var(--dp-good)]" />
                    : <Copy className="h-3 w-3" />}
                  {copied ? "Copied" : "Copy"}
                </Button>
                <Button
                  variant="ghost" size="sm" className="h-6 px-2 text-[11px] gap-1
                    text-muted-foreground hover:text-foreground"
                  onClick={formatQuery}
                  aria-label="Format SQL" title="Format SQL"
                >
                  <AlignLeft className="h-3 w-3" />
                  Format
                </Button>
                <Button
                  variant="ghost" size="sm" className="h-6 px-2 text-[11px] gap-1
                    text-muted-foreground hover:text-destructive"
                  onClick={() => { setQuery(DEFAULT_QUERY); setResults(null); setQueryStatus("idle"); setError(null) }}
                  aria-label="Clear editor" title="Clear editor"
                >
                  <Trash2 className="h-3 w-3" />
                  Clear
                </Button>
              </div>
            </div>

            {/* Monaco editor */}
            <div className="flex-1 overflow-hidden">
              <SqlEditor value={query} onChange={setQuery} onExecute={executeQuery} />
            </div>
          </div>

          {/* ── Drag handle between editor and results ───────────────────────── */}
          <div
            onMouseDown={startEditorResize}
            className="h-1.5 shrink-0 cursor-row-resize bg-border/50
                       hover:bg-primary/50 active:bg-primary/70 transition-colors
                       flex items-center justify-center"
            aria-label="Drag to resize" title="Drag to resize"
          >
            <div className="w-8 h-px bg-muted-foreground/30 rounded" />
          </div>

          {/* ── Results section ──────────────────────────────────────────────── */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Results header */}
            <div className="flex items-center justify-between px-3 h-9 border-b bg-muted/30 shrink-0">
              <div className="flex items-center gap-2">
                <BarChart2 className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs font-medium">Results</span>
                {hasResults && (
                  <>
                    <div className="h-3.5 w-px bg-border" />
                    <span className="dp-num text-[11px] text-muted-foreground">
                      {results.truncated ? "first " : ""}{results.rows.length.toLocaleString()} rows
                    </span>
                    <span className="text-[11px] text-muted-foreground/60">·</span>
                    <span className="dp-num text-[11px] text-muted-foreground">
                      {results.columns.length} cols
                    </span>
                    <span className="text-[11px] text-muted-foreground/60">·</span>
                    <span className="dp-num text-[11px] text-muted-foreground">
                      {results.execution_time_ms < 1000
                        ? `${Math.round(results.execution_time_ms)}ms`
                        : `${(results.execution_time_ms / 1000).toFixed(2)}s`}
                    </span>
                    {results.truncated && (
                      <Badge
                        variant="outline"
                        className="text-[10px] h-4 px-1.5 font-normal gap-1 text-[var(--dp-warn)] border-[var(--dp-warn)]/40"
                        title="Add your own LIMIT clause to see more rows"
                      >
                        <AlertCircle className="h-3 w-3" />
                        Limited to 1,000 rows
                      </Badge>
                    )}
                    {resultsStale && (
                      <Badge
                        variant="outline"
                        className="text-[10px] h-4 px-1.5 font-normal gap-1 text-[var(--dp-warn)] border-[var(--dp-warn)]/40"
                        title="The editor has changed since these results were produced — re-run to refresh"
                      >
                        <AlertCircle className="h-3 w-3" />
                        Editor changed since run
                      </Badge>
                    )}
                  </>
                )}
              </div>
              {/* Chart selector — inline in results header */}
              {hasResults && (
                <ChartSelector selectedType={chartType} onTypeChange={setChartType} />
              )}
            </div>

            {/* Results body */}
            <div className="flex-1 overflow-hidden">
              {/* idle */}
              {queryStatus === "idle" && !results && (
                <div className="flex h-full items-center justify-center flex-col gap-2">
                  <div className="text-muted-foreground/30">
                    <Play className="h-8 w-8" />
                  </div>
                  <p className="text-sm text-muted-foreground">Write a query and run it to see results here</p>
                  <p className="text-xs text-muted-foreground/60">
                    Press <kbd className="px-1.5 py-0.5 text-[10px] border rounded font-mono">⌘↵</kbd> or click Run — or pick a table from the schema tree to start
                  </p>
                </div>
              )}

              {/* running */}
              {isRunning && (
                <div className="flex h-full items-center justify-center">
                  <div className="text-center space-y-3">
                    <div className="animate-spin rounded-full h-8 w-8 border-2
                                    border-primary border-t-transparent mx-auto" />
                    <p className="text-sm text-muted-foreground">Executing query...</p>
                  </div>
                </div>
              )}

              {/* error */}
              {queryStatus === "error" && error && (
                <div className="m-4 rounded-lg border border-destructive/30 bg-destructive/5 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
                    <p className="text-sm font-medium text-destructive">Query Error</p>
                  </div>
                  <pre className="text-xs text-destructive/80 whitespace-pre-wrap font-mono
                                  bg-destructive/5 rounded p-3 border border-destructive/10">
                    {error}
                  </pre>
                </div>
              )}

              {/* results */}
              {hasResults && (
                chartType === "table" ? (
                  <div className="h-full overflow-hidden p-3">
                    <QueryResults
                      columns={results.columns}
                      rows={results.rows}
                      executionTime={results.execution_time_ms}
                      loading={false}
                    />
                  </div>
                ) : (
                  <div className="h-full overflow-auto p-4">
                    <ChartRenderer
                      data={getChartData()}
                      chartType={chartType}
                      xAxis={xAxis}
                      yAxis={yAxis}
                      chartConfig={{ showGrid, showLegend }}
                    />
                  </div>
                )
              )}
            </div>
          </div>
        </div>

        {/* Right: sliding panels */}
        {rightPanel === "history" && (
          <div className="w-72 shrink-0 border-l flex flex-col overflow-hidden">
            <QueryHistorySidebar
              onQuerySelect={handleQuerySelect}
              isOpen={true}
              onToggle={() => setRightPanel(null)}
            />
          </div>
        )}

        {rightPanel === "chart-config" && hasResults && (
          <div className="w-64 shrink-0 border-l overflow-auto">
            <div className="flex items-center justify-between px-3 h-9 border-b bg-muted/30">
              <div className="flex items-center gap-1.5">
                <Settings className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs font-medium">Chart Config</span>
              </div>
              <Button variant="ghost" size="sm" className="h-6 w-6 p-0"
                onClick={() => setRightPanel(null)}>
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
            <div className="p-3">
              <ChartConfigPanel
                columns={results!.columns}
                xAxis={xAxis} yAxis={yAxis}
                onXAxisChange={setXAxis} onYAxisChange={setYAxis}
                showGrid={showGrid} showLegend={showLegend}
                onShowGridChange={setShowGrid} onShowLegendChange={setShowLegend}
              />
            </div>
          </div>
        )}
      </div>

      {/* Modals */}
      {results && (
        <OpenInNotebookModal
          open={openInNotebookOpen}
          onOpenChange={setOpenInNotebookOpen}
          queryText={query}
          columns={results.columns}
          rowCount={results.rows.length}
          executionTimeMs={results.execution_time_ms}
        />
      )}

      {results && (
        <LogToMlflowModal
          open={logToMlflowOpen}
          onOpenChange={setLogToMlflowOpen}
          queryText={query}
          columns={results.columns}
          rowCount={results.rows.length}
          executionTimeMs={results.execution_time_ms}
          onSuccess={() => toast("Run logged to MLflow!", "success")}
        />
      )}
      <SaveDashboardModal
        open={saveDashboardOpen}
        onOpenChange={setSaveDashboardOpen}
        queryText={query}
        chartConfig={{ chartType, xAxis, yAxis, showGrid, showLegend }}
        onSuccess={() => toast("Dashboard saved!", "success")}
      />
    </div>
  )
}

// Analytics workspace — one entry, two tabs. ?tab=dashboards selects the saved
// dashboards gallery; anything else is the SQL Editor. Both share the "query"
// capability and the /queries/execute engine.
function AnalyticsWorkspace() {
  const tab = useSearchParams().get("tab")
  return tab === "dashboards" ? <DashboardsGallery /> : <QueryPageInner />
}

export default function QueryPage() {
  return (
    <CapabilityGate capability="query">
      <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
        <AnalyticsWorkspace />
      </Suspense>
    </CapabilityGate>
  )
}
