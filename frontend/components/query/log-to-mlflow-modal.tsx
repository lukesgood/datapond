"use client"

import { useState, useEffect } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { FlaskConical, Plus, Loader2, ExternalLink, X, CheckCircle2, AlertCircle } from "lucide-react"

interface MlflowExperiment {
  experiment_id: string
  name: string
}

interface KVRow {
  key: string
  value: string
}

interface Props {
  open: boolean
  onOpenChange: (v: boolean) => void
  queryText: string
  columns: string[]
  rowCount: number
  executionTimeMs: number
  onSuccess?: (runId: string) => void
}

export function LogToMlflowModal({
  open,
  onOpenChange,
  queryText,
  columns,
  rowCount,
  executionTimeMs,
  onSuccess,
}: Props) {
  const [experiments, setExperiments] = useState<MlflowExperiment[]>([])
  const [selectedExpId, setSelectedExpId] = useState("")
  const [runName, setRunName] = useState("")
  const [newExpName, setNewExpName] = useState("")
  const [showNewExp, setShowNewExp] = useState(false)
  const [customParams, setCustomParams] = useState<KVRow[]>([{ key: "", value: "" }])
  const [customMetrics, setCustomMetrics] = useState<KVRow[]>([])
  const [loading, setLoading] = useState(false)
  const [loadingExps, setLoadingExps] = useState(false)
  const [creating, setCreating] = useState(false)
  const [result, setResult] = useState<{ run_id: string; mlflow_url: string; run_name: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setResult(null)
      setError(null)
      setRunName("")
      setNewExpName("")
      setShowNewExp(false)
      setCustomParams([{ key: "", value: "" }])
      setCustomMetrics([])
      fetchExperiments()
    }
  }, [open])

  const fetchExperiments = async () => {
    setLoadingExps(true)
    try {
      const r = await fetch("/api/mlflow/experiments")
      const data = await r.json()
      const exps: MlflowExperiment[] = Array.isArray(data) ? data : (data.experiments ?? [])
      setExperiments(exps)
      if (exps.length > 0 && !selectedExpId) {
        setSelectedExpId(exps[0].experiment_id)
      }
    } catch {
      // silently fail — user can still create a new experiment
    } finally {
      setLoadingExps(false)
    }
  }

  const handleCreateExp = async () => {
    if (!newExpName.trim()) return
    setCreating(true)
    try {
      const r = await fetch("/api/mlflow/experiments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newExpName.trim() }),
      })
      if (!r.ok) throw new Error("Failed to create experiment")
      const exp = await r.json()
      setExperiments(prev => [...prev, exp])
      setSelectedExpId(exp.experiment_id)
      setNewExpName("")
      setShowNewExp(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create experiment")
    } finally {
      setCreating(false)
    }
  }

  // KV list helpers
  const updateParam = (i: number, field: "key" | "value", val: string) => {
    setCustomParams(prev => prev.map((row, idx) => idx === i ? { ...row, [field]: val } : row))
  }
  const addParam = () => setCustomParams(prev => [...prev, { key: "", value: "" }])
  const removeParam = (i: number) => setCustomParams(prev => prev.filter((_, idx) => idx !== i))

  const updateMetric = (i: number, field: "key" | "value", val: string) => {
    setCustomMetrics(prev => prev.map((row, idx) => idx === i ? { ...row, [field]: val } : row))
  }
  const addMetric = () => setCustomMetrics(prev => [...prev, { key: "", value: "" }])
  const removeMetric = (i: number) => setCustomMetrics(prev => prev.filter((_, idx) => idx !== i))

  const handleSubmit = async () => {
    if (!selectedExpId) {
      setError("Select an experiment first")
      return
    }
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string> = {}
      customParams.forEach(({ key, value }) => {
        if (key.trim()) params[key.trim()] = value
      })

      const metrics: Record<string, number> = {}
      customMetrics.forEach(({ key, value }) => {
        if (key.trim() && !isNaN(Number(value))) {
          metrics[key.trim()] = Number(value)
        }
      })

      const r = await fetch("/api/mlflow/log-query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          experiment_id: selectedExpId,
          run_name: runName.trim() || undefined,
          query_text: queryText,
          row_count: rowCount,
          execution_time_ms: executionTimeMs,
          columns,
          params: Object.keys(params).length > 0 ? params : undefined,
          metrics: Object.keys(metrics).length > 0 ? metrics : undefined,
        }),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(body.detail || "Failed to log run")
      }
      const data = await r.json()
      setResult({
        run_id: data.run_id,
        mlflow_url: data.mlflow_url ?? "/mlflow",
        run_name: runName.trim() || data.run_id?.slice(0, 8) || "run",
      })
      onSuccess?.(data.run_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to log run")
    } finally {
      setLoading(false)
    }
  }

  const queryPreview = queryText.trim().replace(/\s+/g, " ").slice(0, 120)
  const executionTimeSec = (executionTimeMs / 1000).toFixed(2)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-orange-500" />
            Log to MLflow
          </DialogTitle>
        </DialogHeader>

        {/* Success state */}
        {result ? (
          <div className="py-4 space-y-4">
            <div className="flex flex-col items-center gap-3 py-4 text-center">
              <CheckCircle2 className="h-10 w-10 text-green-500" />
              <div>
                <p className="font-medium text-sm">Run logged successfully!</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Run <span className="font-mono">{result.run_name}</span> saved to MLflow
                </p>
              </div>
              <a
                href={result.mlflow_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline"
              >
                View in MLflow
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>
            <div className="flex justify-end">
              <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                Close
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4 py-2">
            {/* Query preview */}
            <div className="rounded-md border bg-muted/40 p-3 space-y-2">
              <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                Query Preview
              </p>
              <p className="text-xs font-mono text-foreground/80 line-clamp-2 leading-relaxed">
                {queryPreview}
                {queryText.trim().length > 120 && (
                  <span className="text-muted-foreground">…</span>
                )}
              </p>
              <div className="flex gap-2 pt-0.5">
                <Badge variant="secondary" className="text-[11px] h-5">
                  {rowCount.toLocaleString()} rows
                </Badge>
                <Badge variant="secondary" className="text-[11px] h-5">
                  {executionTimeMs >= 1000 ? `${executionTimeSec}s` : `${executionTimeMs}ms`}
                </Badge>
                <Badge variant="secondary" className="text-[11px] h-5">
                  {columns.length} columns
                </Badge>
              </div>
            </div>

            {/* Experiment selector */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs">Experiment</Label>
                {!showNewExp && (
                  <button
                    type="button"
                    onClick={() => setShowNewExp(true)}
                    className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
                  >
                    <Plus className="h-3 w-3" />
                    New experiment
                  </button>
                )}
              </div>

              {showNewExp ? (
                <div className="flex gap-2">
                  <Input
                    placeholder="Experiment name"
                    value={newExpName}
                    onChange={e => setNewExpName(e.target.value)}
                    className="h-8 text-xs"
                    onKeyDown={e => e.key === "Enter" && handleCreateExp()}
                    autoFocus
                  />
                  <Button
                    size="sm"
                    className="h-8 text-xs px-3"
                    onClick={handleCreateExp}
                    disabled={creating || !newExpName.trim()}
                  >
                    {creating ? <Loader2 className="h-3 w-3 animate-spin" /> : "Create"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-8 text-xs px-2"
                    onClick={() => { setShowNewExp(false); setNewExpName("") }}
                    disabled={creating}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ) : (
                <Select
                  value={selectedExpId}
                  onValueChange={(v) => setSelectedExpId(v ?? "")}
                  disabled={loadingExps}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder={loadingExps ? "Loading…" : "Select experiment"} />
                  </SelectTrigger>
                  <SelectContent>
                    {experiments.length === 0 && !loadingExps && (
                      <div className="px-2 py-2 text-xs text-muted-foreground">
                        No experiments yet — create one above
                      </div>
                    )}
                    {experiments.map(exp => (
                      <SelectItem key={exp.experiment_id} value={exp.experiment_id} className="text-xs">
                        {exp.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>

            {/* Run name */}
            <div className="space-y-1.5">
              <Label className="text-xs">
                Run Name <span className="text-muted-foreground font-normal">(optional)</span>
              </Label>
              <Input
                placeholder="e.g., revenue-analysis-q4"
                value={runName}
                onChange={e => setRunName(e.target.value)}
                className="h-8 text-xs"
              />
            </div>

            {/* Custom params */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs">
                  Parameters <span className="text-muted-foreground font-normal">(optional)</span>
                </Label>
                <button
                  type="button"
                  onClick={addParam}
                  className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
                >
                  <Plus className="h-3 w-3" />
                  Add
                </button>
              </div>
              <div className="space-y-1.5">
                {customParams.map((row, i) => (
                  <div key={i} className="flex gap-1.5 items-center">
                    <Input
                      placeholder="key"
                      value={row.key}
                      onChange={e => updateParam(i, "key", e.target.value)}
                      className="h-7 text-xs flex-1"
                    />
                    <Input
                      placeholder="value"
                      value={row.value}
                      onChange={e => updateParam(i, "value", e.target.value)}
                      className="h-7 text-xs flex-1"
                    />
                    {customParams.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeParam(i)}
                        className="text-muted-foreground hover:text-destructive transition-colors"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Custom metrics */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs">
                  Metrics <span className="text-muted-foreground font-normal">(numeric, optional)</span>
                </Label>
                <button
                  type="button"
                  onClick={addMetric}
                  className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
                >
                  <Plus className="h-3 w-3" />
                  Add
                </button>
              </div>
              {customMetrics.length === 0 && (
                <p className="text-[11px] text-muted-foreground">No custom metrics yet.</p>
              )}
              <div className="space-y-1.5">
                {customMetrics.map((row, i) => (
                  <div key={i} className="flex gap-1.5 items-center">
                    <Input
                      placeholder="metric name"
                      value={row.key}
                      onChange={e => updateMetric(i, "key", e.target.value)}
                      className="h-7 text-xs flex-1"
                    />
                    <Input
                      placeholder="0.0"
                      value={row.value}
                      onChange={e => updateMetric(i, "value", e.target.value)}
                      className="h-7 text-xs flex-1"
                      type="number"
                    />
                    <button
                      type="button"
                      onClick={() => removeMetric(i)}
                      className="text-muted-foreground hover:text-destructive transition-colors"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="flex items-start gap-2 rounded-md bg-destructive/10 border border-destructive/20 p-2.5">
                <AlertCircle className="h-3.5 w-3.5 text-destructive mt-0.5 shrink-0" />
                <p className="text-xs text-destructive">{error}</p>
              </div>
            )}

            {/* Footer */}
            <div className="flex justify-end gap-2 pt-1">
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs"
                onClick={() => onOpenChange(false)}
                disabled={loading}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                className="h-8 text-xs gap-1.5"
                onClick={handleSubmit}
                disabled={loading || !selectedExpId}
              >
                {loading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <FlaskConical className="h-3.5 w-3.5" />
                )}
                {loading ? "Logging…" : "Log Run"}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
