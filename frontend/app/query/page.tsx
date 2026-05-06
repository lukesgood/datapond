"use client"

import { useState, useRef, useCallback, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Play, Save, History, Settings, ChevronRight, ChevronLeft,
  FlaskConical, Code2, Database, Trash2, AlignLeft,
  TableProperties, BarChart2, AlertCircle, FileCode
} from "lucide-react"
import { SqlEditor } from "@/components/query/sql-editor"
import { SchemaTree } from "@/components/query/schema-tree"
import { QueryResults } from "@/components/query/query-results"
import { addToQueryHistory } from "@/components/query/query-history"
import { QueryHistorySidebar } from "@/components/query/query-history-sidebar"
import { ChartSelector } from "@/components/query/chart-selector"
import { ChartRenderer, ChartType } from "@/components/query/chart-renderer"
import { ChartConfigPanel } from "@/components/query/chart-config-panel"
import { SaveDashboardModal } from "@/components/query/save-dashboard-modal"
import { LogToMlflowModal } from "@/components/query/log-to-mlflow-modal"
import { OpenInNotebookModal } from "@/components/query/open-in-notebook-modal"
import { useToast } from "@/lib/toast"

interface QueryResult {
  columns: string[]
  rows: any[][]
  execution_time_ms: number
}

type QueryStatus = "idle" | "running" | "success" | "error"
type RightPanel = "history" | "chart-config" | null

const DEFAULT_QUERY = "-- Write your SQL here\nSELECT 1 AS hello;"

export default function QueryPage() {
  const [query, setQuery]                   = useState(DEFAULT_QUERY)
  const [queryStatus, setQueryStatus]       = useState<QueryStatus>("idle")
  const [results, setResults]               = useState<QueryResult | null>(null)
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
  const [trinoStatus, setTrinoStatus]       = useState<"healthy" | "unhealthy" | "unknown">("unknown")
  const [catalogs, setCatalogs]             = useState<string[]>([])

  const isResizingSchema   = useRef(false)
  const isResizingEditor   = useRef(false)
  const { toast } = useToast()

  // Fetch actual engine status and catalogs on mount
  useEffect(() => {
    fetch("/api/services")
      .then(r => r.json())
      .then((services: { name: string; status: string }[]) => {
        const trino = services.find(s => s.name === "trino")
        setTrinoStatus((trino?.status as "healthy" | "unhealthy" | "unknown") ?? "unknown")
      })
      .catch(() => setTrinoStatus("unknown"))

    fetch("/api/catalog/schemas")
      .then(r => r.json())
      .then(data => {
        const names = (data.catalogs ?? [])
          .map((c: { name: string }) => c.name)
          .filter((n: string) => n !== "system")
        setCatalogs(names)
      })
      .catch(() => {})
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
      setQueryStatus("success")
      addToQueryHistory(query)
      if (data.columns.length > 0 && !xAxis) setXAxis(data.columns[0])
      if (data.columns.length > 1 && !yAxis) setYAxis(data.columns[1])
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
      setQueryStatus("error")
    }
  }, [query, xAxis, yAxis])

  const handleTableSelect = (catalog: string, schema: string, table: string) => {
    setQuery(`SELECT *\nFROM ${catalog}.${schema}.${table}\nLIMIT 100;`)
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

  return (
    <div className="flex flex-col overflow-hidden bg-background" style={{ height: "calc(100vh - 56px)" }}>

      {/* ── Top app toolbar ─────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1.5 border-b px-3 h-11 shrink-0 bg-background">
        {/* Left: status */}
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span className="text-sm font-semibold text-foreground hidden sm:block">SQL Lab</span>
          <div className="h-4 w-px bg-border hidden sm:block" />
          {isRunning && (
            <Badge variant="secondary" className="text-xs gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse inline-block" />
              Executing...
            </Badge>
          )}
          {queryStatus === "success" && results && (
            <Badge className="text-xs bg-emerald-600/90 hover:bg-emerald-600/90 gap-1">
              <TableProperties className="h-3 w-3" />
              {results.rows.length.toLocaleString()} rows · {
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
            title="Save as dashboard"
          >
            <Save className="h-3.5 w-3.5" />
            <span className="hidden md:inline">Save</span>
          </Button>

          {hasResults && (
            <Button
              variant="ghost" size="sm" className="h-8 text-xs gap-1.5"
              onClick={() => setOpenInNotebookOpen(true)}
              title="Open in Jupyter Notebook"
            >
              <FileCode className="h-3.5 w-3.5" />
              <span className="hidden md:inline">Notebook</span>
            </Button>
          )}

          {hasResults && (
            <Button
              variant="ghost" size="sm" className="h-8 text-xs gap-1.5"
              onClick={() => setLogToMlflowOpen(true)}
              title="Log results to MLflow"
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
            title="Query history"
          >
            <History className="h-3.5 w-3.5" />
            <span className="hidden md:inline">History</span>
          </Button>

          {hasResults && chartType !== "table" && (
            <Button
              variant={rightPanel === "chart-config" ? "secondary" : "ghost"}
              size="sm" className="h-8 text-xs gap-1.5"
              onClick={() => togglePanel("chart-config")}
              title="Chart settings"
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
                    onClick={() => setSchemaOpen(false)} title="Collapse">
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
                title="Drag to resize"
              />
            </>
          ) : (
            <Button
              variant="ghost" size="sm"
              className="h-9 w-9 p-0 m-0 rounded-none text-muted-foreground"
              onClick={() => setSchemaOpen(true)} title="Expand schema">
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
                  title={`Query engine: Trino (${trinoStatus})\nCatalogs: ${catalogs.join(", ") || "loading..."}`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full inline-block ${
                    trinoStatus === "healthy" ? "bg-emerald-500" :
                    trinoStatus === "unhealthy" ? "bg-red-500" : "bg-yellow-400"
                  }`} />
                  Trino
                  {catalogs.length > 0 && (
                    <span className="text-muted-foreground">
                      · {catalogs.join(", ")}
                    </span>
                  )}
                </Badge>
              </div>
              <div className="flex items-center gap-0.5">
                <Button
                  variant="ghost" size="sm" className="h-6 px-2 text-[11px] gap-1
                    text-muted-foreground hover:text-foreground"
                  onClick={formatQuery}
                  title="Format SQL"
                >
                  <AlignLeft className="h-3 w-3" />
                  Format
                </Button>
                <Button
                  variant="ghost" size="sm" className="h-6 px-2 text-[11px] gap-1
                    text-muted-foreground hover:text-destructive"
                  onClick={() => { setQuery(DEFAULT_QUERY); setResults(null); setQueryStatus("idle"); setError(null) }}
                  title="Clear editor"
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
            title="Drag to resize"
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
                    <span className="text-[11px] text-muted-foreground">
                      {results.rows.length.toLocaleString()} rows
                    </span>
                    <span className="text-[11px] text-muted-foreground/60">·</span>
                    <span className="text-[11px] text-muted-foreground">
                      {results.columns.length} cols
                    </span>
                    <span className="text-[11px] text-muted-foreground/60">·</span>
                    <span className="text-[11px] text-muted-foreground">
                      {results.execution_time_ms < 1000
                        ? `${Math.round(results.execution_time_ms)}ms`
                        : `${(results.execution_time_ms / 1000).toFixed(2)}s`}
                    </span>
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
                  <p className="text-sm text-muted-foreground">Run a query to see results</p>
                  <p className="text-xs text-muted-foreground/60">
                    Press <kbd className="px-1.5 py-0.5 text-[10px] border rounded font-mono">⌘↵</kbd> or click Run
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
