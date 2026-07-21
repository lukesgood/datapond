"use client"

import { useState, useEffect } from "react"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import {
  CheckCircle2, XCircle, Loader2, AlertCircle,
  Code2, Play, Rocket, ChevronRight, Wand2,
  Plus, Trash2, Database, Table2, GitBranch,
} from "lucide-react"

interface Props {
  open: boolean
  onOpenChange: (v: boolean) => void
  onDeployed?: (pipelineName: string) => void
}

interface Connection { id: string; name: string; connector_type: string }
interface ValidationResult {
  success: boolean
  pipeline_name?: string
  errors?: string[]
  warnings?: string[]
}
interface DeployResult {
  success: boolean
  pipeline_name: string
  dag_id: string
  dag_file: string
  message?: string
}
interface CompileResult {
  success: boolean
  pipeline_name: string
  errors?: string[]
  artifacts?: Array<{ type: string; content?: string }>
}

// ── Wizard state ────────────────────────────────────────────────────────────
interface WizardState {
  pipelineName: string
  schedule: string
  description: string
  sources: {
    id: string
    name: string
    connectionName: string
    connectionType: string
    table: string
    mode: "full_refresh" | "incremental"
    watermarkColumn: string
  }[]
  transforms: {
    id: string
    name: string
    sql: string
    mode: "full_refresh" | "incremental"
    dependsOn: string
    qualityCheck: string
  }[]
}

const SCHEDULE_OPTIONS = [
  { value: "@hourly",  label: "Every hour" },
  { value: "@daily",   label: "Daily (midnight)" },
  { value: "@weekly",  label: "Weekly (Sunday)" },
  { value: "@monthly", label: "Monthly" },
  { value: "None",     label: "Manual only" },
  { value: "custom",   label: "Custom cron..." },
]

function uid() { return Math.random().toString(36).slice(2, 8) }

// ── DSL code generator ──────────────────────────────────────────────────────
function generateCode(w: WizardState): string {
  const scheduleVal = w.schedule === "None" ? "None" : `"${w.schedule}"`
  const lines: string[] = [
    `from app.pipelines.decorators import pipeline, source, live_table, quality`,
    ``,
    `@pipeline(`,
    `    name="${w.pipelineName}",`,
    `    schedule=${scheduleVal},`,
    ...(w.description ? [`    description="${w.description}",`] : []),
    `)`,
    `def ${w.pipelineName}(): pass`,
    ``,
  ]

  for (const src of w.sources) {
    lines.push(
      ``,
      `@source(`,
      `    name="${src.name}",`,
      `    connection="${src.connectionName}",`,
      `    source_type="${src.connectionType}",`,
      `    table="${src.table}",`,
      `    mode="${src.mode}",`,
      ...(src.mode === "incremental" && src.watermarkColumn
        ? [`    watermark_column="${src.watermarkColumn}",`] : []),
      `)`,
      `def ${src.name}(): pass`,
    )
  }

  for (const tr of w.transforms) {
    const deps = tr.dependsOn ? `["${tr.dependsOn}"]` : "[]"
    lines.push(
      ``,
      `@live_table(mode="${tr.mode}", depends_on=${deps})`,
      `def ${tr.name}():`,
      `    return """`,
      ...tr.sql.split("\n").map(l => `    ${l}`),
      `    """`,
    )
    if (tr.qualityCheck.trim()) {
      lines.push(
        ``,
        `@quality(table="${tr.name}")`,
        `def check_${tr.name}():`,
        `    return "${tr.qualityCheck.replace(/"/g, '\\"')}"`,
      )
    }
  }

  return lines.join("\n")
}

// ── Step progress bar ────────────────────────────────────────────────────────
type DeployStep = "edit" | "validate" | "deploy" | "done"

function StepBar({ step }: { step: DeployStep }) {
  const steps: { key: DeployStep; label: string }[] = [
    { key: "edit", label: "Configure" },
    { key: "validate", label: "Validate" },
    { key: "deploy", label: "Deploy" },
    { key: "done", label: "Done" },
  ]
  const cur = steps.findIndex(s => s.key === step)
  return (
    <div className="flex items-center gap-1.5 text-xs">
      {steps.map((s, i) => (
        <span key={s.key} className="flex items-center gap-1.5">
          <span className={`inline-flex items-center justify-center h-5 w-5 rounded-full text-[10px] font-medium
            ${i < cur ? "bg-emerald-500 text-white" :
              i === cur ? "bg-primary text-primary-foreground" :
              "bg-muted text-muted-foreground"}`}>
            {i < cur ? "✓" : i + 1}
          </span>
          <span className={i === cur ? "font-medium" : "text-muted-foreground"}>{s.label}</span>
          {i < steps.length - 1 && <ChevronRight className="h-3 w-3 text-muted-foreground" />}
        </span>
      ))}
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────
export function CreatePipelineModal({ open, onOpenChange, onDeployed }: Props) {
  const [mode, setMode]           = useState<"wizard" | "code">("wizard")
  const [deployStep, setDeployStep] = useState<DeployStep>("edit")
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [validateResult, setValidateResult] = useState<ValidationResult | null>(null)
  const [deployResult, setDeployResult]     = useState<DeployResult | null>(null)
  const [overwrite, setOverwrite] = useState(false)
  const [connections, setConnections] = useState<Connection[]>([])
  const [customSchedule, setCustomSchedule] = useState("")
  const [code, setCode]           = useState("")

  const [wizard, setWizard] = useState<WizardState>({
    pipelineName: "my_pipeline",
    schedule: "@daily",
    description: "",
    sources: [{
      id: uid(), name: "raw_source", connectionName: "",
      connectionType: "postgresql", table: "", mode: "incremental", watermarkColumn: "updated_at",
    }],
    transforms: [{
      id: uid(), name: "clean_data",
      sql: "SELECT *\nFROM {{ source('raw_source') }}\nWHERE id IS NOT NULL\n{{ incremental_filter('updated_at') }}",
      mode: "incremental", dependsOn: "raw_source", qualityCheck: "id IS NOT NULL",
    }],
  })

  // Load connections
  useEffect(() => {
    if (open) {
      fetch("/api/connectors/connections")
        .then(r => r.json())
        .then(d => setConnections(Array.isArray(d) ? d : []))
        .catch(() => {})
    }
  }, [open])

  // Sync wizard → code when switching to code tab
  const handleTabChange = (v: string) => {
    if (v === "code") {
      const schedule = wizard.schedule === "custom" ? (customSchedule || "@daily") : wizard.schedule
      setCode(generateCode({ ...wizard, schedule }))
    }
    setMode(v as "wizard" | "code")
  }

  const currentCode = mode === "wizard"
    ? generateCode({ ...wizard, schedule: wizard.schedule === "custom" ? (customSchedule || "@daily") : wizard.schedule })
    : code

  // ── Validate ──────────────────────────────────────────────────────────────
  const handleValidate = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch("/api/pipelines/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: currentCode }),
      })
      const data = await res.json()
      setValidateResult(data)
      if (data.success) setDeployStep("validate")
      else setError(data.errors?.join("\n") || "Validation failed")
    } catch (e) {
      setError(e instanceof Error ? e.message : "Validation failed")
    } finally {
      setLoading(false)
    }
  }

  // ── Compile & Deploy ──────────────────────────────────────────────────────
  const handleDeploy = async () => {
    setLoading(true)
    setError(null)
    try {
      const compRes = await fetch("/api/pipelines/compile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: currentCode }),
      })
      const compData: CompileResult = await compRes.json()
      if (!compData.success) throw new Error(compData.errors?.join("\n") || "Compile failed")

      const dagArtifact = compData.artifacts?.find(a => a.type === "airflow_dag")
      if (!dagArtifact?.content) throw new Error("No DAG code generated")

      const deployRes = await fetch("/api/pipelines/deploy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_name: compData.pipeline_name,
          dag_code: dagArtifact.content,
          overwrite,
        }),
      })
      const deployData: DeployResult = await deployRes.json()
      if (deployRes.status === 409) {
        setError(`Pipeline '${compData.pipeline_name}' already exists.`)
        setOverwrite(true)
        setDeployStep("validate")
        return
      }
      if (!deployData.success) throw new Error(deployData.message || "Deploy failed")
      setDeployResult(deployData)
      setDeployStep("done")
      onDeployed?.(deployData.pipeline_name)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Deploy failed")
    } finally {
      setLoading(false)
    }
  }

  const reset = () => {
    setDeployStep("edit")
    setValidateResult(null)
    setDeployResult(null)
    setError(null)
    setOverwrite(false)
  }

  // ── Wizard helpers ────────────────────────────────────────────────────────
  const updateSource = (id: string, patch: Partial<WizardState["sources"][0]>) =>
    setWizard(w => ({ ...w, sources: w.sources.map(s => s.id === id ? { ...s, ...patch } : s) }))

  const updateTransform = (id: string, patch: Partial<WizardState["transforms"][0]>) =>
    setWizard(w => ({ ...w, transforms: w.transforms.map(t => t.id === id ? { ...t, ...patch } : t) }))

  const addSource = () =>
    setWizard(w => ({ ...w, sources: [...w.sources, {
      id: uid(), name: `source_${w.sources.length + 1}`, connectionName: "",
      connectionType: "postgresql", table: "", mode: "incremental", watermarkColumn: "updated_at",
    }]}))

  const addTransform = () =>
    setWizard(w => ({ ...w, transforms: [...w.transforms, {
      id: uid(), name: `transform_${w.transforms.length + 1}`,
      sql: "SELECT *\nFROM {{ source('raw_source') }}",
      mode: "full_refresh", dependsOn: w.sources[0]?.name ?? "",
      qualityCheck: "",
    }]}))

  const allSourceNames = wizard.sources.map(s => s.name)

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <Dialog open={open} onOpenChange={v => { if (!v) { reset(); onOpenChange(false) } }}>
      <DialogContent className="max-w-3xl max-h-[88vh] flex flex-col gap-0 p-0">
        <DialogHeader className="px-5 pt-5 pb-3 border-b">
          <DialogTitle className="flex items-center gap-2 text-base">
            <GitBranch className="h-4 w-4" />
            New Pipeline
          </DialogTitle>
          <StepBar step={deployStep} />
        </DialogHeader>

        <div className="flex-1 overflow-auto px-5 py-4 space-y-4 min-h-0">

          {/* ── Edit step ── */}
          {(deployStep === "edit" || deployStep === "validate") && (
            <Tabs value={mode} onValueChange={handleTabChange}>
              <TabsList className="h-8 mb-4">
                <TabsTrigger value="wizard" className="text-xs h-7 gap-1.5">
                  <Wand2 className="h-3.5 w-3.5" />
                  Visual Builder
                </TabsTrigger>
                <TabsTrigger value="code" className="text-xs h-7 gap-1.5">
                  <Code2 className="h-3.5 w-3.5" />
                  Code Editor
                </TabsTrigger>
              </TabsList>

              {/* ── Visual Builder ── */}
              <TabsContent value="wizard" className="space-y-5 mt-0">

                {/* 1. Basic Info */}
                <section className="space-y-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    1. Pipeline Info
                  </h3>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Name <span className="text-destructive">*</span></Label>
                      <Input
                        value={wizard.pipelineName}
                        onChange={e => setWizard(w => ({ ...w, pipelineName: e.target.value.replace(/\s/g, "_") }))}
                        className="h-8 text-sm font-mono"
                        placeholder="my_pipeline"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Schedule</Label>
                      <Select
                        value={wizard.schedule}
                        onValueChange={(v) => { if (v) setWizard(w => ({ ...w, schedule: v })) }}
                      >
                        <SelectTrigger className="h-8 text-sm">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {SCHEDULE_OPTIONS.map(o => (
                            <SelectItem key={o.value} value={o.value} className="text-sm">{o.label}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    {wizard.schedule === "custom" && (
                      <div className="col-span-2 space-y-1.5">
                        <Label className="text-xs">Cron Expression</Label>
                        <Input
                          value={customSchedule}
                          onChange={e => setCustomSchedule(e.target.value)}
                          className="h-8 text-sm font-mono"
                          placeholder="0 6 * * *  (every day at 6am)"
                        />
                      </div>
                    )}
                    <div className="col-span-2 space-y-1.5">
                      <Label className="text-xs">Description</Label>
                      <Input
                        value={wizard.description}
                        onChange={e => setWizard(w => ({ ...w, description: e.target.value }))}
                        className="h-8 text-sm"
                        placeholder="What does this pipeline do?"
                      />
                    </div>
                  </div>
                </section>

                <Separator />

                {/* 2. Data Sources */}
                <section className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      2. Data Sources
                    </h3>
                    <Button variant="outline" size="sm" className="h-6 text-xs gap-1" onClick={addSource}>
                      <Plus className="h-3 w-3" />Add Source
                    </Button>
                  </div>
                  {wizard.sources.map((src, idx) => (
                    <div key={src.id} className="rounded-lg border p-3 space-y-3 bg-muted/20">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5">
                          <Database className="h-3.5 w-3.5 text-muted-foreground" />
                          <span className="text-xs font-medium">Source {idx + 1}</span>
                        </div>
                        {wizard.sources.length > 1 && (
                          <Button variant="ghost" size="icon" className="h-6 w-6"
                            onClick={() => setWizard(w => ({ ...w, sources: w.sources.filter(s => s.id !== src.id) }))}>
                            <Trash2 className="h-3 w-3 text-muted-foreground" />
                          </Button>
                        )}
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <div className="space-y-1">
                          <Label className="text-[11px]">Source Name</Label>
                          <Input value={src.name}
                            onChange={e => updateSource(src.id, { name: e.target.value.replace(/\s/g, "_") })}
                            className="h-7 text-xs font-mono" placeholder="raw_orders" />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-[11px]">Connection</Label>
                          <Select value={src.connectionName}
                            onValueChange={(v) => {
                              if (!v) return
                              const conn = connections.find(c => c.name === v)
                              updateSource(src.id, { connectionName: v, connectionType: conn?.connector_type ?? "postgresql" })
                            }}>
                            <SelectTrigger className="h-7 text-xs">
                              <SelectValue placeholder="Select connection..." />
                            </SelectTrigger>
                            <SelectContent>
                              {connections.length === 0
                                ? <SelectItem value="__none" disabled>No connections — add in Connectors</SelectItem>
                                : connections.map(c => (
                                  <SelectItem key={c.id} value={c.name} className="text-xs">
                                    {c.name} ({c.connector_type})
                                  </SelectItem>
                                ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-[11px]">Table</Label>
                          <Input value={src.table}
                            onChange={e => updateSource(src.id, { table: e.target.value })}
                            className="h-7 text-xs font-mono" placeholder="schema.table_name" />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-[11px]">Sync Mode</Label>
                          <Select value={src.mode}
                            onValueChange={(v) => {
                              if (v === "incremental" || v === "full_refresh") updateSource(src.id, { mode: v })
                            }}>
                            <SelectTrigger className="h-7 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="incremental" className="text-xs">Incremental</SelectItem>
                              <SelectItem value="full_refresh" className="text-xs">Full Refresh</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                        {src.mode === "incremental" && (
                          <div className="col-span-2 space-y-1">
                            <Label className="text-[11px]">Watermark Column</Label>
                            <Input value={src.watermarkColumn}
                              onChange={e => updateSource(src.id, { watermarkColumn: e.target.value })}
                              className="h-7 text-xs font-mono" placeholder="updated_at" />
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </section>

                <Separator />

                {/* 3. Transforms */}
                <section className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      3. Transformations
                    </h3>
                    <Button variant="outline" size="sm" className="h-6 text-xs gap-1" onClick={addTransform}>
                      <Plus className="h-3 w-3" />Add Transform
                    </Button>
                  </div>
                  {wizard.transforms.map((tr, idx) => (
                    <div key={tr.id} className="rounded-lg border p-3 space-y-3 bg-muted/20">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5">
                          <Table2 className="h-3.5 w-3.5 text-muted-foreground" />
                          <span className="text-xs font-medium">Transform {idx + 1}</span>
                        </div>
                        {wizard.transforms.length > 1 && (
                          <Button variant="ghost" size="icon" className="h-6 w-6"
                            onClick={() => setWizard(w => ({ ...w, transforms: w.transforms.filter(t => t.id !== tr.id) }))}>
                            <Trash2 className="h-3 w-3 text-muted-foreground" />
                          </Button>
                        )}
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        <div className="space-y-1">
                          <Label className="text-[11px]">Output Table Name</Label>
                          <Input value={tr.name}
                            onChange={e => updateTransform(tr.id, { name: e.target.value.replace(/\s/g, "_") })}
                            className="h-7 text-xs font-mono" />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-[11px]">Depends On</Label>
                          <Select value={tr.dependsOn}
                            onValueChange={(v) => { if (v) updateTransform(tr.id, { dependsOn: v }) }}>
                            <SelectTrigger className="h-7 text-xs">
                              <SelectValue placeholder="Select..." />
                            </SelectTrigger>
                            <SelectContent>
                              {[...allSourceNames, ...wizard.transforms.filter(t => t.id !== tr.id).map(t => t.name)]
                                .map(n => <SelectItem key={n} value={n} className="text-xs">{n}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-[11px]">Mode</Label>
                          <Select value={tr.mode}
                            onValueChange={(v) => {
                              if (v === "incremental" || v === "full_refresh") updateTransform(tr.id, { mode: v })
                            }}>
                            <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value="incremental" className="text-xs">Incremental</SelectItem>
                              <SelectItem value="full_refresh" className="text-xs">Full Refresh</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <div className="space-y-1">
                        <Label className="text-[11px]">
                          SQL Transform
                          <span className="ml-1 font-normal text-muted-foreground">
                            (use {`{{ source('name') }}`} or {`{{ ref('name') }}`})
                          </span>
                        </Label>
                        <Textarea
                          value={tr.sql}
                          onChange={e => updateTransform(tr.id, { sql: e.target.value })}
                          className="font-mono text-xs min-h-[80px] resize-none"
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-[11px]">
                          Quality Check
                          <span className="ml-1 font-normal text-muted-foreground">(SQL WHERE condition, optional)</span>
                        </Label>
                        <Input value={tr.qualityCheck}
                          onChange={e => updateTransform(tr.id, { qualityCheck: e.target.value })}
                          className="h-7 text-xs font-mono" placeholder="id IS NOT NULL AND amount > 0" />
                      </div>
                    </div>
                  ))}
                </section>

                {/* Code preview */}
                <details className="group">
                  <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground
                                      flex items-center gap-1 list-none">
                    <Code2 className="h-3 w-3" />
                    <span>Preview generated code</span>
                  </summary>
                  <pre className="mt-2 p-3 rounded-md bg-muted text-[11px] font-mono overflow-x-auto
                                  border whitespace-pre-wrap">
                    {currentCode}
                  </pre>
                </details>
              </TabsContent>

              {/* ── Code Editor ── */}
              <TabsContent value="code" className="mt-0">
                <Textarea
                  value={code}
                  onChange={e => setCode(e.target.value)}
                  className="font-mono text-xs min-h-[420px] resize-none"
                  spellCheck={false}
                />
              </TabsContent>
            </Tabs>
          )}

          {/* ── Validate result ── */}
          {validateResult && deployStep === "validate" && (
            <div className={`rounded-lg border p-3 text-xs space-y-1.5
              ${validateResult.success ? "border-emerald-200 bg-emerald-50" : "border-destructive/30 bg-destructive/5"}`}>
              <div className="flex items-center gap-1.5 font-medium">
                {validateResult.success
                  ? <><CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                      <span className="text-emerald-700">
                        Ready to deploy — <code>{validateResult.pipeline_name}</code>
                      </span></>
                  : <><XCircle className="h-3.5 w-3.5 text-destructive" />
                      <span className="text-destructive">Validation failed</span></>
                }
              </div>
              {validateResult.warnings?.map((w, i) => (
                <p key={i} className="text-yellow-700">⚠ {w}</p>
              ))}
            </div>
          )}

          {overwrite && (
            <div className="flex items-center gap-2 rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-xs text-yellow-800">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              Pipeline already exists. Deploying will overwrite the current version.
            </div>
          )}

          {/* ── Done ── */}
          {deployStep === "done" && deployResult && (
            <div className="flex flex-col items-center gap-4 py-8 text-center">
              <div className="h-14 w-14 rounded-full bg-emerald-50 flex items-center justify-center">
                <CheckCircle2 className="h-7 w-7 text-emerald-600" />
              </div>
              <div>
                <p className="font-semibold">Pipeline Deployed!</p>
                <p className="text-sm text-muted-foreground mt-0.5">
                  Airflow will pick it up within 30 seconds
                </p>
              </div>
              <div className="rounded-lg border bg-muted/30 p-3 text-xs text-left w-full max-w-sm space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Pipeline</span>
                  <code>{deployResult.pipeline_name}</code>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">DAG ID</span>
                  <code>{deployResult.dag_id}</code>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">File</span>
                  <code>{deployResult.dag_file}</code>
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3">
              <div className="flex items-center gap-1.5 mb-1">
                <AlertCircle className="h-3.5 w-3.5 text-destructive" />
                <span className="text-xs font-medium text-destructive">Error</span>
              </div>
              <pre className="text-xs text-destructive/80 whitespace-pre-wrap font-mono">{error}</pre>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t px-5 py-3 flex justify-between items-center">
          <Button variant="ghost" size="sm" className="text-xs"
            onClick={() => { reset(); onOpenChange(false) }}>
            {deployStep === "done" ? "Close" : "Cancel"}
          </Button>
          <div className="flex gap-2">
            {deployStep === "validate" && (
              <Button variant="outline" size="sm" className="text-xs gap-1.5"
                onClick={() => setDeployStep("edit")}>
                Back
              </Button>
            )}
            {(deployStep === "edit" || deployStep === "validate") && (
              <>
                {deployStep === "edit" && (
                  <Button size="sm" className="text-xs gap-1.5"
                    onClick={handleValidate} disabled={loading || !currentCode.trim()}>
                    {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                    Validate
                  </Button>
                )}
                {deployStep === "validate" && (
                  <Button size="sm" className="text-xs gap-1.5"
                    onClick={handleDeploy} disabled={loading}>
                    {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Rocket className="h-3.5 w-3.5" />}
                    {overwrite ? "Overwrite & Deploy" : "Deploy"}
                  </Button>
                )}
              </>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
