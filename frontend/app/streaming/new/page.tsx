"use client"

import { useState, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import {
  CheckCircle2, XCircle, ChevronLeft, ChevronRight, Loader2, RefreshCw,
  Radio, Database, Zap, AlertTriangle,
} from "lucide-react"
import Link from "next/link"

// ── Sources ────────────────────────────────────────────────────────────────────

const SOURCES = [
  {
    id: "postgres-cdc", type: "cdc", name: "PostgreSQL CDC",
    icon: "🐘", color: "blue",
    description: "WAL 기반 실시간 변경 캡처 (INSERT / UPDATE / DELETE)",
    features: ["Zero latency", "No source load", "DELETE 반영"],
    available: true,
  },
  {
    id: "mysql-cdc", type: "cdc", name: "MySQL CDC",
    icon: "🐬", color: "orange",
    description: "binlog 기반 MySQL / MariaDB 실시간 변경 캡처",
    features: ["binlog 기반", "MariaDB 지원"],
    available: false,
  },
  {
    id: "kafka", type: "event", name: "Apache Kafka",
    icon: "📨", color: "purple",
    description: "Kafka 토픽을 Iceberg 테이블로 실시간 수집",
    features: ["JSON / Avro / CSV", "Schema Registry"],
    available: true,
  },
  {
    id: "kinesis", type: "event", name: "Amazon Kinesis",
    icon: "☁️", color: "purple",
    description: "AWS Kinesis Data Streams → Iceberg",
    features: ["AWS 네이티브", "at-least-once"],
    available: true,
  },
  {
    id: "pulsar", type: "event", name: "Apache Pulsar",
    icon: "⚡", color: "purple",
    description: "Pulsar 토픽 스트리밍",
    features: ["멀티테넌시"],
    available: false,
  },
] as const

type SourceId = typeof SOURCES[number]["id"]
type SourceType = "cdc" | "event" | "custom"
type StreamingResourceType = "sources" | "views" | "sinks"

interface CreatedResource {
  type: StreamingResourceType
  name: string
}

interface CdcPipelineResult {
  tables_total: number
  tables_success: number
  tables_failed: number
  results: Array<{ table: string; status: string; error?: string | null }>
}

async function responseError(response: Response, fallback: string) {
  try {
    const data = await response.json()
    return typeof data?.detail === "string" ? data.detail : fallback
  } catch {
    return fallback
  }
}

async function rollbackCreatedResources(created: CreatedResource[]) {
  const failures: string[] = []
  let removed = 0
  for (const resource of [...created].reverse()) {
    try {
      const response = await fetch(
        `/api/streaming/${resource.type}/${encodeURIComponent(resource.name)}`,
        { method: "DELETE" },
      )
      if (!response.ok) {
        failures.push(
          `${resource.name}: ${await responseError(response, "rollback failed")}`,
        )
      } else {
        removed += 1
      }
    } catch (error) {
      failures.push(
        `${resource.name}: ${error instanceof Error ? error.message : "rollback failed"}`,
      )
    }
  }
  return { removed, failures }
}

// ── CDC Prerequisites Sidebar ─────────────────────────────────────────────────

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
      className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
    >
      {copied ? "Copied!" : "Copy"}
    </button>
  )
}

const PREREQ_STEPS = [
  {
    label: "WAL Level = logical",
    desc: "Must be set before creating a CDC source. Requires DB restart.",
    sql: `ALTER SYSTEM SET wal_level = logical;`,
    note: "Restart PostgreSQL after applying.",
  },
  {
    label: "REPLICATION privilege",
    desc: "The connecting user must have REPLICATION role.",
    sql: `ALTER ROLE {user} REPLICATION LOGIN;`,
  },
  {
    label: "CREATE on database",
    desc: "Required to create replication slots.",
    sql: `GRANT CREATE ON DATABASE {db} TO {user};`,
  },
  {
    label: "Publication (optional)",
    desc: "RisingWave auto-creates, but you can pre-create.",
    sql: `CREATE PUBLICATION datapond_pub FOR ALL TABLES;`,
    optional: true,
  },
]

function CdcPrereqSidebar({ db, user }: { db?: string; user?: string }) {
  const d = db || "your_db"
  const u = user || "your_user"

  return (
    <div className="rounded-xl border bg-amber-50/50 border-amber-200 overflow-hidden">
      <div className="px-4 py-3 border-b border-amber-200 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />
        <div>
          <p className="text-sm font-semibold text-amber-800">Source DB Prerequisites</p>
          <p className="text-[11px] text-amber-600 mt-0.5">Complete before connecting</p>
        </div>
      </div>

      <div className="px-4 py-3 space-y-4">
        {PREREQ_STEPS.map((p, i) => (
          <div key={i}>
            <div className="flex items-center gap-1.5 mb-1">
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-amber-500/15 text-[10px] font-bold text-amber-700 shrink-0">{i + 1}</span>
              <span className="text-xs font-semibold text-amber-800">{p.label}</span>
              {p.optional && <span className="text-[10px] text-amber-500 ml-auto">optional</span>}
            </div>
            <p className="text-[11px] text-amber-700 mb-1.5 ml-5">{p.desc}</p>
            <div className="relative rounded-md bg-white/70 border border-amber-200 ml-5">
              <pre className="text-[11px] font-mono text-amber-900 px-2.5 py-2 pr-14 whitespace-pre-wrap break-all">
                {p.sql.replace(/{db}/g, d).replace(/{user}/g, u)}
              </pre>
              <div className="absolute top-1.5 right-2">
                <CopyBtn text={p.sql.replace(/{db}/g, d).replace(/{user}/g, u)} />
              </div>
            </div>
            {p.note && (
              <p className="text-[10px] text-amber-600 mt-1 ml-5 italic">{p.note}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Step indicator ─────────────────────────────────────────────────────────────

function StepIndicator({
  steps,
  currentStep,
}: {
  steps: string[]
  currentStep: number | "confirm" | "done"
}) {
  const stepIndex =
    currentStep === "done" ? steps.length
    : currentStep === "confirm" ? steps.length - 1
    : (currentStep as number) - 1

  return (
    <div className="flex items-center gap-1 text-xs">
      {steps.map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <span
            className={`w-5 h-5 rounded-full flex items-center justify-center font-medium ${
              i < stepIndex
                ? "bg-green-600 text-white"
                : i === stepIndex
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground"
            }`}
          >
            {i < stepIndex ? "✓" : i + 1}
          </span>
          <span
            className={
              i === stepIndex ? "text-foreground font-medium" : "text-muted-foreground"
            }
          >
            {s}
          </span>
          {i < steps.length - 1 && (
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
          )}
        </div>
      ))}
    </div>
  )
}

// ── Main ───────────────────────────────────────────────────────────────────────

export default function NewStreamingPipelinePage() {
  return (
    <Suspense fallback={<div className="flex-1 flex items-center justify-center"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" /></div>}>
      <NewStreamingPipelineInner />
    </Suspense>
  )
}

function NewStreamingPipelineInner() {
  const router = useRouter()
  const searchParams = useSearchParams()

  // Pre-select source from ?source= query param (coming from marketplace tab)
  const sourceParam = searchParams.get("source") as SourceId | null
  const initialSource = sourceParam && SOURCES.find(s => s.id === sourceParam) ? sourceParam : null

  const [step, setStep] = useState<number | "confirm" | "done">(initialSource ? 2 : 1)
  const [selectedSource, setSelectedSource] = useState<SourceId | null>(initialSource)

  const sourceType: SourceType | null = selectedSource
    ? (SOURCES.find(s => s.id === selectedSource)?.type as SourceType) ?? null
    : null

  // ── CDC form ──────────────────────────────────────────────────────────────────
  const [cdcForm, setCdcForm] = useState({
    pipeline_name: "",
    db_host: "",
    db_port: "5432",
    db_name: "",
    db_user: "",
    db_password: "",
    db_schema: "public",
    iceberg_schema: "raw",
  })
  const [cdcTables, setCdcTables] = useState<string[]>([])
  const [cdcSelectedTables, setCdcSelectedTables] = useState<string[]>([])
  const [loadingTables, setLoadingTables] = useState(false)
  const [tableError, setTableError] = useState<string | null>(null)

  // ── CDC connection test result ─────────────────────────────────────────────
  const [cdcTestResult, setCdcTestResult] = useState<{
    tested: boolean
    success: boolean
    wal_level?: string
    wal_ok?: boolean
    error?: string
  } | null>(null)
  const [testingConn, setTestingConn] = useState(false)

  const handleTestCdcConnection = async () => {
    setTestingConn(true); setCdcTestResult(null)
    try {
      const res = await fetch("/api/streaming/cdc-test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          db_host: cdcForm.db_host, db_port: parseInt(cdcForm.db_port),
          db_name: cdcForm.db_name, db_user: cdcForm.db_user,
          db_password: cdcForm.db_password, db_schema: cdcForm.db_schema,
        }),
      })
      const d = await res.json()
      setCdcTestResult({ tested: true, success: d.success, wal_level: d.wal_level, wal_ok: d.wal_ok, error: d.error })
    } catch (e) {
      setCdcTestResult({ tested: true, success: false, error: e instanceof Error ? e.message : "Failed" })
    } finally {
      setTestingConn(false)
    }
  }

  // ── Event form ────────────────────────────────────────────────────────────────
  const [eventForm, setEventForm] = useState({
    pipeline_name: "",
    source_type: (sourceParam === "kinesis" ? "kinesis" : "kafka") as "kafka" | "kinesis",
    topic: "",
    bootstrap_servers: "",
    stream_name: "",
    aws_region: "us-east-1",
    format: "json" as "json" | "avro" | "csv",
    iceberg_schema: "raw",
    columns_sql: "data JSONB",  // default: raw JSON capture
  })

  // ── Create state ──────────────────────────────────────────────────────────────
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [createResult, setCreateResult] = useState<{ success: boolean; error?: string } | null>(null)

  // ── Derived step list ─────────────────────────────────────────────────────────
  const stepLabels =
    sourceType === "cdc"
      ? ["Source", "Connection", "Tables", "Confirm"]
      : ["Source", "Configuration", "Confirm"]

  // ── Handlers ──────────────────────────────────────────────────────────────────

  const fetchCdcTables = async () => {
    setLoadingTables(true)
    setTableError(null)
    try {
      const res = await fetch("/api/streaming/cdc-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          db_host: cdcForm.db_host,
          db_port: parseInt(cdcForm.db_port),
          db_name: cdcForm.db_name,
          db_user: cdcForm.db_user,
          db_password: cdcForm.db_password,
          db_schema: cdcForm.db_schema,
        }),
      })
      const d = await res.json()
      if (!d.success) throw new Error(d.error || "Connection failed")
      if (d.tables.length === 0) throw new Error("No tables found in schema — check schema name and permissions")
      if (!d.wal_ok) {
        // Show warning but don't block
        setTableError(`Warning: wal_level is "${d.wal_level}" — must be "logical" for CDC. Contact your DBA.`)
      }
      setCdcTables(d.tables)
      setCdcSelectedTables(d.tables)
      setStep(3)
    } catch (e) {
      setTableError(e instanceof Error ? e.message : "Failed to connect")
    } finally {
      setLoadingTables(false)
    }
  }

  const handleCreate = async () => {
    setCreating(true)
    setCreateError(null)
    setCreateResult(null)
    try {
      if (sourceType === "cdc") {
        const response = await fetch("/api/streaming/cdc-pipeline", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            pipeline_name: cdcForm.pipeline_name,
            db_host: cdcForm.db_host,
            db_port: parseInt(cdcForm.db_port),
            db_name: cdcForm.db_name,
            db_user: cdcForm.db_user,
            db_password: cdcForm.db_password,
            db_schema: cdcForm.db_schema,
            tables: cdcSelectedTables,
            iceberg_schema: cdcForm.iceberg_schema,
          }),
        })
        if (!response.ok) {
          throw new Error(await responseError(response, "CDC pipeline creation failed"))
        }
        const result: CdcPipelineResult = await response.json()
        if (result.tables_failed > 0) {
          const failed = result.results
            .filter(item => item.status !== "success")
            .map(item => `${item.table}: ${item.error || "creation failed"}`)
            .join("; ")
          const partial = result.tables_success > 0
            ? `Partial creation: ${result.tables_success}/${result.tables_total} tables succeeded; created objects were retained. `
            : "No tables were created. "
          throw new Error(`${partial}${failed}`)
        }
        setCreateResult({ success: true })
      } else {
        // Event (Kafka / Kinesis): source → view → sink. Track only successful
        // creates so rollback never removes an object this attempt did not create.
        const created: CreatedResource[] = []
        const sourceName = `${eventForm.pipeline_name}_src`
        const viewName = `${eventForm.pipeline_name}_mv`
        const sinkName = `${eventForm.pipeline_name}_sink`
        try {
          const isKafka = eventForm.source_type === "kafka"
          const sourceResponse = await fetch("/api/streaming/sources", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: sourceName,
              connector: eventForm.source_type,
              topic: isKafka ? eventForm.topic : eventForm.stream_name,
              bootstrap_servers: isKafka ? eventForm.bootstrap_servers : "",
              format: "plain",
              row_encode: eventForm.format,
              extra_props: isKafka
                ? {}
                : { stream: eventForm.stream_name, "aws.region": eventForm.aws_region },
              columns_sql: eventForm.columns_sql,
            }),
          })
          if (!sourceResponse.ok) {
            throw new Error(await responseError(sourceResponse, "Source creation failed"))
          }
          created.push({ type: "sources", name: sourceName })

          const viewResponse = await fetch("/api/streaming/views", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: viewName,
              definition: `SELECT * FROM ${sourceName}`,
            }),
          })
          if (!viewResponse.ok) {
            throw new Error(await responseError(viewResponse, "View creation failed"))
          }
          created.push({ type: "views", name: viewName })

          const sinkResponse = await fetch("/api/streaming/sinks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: sinkName,
              from_mv: viewName,
              connector: "iceberg",
              sink_type: "append-only",
              iceberg_schema: eventForm.iceberg_schema,
              iceberg_table: eventForm.pipeline_name,
            }),
          })
          if (!sinkResponse.ok) {
            throw new Error(await responseError(sinkResponse, "Sink creation failed"))
          }
          created.push({ type: "sinks", name: sinkName })
        } catch (error) {
          const cause = error instanceof Error ? error.message : "Pipeline creation failed"
          if (created.length === 0) {
            throw new Error(`${cause}. No resources were created.`)
          }
          const rollback = await rollbackCreatedResources(created)
          if (rollback.failures.length === 0) {
            throw new Error(`${cause}. Rollback removed all ${rollback.removed} created resources.`)
          }
          throw new Error(
            `${cause}. Rollback incomplete: removed ${rollback.removed}/${created.length}; ` +
            `failed to remove ${rollback.failures.join("; ")}`,
          )
        }
        setCreateResult({ success: true })
      }
      setStep("done")
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Failed")
    } finally {
      setCreating(false)
    }
  }

  // ── Render helpers ────────────────────────────────────────────────────────────

  const pipelineName = sourceType === "cdc" ? cdcForm.pipeline_name : eventForm.pipeline_name

  const renderStepContent = () => {

    // ── Step 1: Source selection ────────────────────────────────────────────────
    if (step === 1) {
      const cdcSources   = SOURCES.filter(s => s.type === "cdc")
      const eventSources = SOURCES.filter(s => s.type === "event")

      return (
        <div className="space-y-6">
          <p className="text-sm text-muted-foreground">
            어떤 소스에서 실시간으로 데이터를 가져오시겠습니까?
          </p>

          {/* DB Change Capture */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <div className="flex items-center justify-center w-5 h-5 rounded bg-primary/10">
                <RefreshCw className="h-3 w-3 text-primary" />
              </div>
              <p className="text-sm font-semibold">DB Change Capture</p>
              <span className="text-xs text-muted-foreground">— INSERT / UPDATE / DELETE 실시간 캡처</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {cdcSources.map(src => (
                <button
                  key={src.id}
                  onClick={() => {
                    if (!src.available) return
                    setSelectedSource(src.id)
                    setStep(2)
                  }}
                  className={`w-full flex items-start gap-4 p-5 rounded-xl border-2 text-left transition-all ${
                    src.available
                      ? "border-border hover:border-primary hover:shadow-md cursor-pointer bg-card"
                      : "border-border/50 opacity-40 cursor-not-allowed bg-muted/20"
                  }`}
                >
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-muted text-2xl shrink-0">
                    {src.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-semibold">{src.name}</span>
                      {!src.available && (
                        <Badge variant="secondary" className="text-[10px]">Coming Soon</Badge>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground">{src.description}</p>
                    <div className="flex flex-wrap gap-1 mt-2">
                      {src.features.map(f => (
                        <span
                          key={f}
                          className="text-[10px] bg-muted px-2 py-0.5 rounded-full font-medium"
                        >
                          {f}
                        </span>
                      ))}
                    </div>
                  </div>
                  {src.available && (
                    <ChevronRight className="h-5 w-5 text-muted-foreground shrink-0 mt-1" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Event Stream */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <div className="flex items-center justify-center w-5 h-5 rounded bg-purple-500/10">
                <Radio className="h-3 w-3 text-purple-600" />
              </div>
              <p className="text-sm font-semibold">Event Stream</p>
              <span className="text-xs text-muted-foreground">— Kafka · Kinesis 실시간 이벤트</span>
            </div>
            <div className="grid grid-cols-3 gap-3">
              {eventSources.map(src => (
                <button
                  key={src.id}
                  onClick={() => {
                    if (!src.available) return
                    if (src.id === "kinesis") {
                      setEventForm(p => ({ ...p, source_type: "kinesis" }))
                    } else {
                      setEventForm(p => ({ ...p, source_type: "kafka" }))
                    }
                    setSelectedSource(src.id)
                    setStep(2)
                  }}
                  className={`w-full flex items-start gap-4 p-5 rounded-xl border-2 text-left transition-all ${
                    src.available
                      ? "border-border hover:border-primary hover:shadow-md cursor-pointer bg-card"
                      : "border-border/50 opacity-40 cursor-not-allowed bg-muted/20"
                  }`}
                >
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-muted text-2xl shrink-0">
                    {src.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-semibold">{src.name}</span>
                      {!src.available && (
                        <Badge variant="secondary" className="text-[10px]">Coming Soon</Badge>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground">{src.description}</p>
                    <div className="flex flex-wrap gap-1 mt-2">
                      {src.features.map(f => (
                        <span
                          key={f}
                          className="text-[10px] bg-muted px-2 py-0.5 rounded-full font-medium"
                        >
                          {f}
                        </span>
                      ))}
                    </div>
                  </div>
                  {src.available && (
                    <ChevronRight className="h-5 w-5 text-muted-foreground shrink-0 mt-1" />
                  )}
                </button>
              ))}
            </div>
          </div>

        </div>
      )
    }

    // ── Step 2 (CDC): DB connection ────────────────────────────────────────────
    if (step === 2 && sourceType === "cdc") {
      const canTest = !!cdcForm.db_host && !!cdcForm.db_name && !!cdcForm.db_user

      return (
        <div className="space-y-4">

          <div className="space-y-1">
            <Label className="text-xs">Pipeline Name</Label>
            <Input
              value={cdcForm.pipeline_name}
              placeholder="e.g. orders_cdc"
              onChange={e => setCdcForm(p => ({ ...p, pipeline_name: e.target.value }))}
            />
          </div>

          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-2 space-y-1">
              <Label className="text-xs">Host</Label>
              <Input
                value={cdcForm.db_host}
                placeholder="postgres.datapond.svc"
                onChange={e => setCdcForm(p => ({ ...p, db_host: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Port</Label>
              <Input
                value={cdcForm.db_port}
                placeholder="5432"
                onChange={e => setCdcForm(p => ({ ...p, db_port: e.target.value }))}
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-xs">Database</Label>
            <Input
              value={cdcForm.db_name}
              placeholder="mydb"
              onChange={e => setCdcForm(p => ({ ...p, db_name: e.target.value }))}
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label className="text-xs">Username</Label>
              <Input
                value={cdcForm.db_user}
                placeholder="postgres"
                onChange={e => setCdcForm(p => ({ ...p, db_user: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Password</Label>
              <Input
                type="password"
                value={cdcForm.db_password}
                onChange={e => setCdcForm(p => ({ ...p, db_password: e.target.value }))}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label className="text-xs">Schema</Label>
              <Input
                value={cdcForm.db_schema}
                placeholder="public"
                onChange={e => setCdcForm(p => ({ ...p, db_schema: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Iceberg Target Namespace</Label>
              <Select
                value={cdcForm.iceberg_schema}
                onValueChange={v => v && setCdcForm(p => ({ ...p, iceberg_schema: v }))}
              >
                <SelectTrigger className="h-9 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["raw", "refined", "serving"].map(s => (
                    <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Test Connection + result checklist */}
          <div className="space-y-2">
            <Button
              type="button" variant="outline" size="sm"
              className="w-full gap-1.5"
              disabled={!canTest || testingConn}
              onClick={handleTestCdcConnection}
            >
              {testingConn
                ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />Testing…</>
                : <><Database className="h-3.5 w-3.5" />Test Connection</>}
            </Button>

            {cdcTestResult && (
              <div className={`rounded-lg border px-3 py-2.5 space-y-1.5 text-xs ${
                cdcTestResult.success ? "border-green-200 bg-green-50" : "border-destructive/30 bg-destructive/5"
              }`}>
                {/* Connection status */}
                <div className="flex items-center gap-2">
                  {cdcTestResult.success
                    ? <CheckCircle2 className="h-3.5 w-3.5 text-green-600 shrink-0" />
                    : <XCircle className="h-3.5 w-3.5 text-destructive shrink-0" />}
                  <span className={cdcTestResult.success ? "text-green-700 font-medium" : "text-destructive font-medium"}>
                    {cdcTestResult.success ? "Connected successfully" : `Connection failed: ${cdcTestResult.error}`}
                  </span>
                </div>

                {cdcTestResult.success && (
                  <>
                    {/* WAL level check */}
                    <div className="flex items-center gap-2">
                      {cdcTestResult.wal_ok
                        ? <CheckCircle2 className="h-3.5 w-3.5 text-green-600 shrink-0" />
                        : <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0" />}
                      <span className={cdcTestResult.wal_ok ? "text-green-700" : "text-amber-700"}>
                        WAL level: <code className="font-mono">{cdcTestResult.wal_level}</code>
                        {!cdcTestResult.wal_ok && " — must be logical for CDC"}
                      </span>
                      {!cdcTestResult.wal_ok && (
                        <button
                          onClick={() => navigator.clipboard.writeText("ALTER SYSTEM SET wal_level = logical;\nSELECT pg_reload_conf();")}
                          className="ml-auto text-[10px] text-amber-600 hover:underline underline-offset-2"
                        >
                          Copy fix SQL
                        </button>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          {tableError && (
            <p className={`text-xs rounded px-3 py-2 ${
              tableError.startsWith("Warning:")
                ? "text-amber-700 bg-amber-50 border border-amber-200"
                : "text-destructive bg-destructive/5"
            }`}>
              {tableError}
            </p>
          )}
        </div>
      )
    }

    // ── Step 3 (CDC): Table selection ──────────────────────────────────────────
    if (step === 3 && sourceType === "cdc") {
      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">{cdcTables.length} tables found</p>
            <div className="flex gap-2 text-xs">
              <button
                onClick={() => setCdcSelectedTables(cdcTables)}
                className="text-primary hover:underline"
              >
                All
              </button>
              <span className="text-muted-foreground">·</span>
              <button
                onClick={() => setCdcSelectedTables([])}
                className="text-muted-foreground hover:underline"
              >
                None
              </button>
            </div>
          </div>

          <div className="rounded-lg border divide-y max-h-64 overflow-y-auto">
            {cdcTables.map(t => (
              <label
                key={t}
                className="flex items-center gap-3 px-3 py-2 hover:bg-muted/30 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={cdcSelectedTables.includes(t)}
                  onChange={e =>
                    setCdcSelectedTables(prev =>
                      e.target.checked ? [...prev, t] : prev.filter(x => x !== t)
                    )
                  }
                />
                <span className="text-sm font-mono">{t}</span>
              </label>
            ))}
          </div>

          <p className="text-xs text-muted-foreground">
            {cdcSelectedTables.length} of {cdcTables.length} selected
          </p>
        </div>
      )
    }

    // ── Step 2 (Event): Kafka / Kinesis config ─────────────────────────────────
    if (step === 2 && sourceType === "event") {
      return (
        <div className="space-y-4">
          <div className="space-y-1">
            <Label className="text-xs">Pipeline Name</Label>
            <Input
              value={eventForm.pipeline_name}
              placeholder="e.g. user_events"
              onChange={e => setEventForm(p => ({ ...p, pipeline_name: e.target.value }))}
            />
          </div>

          {/* Source type toggle */}
          <div className="space-y-1">
            <Label className="text-xs">Source Type</Label>
            <div className="grid grid-cols-2 gap-2">
              {[
                { id: "kafka",   name: "Apache Kafka",   icon: "📨", desc: "Kafka 토픽" },
                { id: "kinesis", name: "Amazon Kinesis", icon: "☁️", desc: "AWS Kinesis" },
              ].map(t => (
                <button
                  key={t.id}
                  onClick={() =>
                    setEventForm(p => ({ ...p, source_type: t.id as "kafka" | "kinesis" }))
                  }
                  className={`flex items-center gap-2 p-2.5 rounded-lg border-2 transition-colors ${
                    eventForm.source_type === t.id
                      ? "border-purple-500 bg-purple-500/5"
                      : "border-border hover:border-purple-500/50"
                  }`}
                >
                  <span className="text-lg">{t.icon}</span>
                  <div className="text-left">
                    <p className="text-sm font-medium">{t.name}</p>
                    <p className="text-xs text-muted-foreground">{t.desc}</p>
                  </div>
                  {eventForm.source_type === t.id && (
                    <CheckCircle2 className="h-4 w-4 text-purple-600 ml-auto" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {eventForm.source_type === "kafka" ? (
            <>
              <div className="space-y-1">
                <Label className="text-xs">Topic</Label>
                <Input
                  value={eventForm.topic}
                  placeholder="my-topic"
                  onChange={e => setEventForm(p => ({ ...p, topic: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Bootstrap Servers</Label>
                <Input
                  value={eventForm.bootstrap_servers}
                  placeholder="kafka:9092"
                  onChange={e => setEventForm(p => ({ ...p, bootstrap_servers: e.target.value }))}
                />
              </div>
            </>
          ) : (
            <>
              <div className="space-y-1">
                <Label className="text-xs">Stream Name</Label>
                <Input
                  value={eventForm.stream_name}
                  placeholder="my-kinesis-stream"
                  onChange={e => setEventForm(p => ({ ...p, stream_name: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">AWS Region</Label>
                <Input
                  value={eventForm.aws_region}
                  placeholder="us-east-1"
                  onChange={e => setEventForm(p => ({ ...p, aws_region: e.target.value }))}
                />
              </div>
            </>
          )}

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label className="text-xs">Message Format</Label>
              <Select
                value={eventForm.format}
                onValueChange={v =>
                  v && setEventForm(p => ({ ...p, format: v as "json" | "avro" | "csv" }))
                }
              >
                <SelectTrigger className="h-9 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="json" className="text-xs">JSON</SelectItem>
                  <SelectItem value="avro" className="text-xs">Avro</SelectItem>
                  <SelectItem value="csv"  className="text-xs">CSV</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Iceberg Target Namespace</Label>
              <Select
                value={eventForm.iceberg_schema}
                onValueChange={v => v && setEventForm(p => ({ ...p, iceberg_schema: v }))}
              >
                <SelectTrigger className="h-9 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["raw", "refined", "serving"].map(s => (
                    <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-xs">
              Column Schema
              <span className="ml-1 font-normal text-muted-foreground normal-case">(SQL column definitions)</span>
            </Label>
            <textarea
              value={eventForm.columns_sql}
              onChange={e => setEventForm(p => ({ ...p, columns_sql: e.target.value }))}
              className="w-full h-20 px-3 py-2 text-xs font-mono rounded-md border bg-background resize-none focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="user_id BIGINT, event VARCHAR, ts TIMESTAMPTZ"
            />
            <p className="text-[10px] text-muted-foreground">
              Default <code className="font-mono">data JSONB</code> captures raw JSON. Define columns to extract specific fields.
            </p>
          </div>
        </div>
      )
    }

    // ── Confirm ────────────────────────────────────────────────────────────────
    if (step === "confirm") {
      const rows: [string, string][] =
        sourceType === "cdc"
          ? [
              ["Pipeline",       cdcForm.pipeline_name],
              ["Source",         "PostgreSQL CDC"],
              ["Host",           `${cdcForm.db_host}:${cdcForm.db_port}/${cdcForm.db_name}`],
              ["Tables",         `${cdcSelectedTables.length} selected`],
              ["Iceberg target", `iceberg.${cdcForm.iceberg_schema}.*`],
            ]
          : [
              ["Pipeline",
                eventForm.pipeline_name],
              ["Source",
                eventForm.source_type === "kafka" ? "Apache Kafka" : "Amazon Kinesis"],
              ...(eventForm.source_type === "kafka"
                ? [
                    ["Topic",             eventForm.topic] as [string, string],
                    ["Bootstrap Servers", eventForm.bootstrap_servers] as [string, string],
                  ]
                : [
                    ["Stream",     eventForm.stream_name] as [string, string],
                    ["AWS Region", eventForm.aws_region]  as [string, string],
                  ]
              ),
              ["Format",         eventForm.format.toUpperCase()],
              ["Iceberg target", `iceberg.${eventForm.iceberg_schema}.${eventForm.pipeline_name}`],
            ]

      return (
        <div className="space-y-4">
          <div className="rounded-lg bg-muted/40 border divide-y text-sm">
            {rows.map(([k, v]) => (
              <div key={k} className="flex justify-between px-3 py-2.5">
                <span className="text-muted-foreground">{k}</span>
                <span className="font-medium font-mono text-xs">{v}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {sourceType === "cdc"
              ? `This will create ${cdcSelectedTables.length * 3} RisingWave objects (source + materialized view + Iceberg sink per table).`
              : "This will create 3 RisingWave objects: source, materialized view, and Iceberg sink."}
          </p>
          {createError && (
            <p className="text-xs text-destructive bg-destructive/5 rounded px-3 py-2">
              {createError}
            </p>
          )}
        </div>
      )
    }

    // ── Done ───────────────────────────────────────────────────────────────────
    if (step === "done") {
      const success = createResult?.success === true
      return (
        <div className="flex flex-col items-center py-10 space-y-5 text-center">
          {success ? (
            <>
              <div className="rounded-full bg-green-100 p-4">
                <CheckCircle2 className="h-10 w-10 text-green-600" />
              </div>
              <div>
                <p className="font-semibold text-lg">Pipeline created successfully</p>
                <p className="text-sm text-muted-foreground mt-1">
                  {pipelineName}
                  {sourceType === "cdc" && cdcSelectedTables.length > 0
                    ? ` — ${cdcSelectedTables.length} table${cdcSelectedTables.length !== 1 ? "s" : ""}`
                    : ""}
                </p>
              </div>
              <Button onClick={() => router.push("/streaming")}>View Pipelines</Button>
            </>
          ) : (
            <>
              <p className="text-sm text-destructive">{createResult?.error ?? "An error occurred."}</p>
              <Button variant="outline" onClick={() => { setStep("confirm"); setCreateError(null) }}>
                ← Back
              </Button>
            </>
          )}
        </div>
      )
    }

    return null
  }

  // ── Navigation footer ─────────────────────────────────────────────────────────

  const renderFooter = () => {
    if (step === "done") return null

    if (step === 1) {
      return (
        <div className="flex justify-end">
          {/* No Next button on step 1 — selecting a card advances automatically */}
          <p className="text-xs text-muted-foreground self-center">Select a source above to continue</p>
        </div>
      )
    }

    if (step === 2 && sourceType === "cdc") {
      const canNext =
        !!cdcForm.pipeline_name && !!cdcForm.db_host && !!cdcForm.db_name &&
        !!cdcForm.db_user
      return (
        <div className="flex justify-between">
          <Button variant="outline" size="sm" onClick={() => router.push("/streaming?tab=add-source")}>
            <ChevronLeft className="h-4 w-4 mr-1" />Back
          </Button>
          <Button
            size="sm"
            onClick={fetchCdcTables}
            disabled={!canNext || loadingTables}
          >
            {loadingTables
              ? <><Loader2 className="h-4 w-4 animate-spin mr-1.5" />Connecting…</>
              : <>Next<ChevronRight className="h-4 w-4 ml-1" /></>}
          </Button>
        </div>
      )
    }

    if (step === 3 && sourceType === "cdc") {
      return (
        <div className="flex justify-between">
          <Button variant="outline" size="sm" onClick={() => setStep(2)}>
            <ChevronLeft className="h-4 w-4 mr-1" />Back
          </Button>
          <Button
            size="sm"
            onClick={() => setStep("confirm")}
            disabled={cdcSelectedTables.length === 0}
          >
            Next<ChevronRight className="h-4 w-4 ml-1" />
          </Button>
        </div>
      )
    }

    if (step === 2 && sourceType === "event") {
      const canNext =
        !!eventForm.pipeline_name && (
          eventForm.source_type === "kafka"
            ? !!eventForm.topic && !!eventForm.bootstrap_servers
            : !!eventForm.stream_name
        )
      return (
        <div className="flex justify-between">
          <Button variant="outline" size="sm" onClick={() => router.push("/streaming?tab=add-source")}>
            <ChevronLeft className="h-4 w-4 mr-1" />Back
          </Button>
          <Button
            size="sm"
            onClick={() => setStep("confirm")}
            disabled={!canNext}
          >
            Next<ChevronRight className="h-4 w-4 ml-1" />
          </Button>
        </div>
      )
    }

    if (step === "confirm") {
      const backStep: number = sourceType === "cdc" ? 3 : 2
      return (
        <div className="flex justify-between">
          <Button variant="outline" size="sm" onClick={() => setStep(backStep)}>
            <ChevronLeft className="h-4 w-4 mr-1" />Back
          </Button>
          <Button size="sm" onClick={handleCreate} disabled={creating}>
            {creating
              ? <><Loader2 className="h-4 w-4 animate-spin mr-1.5" />Creating…</>
              : "Create Pipeline"}
          </Button>
        </div>
      )
    }

    return null
  }

  // ── Page ───────────────────────────────────────────────────────────────────────

  return (
    <div className="flex-1 px-6 py-5">
      <div className={`${step === 2 && sourceType === "cdc" ? "max-w-5xl" : "max-w-3xl"} mx-auto space-y-6`}>

        {/* Header */}
        <div className="flex items-center gap-3">
          <Link
            href="/streaming"
            className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
          >
            <ChevronLeft className="h-4 w-4" />Streaming
          </Link>
          <span className="text-muted-foreground">/</span>
          <h1 className="text-sm font-medium">New Streaming Pipeline</h1>
        </div>

        {/* Title */}
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
            <Zap className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h2 className="text-xl font-bold">New Streaming Pipeline</h2>
            <p className="text-xs text-muted-foreground">
              Real-time CDC or event stream → Iceberg via RisingWave
            </p>
          </div>
        </div>

        {/* Step indicator (hidden on step 1 before source is chosen) */}
        {(step !== 1 || selectedSource !== null) && (
          <StepIndicator
            steps={stepLabels}
            currentStep={
              step === "done" || step === "confirm"
                ? step
                : (step as number)
            }
          />
        )}

        {/* Content card — 2-col layout for CDC Step 2 */}
        {step === 2 && sourceType === "cdc" ? (
          <div className="grid grid-cols-[1fr_320px] gap-5 items-start">
            <div className="rounded-xl border bg-card shadow-sm p-6">
              {renderStepContent()}
            </div>
            <CdcPrereqSidebar db={cdcForm.db_name} user={cdcForm.db_user} />
          </div>
        ) : (
          <div className="rounded-xl border bg-card shadow-sm p-6">
            {renderStepContent()}
          </div>
        )}

        {/* Footer navigation */}
        {step !== "done" && (
          <div className="pb-8">
            {renderFooter()}
          </div>
        )}

      </div>
    </div>
  )
}
