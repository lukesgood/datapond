"use client"

import { useCallback, useEffect, useState } from "react"
import { useCapabilities } from "@/lib/capabilities"
import { useToast } from "@/lib/toast"
import { buildToolCallSection, windowParams } from "@/lib/compliance-report"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { SourceState } from "@/components/ui/source-state"
import { readJson } from "@/lib/source-state"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { PiiEvidenceSection } from "@/components/governance/pii-evidence"
import { ToolCallsTab } from "@/components/governance/tool-calls-tab"
import { AccessPolicies } from "@/components/governance/access-policies"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import {
  Database,
  ShieldAlert,
  Lock,
  Search,
  FileText,
  RefreshCw,
  Download,
  Loader2,
} from "lucide-react"
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts"
import type {
  GovernanceStats,
  AuditLogItem,
  AuditStreamItem,
  PiiTable,
  AiSafetyFlag,
} from "@/lib/api"
import { callerLabel } from "@/lib/caller-label"

// ─── helpers ────────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n) + "…" : s
}

// ─── stat card ───────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string
  value: number | null
  icon: React.ReactNode
  colorClass: string
  bgClass: string
  loading: boolean
  /** Set when the number could not be read: the card says so and offers a retry,
   *  instead of an em dash that looks like "not measured". */
  error?: string | null
  onRetry?: () => void
}

function StatCard({ label, value, icon, colorClass, bgClass, loading, error, onRetry }: StatCardProps) {
  return (
    <Card>
      <CardContent className="pt-5 pb-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{label}</p>
            {loading ? (
              <Skeleton className="h-8 w-16 mt-1" />
            ) : error ? (
              <p className="mt-2 text-xs text-destructive">
                Could not load{onRetry && <> · <button className="underline" onClick={onRetry}>Retry</button></>}
              </p>
            ) : (
              /* An em dash, not 0, when the number is absent. `?? 0` made three
                 different situations look identical: measured zero, a stats fetch
                 that failed, and a PII scan that could not run because this profile
                 has no query engine. Only the first of those is zero. */
              <p className={`text-3xl font-bold mt-1 ${value == null ? "text-muted-foreground" : colorClass}`}
                 title={value == null ? "Not measured" : undefined}>
                {value ?? "\u2014"}
              </p>
            )}
          </div>
          <div className={`p-3 rounded-xl ${bgClass}`}>
            <div className={colorClass}>{icon}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ─── event type badge ─────────────────────────────────────────────────────────

function EventBadge({ type }: { type: string }) {
  // Only the event types the backend actually emits (derived from
  // query_history.status — see /api/governance/audit-log). No entries for
  // event types that are never written anywhere (ai_sql_generated /
  // pii_detected / login_success / login_failure) — those filters were
  // removed from the UI because they always returned 0 rows.
  const map: Record<string, { label: string; className: string }> = {
    query_executed:    { label: "Query executed",    className: "border-primary/40 text-primary" },
    query_error:       { label: "Query error",       className: "border-destructive/40 text-destructive" },
    query_timeout:     { label: "Query timeout",      className: "border-[var(--dp-warn)]/40 text-[var(--dp-warn-text)]" },
  }
  const cfg = map[type] ?? { label: type, className: "border-border text-muted-foreground" }
  return (
    <Badge variant="outline" className={cfg.className}>
      {cfg.label}
    </Badge>
  )
}

// ─── source badge (unified audit stream) ──────────────────────────────────────

function SourceBadge({ source }: { source: string }) {
  const map: Record<string, { label: string; className: string }> = {
    query:     { label: "Query",     className: "border-[var(--chart-1)]/40 text-[var(--chart-1)]" },
    auth:      { label: "Auth",      className: "border-[var(--chart-3)]/40 text-[var(--chart-3)]" },
    connector: { label: "Connector", className: "border-[var(--chart-4)]/40 text-[var(--chart-4)]" },
  }
  const cfg = map[source] ?? { label: source, className: "border-border text-muted-foreground" }
  return (
    <Badge variant="outline" className={cfg.className}>
      {cfg.label}
    </Badge>
  )
}

// ─── result badge ─────────────────────────────────────────────────────────────

function ResultBadge({ result }: { result: string }) {
  if (result === "통과" || result === "pass" || result === "success")
    return <Badge className="bg-[var(--dp-good)]/10 text-[var(--dp-good-text)] border-0">Passed</Badge>
  if (result === "failure" || result === "failed")
    return <Badge className="bg-destructive/10 text-destructive border-0">Failed</Badge>
  if (result === "error")
    return <Badge className="bg-destructive/10 text-destructive border-0">Error</Badge>
  if (result === "timeout")
    return <Badge className="bg-[var(--dp-warn)]/10 text-[var(--dp-warn-text)] border-0">Timeout</Badge>
  if (result === "차단" || result === "blocked")
    return <Badge className="bg-destructive/10 text-destructive border-0">Blocked</Badge>
  if (result === "마스킹" || result === "masked")
    return <Badge className="bg-[var(--dp-warn)]/10 text-[var(--dp-warn-text)] border-0">Masked</Badge>
  return <Badge variant="secondary">{result}</Badge>
}

// ─── risk badge ───────────────────────────────────────────────────────────────

function RiskBadge({ risk }: { risk: string }) {
  if (risk === "high")
    return <Badge className="bg-destructive/10 text-destructive border-0">High risk</Badge>
  if (risk === "medium")
    return <Badge className="bg-[var(--dp-warn)]/10 text-[var(--dp-warn-text)] border-0">Caution</Badge>
  return <Badge className="bg-[var(--dp-good)]/10 text-[var(--dp-good-text)] border-0">Normal</Badge>
}

// ─── PII type color ───────────────────────────────────────────────────────────

// Categories, not statuses: the identifiers that carry legal weight (SSN, card) keep
// the destructive tone, and the rest come from the chart ramp rather than raw palette
// hues, so they follow the theme like every other colour in the console.
const PII_COLORS: Record<string, string> = {
  email:   "bg-[var(--chart-1)]/10 text-[var(--chart-1)]",
  phone:   "bg-[var(--dp-good)]/10 text-[var(--dp-good-text)]",
  ssn:     "bg-destructive/10 text-destructive",
  card:    "bg-destructive/10 text-destructive",
  name:    "bg-muted text-muted-foreground",
  address: "bg-muted text-muted-foreground",
  dob:     "bg-[var(--chart-4)]/10 text-[var(--chart-4)]",
}

function PiiTypeBadge({ column, type }: { column: string; type: string }) {
  const cls = PII_COLORS[type.toLowerCase()] ?? "bg-muted text-muted-foreground"
  return (
    <Badge className={`${cls} border-0 gap-1`}>
      <Lock className="h-2.5 w-2.5" />
      {column}
      <span className="opacity-60 text-2xs">({type})</span>
    </Badge>
  )
}

// ─── summary stat pill ─────────────────────────────────────────────────────
// Shared with the Activity tab's summary-strip idiom (bordered rounded pill,
// bold tabular-nums value). `tone` encodes state as color; default is neutral.

function StatPill({
  value,
  label,
  tone = "default",
}: {
  value: React.ReactNode
  label: string
  tone?: "default" | "good" | "warn" | "bad"
}) {
  const toneCls =
    tone === "bad"
      ? "border-destructive/30 bg-destructive/5 text-destructive"
      : tone === "warn"
        ? "border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/5 text-[var(--dp-warn-text)]"
        : tone === "good"
          ? "border-[var(--dp-good)]/30 bg-[var(--dp-good)]/5 text-[var(--dp-good-text)]"
          : "text-muted-foreground"
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 ${toneCls}`}>
      <span className="font-semibold tabular-nums">{value}</span>
      <span className={tone === "default" ? "text-muted-foreground" : undefined}>{label}</span>
    </span>
  )
}

// ─── main page ────────────────────────────────────────────────────────────────

const GOVERNANCE_TABS = ["tool-calls", "audit", "activity", "ai-safety", "data-protection", "access-control", "reports"]

/** 3 of 200 is 1.5%, not 2% — whole-number rounding made the three shares add to 101%. */
const sharePct = (n: number, total: number) =>
  total > 0 ? `${Number(((n / total) * 100).toFixed(1))}%` : "0%"
const ATTENTION = new Set(["failure", "failed", "error", "blocked", "차단", "denied"])
const needsAttentionItem = (i: { status?: string | null }) => !!i.status && ATTENTION.has(i.status)

export default function GovernancePage() {
  const { toast } = useToast()
  const caps = useCapabilities()
  // ?tab= opens a tab directly (Metrics › Concepts links to a prefilled column mask).
  const [tab, setTab] = useState("tool-calls")
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab")
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (t && GOVERNANCE_TABS.includes(t)) setTab(t)
  }, [])
  // stats
  const [stats, setStats] = useState<GovernanceStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [statsError, setStatsError] = useState<string | null>(null)
  const [piiError, setPiiError] = useState<string | null>(null)

  // audit log
  const [auditItems, setAuditItems] = useState<AuditLogItem[]>([])
  const [auditTotal, setAuditTotal] = useState(0)
  const [auditOffset, setAuditOffset] = useState(0)
  // Bumped by Refresh so the effect refetches page one even when the offset is
  // already 0. Refresh used to fetch on its own and leave the offset where "Load
  // more" had put it, so the next "Load more" asked for an offset it already had
  // and nothing happened.
  const [auditReload, setAuditReload] = useState(0)
  const [auditLoading, setAuditLoading] = useState(true)
  const [auditError, setAuditError] = useState<string | null>(null)
  const [eventTypeFilter, setEventTypeFilter] = useState("all")
  const [searchQuery, setSearchQuery] = useState("")

  // unified activity stream (query + auth + connector)
  const [activityItems, setActivityItems] = useState<AuditStreamItem[]>([])
  const [activityLoading, setActivityLoading] = useState(true)
  const [activityError, setActivityError] = useState<string | null>(null)
  const [activityReload, setActivityReload] = useState(0)
  const [activitySource, setActivitySource] = useState("all")
  // The "needs attention" chip filters the feed to those events: a count with no way
  // to find them among a hundred rows was a dead end.
  const [attentionOnly, setAttentionOnly] = useState(false)
  const [activitySources, setActivitySources] = useState<string[]>([])

  // pii
  const [piiTables, setPiiTables] = useState<PiiTable[]>([])
  const [piiScanned, setPiiScanned] = useState(false)  // did a real scan run? (vs engine unsupported)
  const [piiLoading, setPiiLoading] = useState(true)

  // ai safety
  const [riskDist, setRiskDist] = useState<{ low: number; medium: number; high: number } | null>(null)
  const [recentFlags, setRecentFlags] = useState<AiSafetyFlag[]>([])
  const [safetyLoading, setSafetyLoading] = useState(true)
  const [safetyError, setSafetyError] = useState<string | null>(null)
  const [safetyReload, setSafetyReload] = useState(0)

  // reports state
  const [reportFrom, setReportFrom] = useState("")
  const [reportTo, setReportTo] = useState("")
  const [reportChecks, setReportChecks] = useState({
    queries: true,
    aiSql: true,
    pii: true,
    toolCalls: true,
  })
  const [exporting, setExporting] = useState(false)

  // Assemble a compliance report (JSON) from the sections that are checked.
  // Each section comes from its real governance dataset — the query audit log
  // is fetched fresh (the API caps at 200 rows / newest-first, so we surface a
  // `capped` flag when we hit it); AI-SQL safety, PII, and the blocked summary
  // are current snapshots already loaded on the page. No placeholders.
  const AUDIT_LIMIT = 200
  // One screenful per request; the backend allows up to 200 per call.
  const AUDIT_PAGE = 50
  const exportReport = async () => {
    setExporting(true)
    try {
      const from = reportFrom ? new Date(`${reportFrom}T00:00:00`).getTime() : null
      const to = reportTo ? new Date(`${reportTo}T23:59:59`).getTime() : null
      const inRange = (ts: string | null | undefined) => {
        if (from === null && to === null) return true
        if (!ts) return true
        const t = new Date(ts).getTime()
        return (from === null || t >= from) && (to === null || t <= to)
      }

      const report: Record<string, unknown> = {
        generated_at: new Date().toISOString(),
        date_range: { from: reportFrom || null, to: reportTo || null },
        note: "AI-SQL safety and PII sections are current snapshots; the query audit log and agent tool calls are time-scoped per event.",
        sections: {},
      }
      const sections = report.sections as Record<string, unknown>

      if (reportChecks.queries) {
        const qs = new URLSearchParams({ limit: String(AUDIT_LIMIT), offset: "0" })
        const r = await fetch(`/api/governance/audit-log?${qs}`)
        if (!r.ok) throw new Error(`audit-log HTTP ${r.status}`)
        const d = await r.json()
        const all: AuditLogItem[] = d.items ?? []
        const scoped = all.filter((it) => inRange(it.created_at))
        sections.query_audit_log = {
          total_available: d.total ?? all.length,
          returned: all.length,
          capped: (d.total ?? all.length) > all.length,
          events_in_range: scoped.length,
          events: scoped,
        }
      }
      if (reportChecks.aiSql) {
        sections.ai_sql_safety = {
          risk_distribution: riskDist,
          recent_flags: recentFlags.filter((f) => inRange(f.ts)),
        }
      }
      if (reportChecks.pii) {
        sections.pii_report = { scanned: piiScanned, tables: piiTables }
      }
      if (reportChecks.toolCalls) {
        const qs = windowParams(reportFrom, reportTo)
        qs.set("limit", String(AUDIT_LIMIT))
        const [lr, sr] = await Promise.all([
          fetch(`/api/audit/tool-calls?${qs}`),
          fetch(`/api/audit/tool-calls/summary?${windowParams(reportFrom, reportTo)}`),
        ])
        if (!lr.ok) throw new Error(`tool-calls HTTP ${lr.status}`)
        if (!sr.ok) throw new Error(`tool-calls summary HTTP ${sr.status}`)
        sections.agent_tool_calls = buildToolCallSection(await lr.json(), await sr.json())
      }

      if (Object.keys(sections).length === 0) {
        toast("Select at least one section to include in the report.", "info")
        return
      }

      const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = "datapond-compliance-report.json"
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      const audit = sections.query_audit_log as { capped?: boolean } | undefined
      toast(
        audit?.capped
          ? "Report exported. Query audit log capped at the 200 most-recent events."
          : "Compliance report exported.",
        "success",
      )
    } catch (err) {
      toast(`Export failed: ${err instanceof Error ? err.message : "unknown error"}`, "error")
    } finally {
      setExporting(false)
    }
  }

  // The query count is one COUNT; the PII scan walks the catalog (seconds, uncached).
  // Asking stats for both held "Queries today" blank until the scan finished, and ran
  // the same scan twice — pii-report below already does it. So stats skips it, and the
  // PII card counts the columns pii-report found.
  const loadStats = useCallback(() => {
    setStatsLoading(true); setStatsError(null)
    fetch("/api/governance/stats?include_pii=false")
      .then(async (r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setStats)
      .catch((e) => setStatsError(e instanceof Error ? e.message : "failed"))
      .finally(() => setStatsLoading(false))
  }, [])

  const loadPii = useCallback(() => {
    setPiiLoading(true); setPiiError(null)
    fetch("/api/governance/pii-report")
      .then(async (r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d) => { setPiiTables(d.tables ?? []); setPiiScanned(!!d.scanned) })
      .catch((e) => setPiiError(e instanceof Error ? e.message : "failed"))
      .finally(() => setPiiLoading(false))
  }, [])

  useEffect(() => {
    // Deferred a tick, like the audit log below: the loaders set state.
    const t = window.setTimeout(() => { loadStats(); loadPii() }, 0)
    return () => window.clearTimeout(t)
  }, [loadStats, loadPii])

  useEffect(() => {
    const request = window.setTimeout(() => {
      setSafetyLoading(true); setSafetyError(null)
      fetch("/api/governance/ai-safety")
        .then((r) => readJson<{ risk_distribution?: { low: number; medium: number; high: number }; recent_flags?: AiSafetyFlag[] }>(r))
        .then((d) => {
          setRiskDist(d.risk_distribution ?? null)
          setRecentFlags(d.recent_flags ?? [])
        })
        .catch((e) => setSafetyError(e instanceof Error ? e.message : "failed"))
        .finally(() => setSafetyLoading(false))
    }, 0)
    return () => window.clearTimeout(request)
  }, [safetyReload])

  // Audit log — re-fetch when filter changes
  useEffect(() => {
    const request = window.setTimeout(() => {
      setAuditLoading(true); setAuditError(null)
      const qs = new URLSearchParams({ limit: String(AUDIT_PAGE), offset: String(auditOffset) })
      if (eventTypeFilter !== "all") qs.set("event_type", eventTypeFilter)
      fetch(`/api/governance/audit-log?${qs}`)
        .then((r) => readJson<{ items?: AuditLogItem[]; total?: number }>(r))
        .then((d) => {
          // Append past the first page: the table used to ask for 50 at offset 0 and
          // nothing else, so a deployment with more than fifty entries could not reach
          // the fifty-first from this screen at all.
          setAuditItems((prev) => (auditOffset === 0 ? (d.items ?? []) : [...prev, ...(d.items ?? [])]))
          setAuditTotal(d.total ?? 0)
        })
        .catch((e) => setAuditError(e instanceof Error ? e.message : "failed"))
        .finally(() => setAuditLoading(false))
    }, 0)
    return () => window.clearTimeout(request)
  }, [eventTypeFilter, auditOffset, auditReload])

  // Unified activity stream — re-fetch when source filter changes
  useEffect(() => {
    const request = window.setTimeout(() => {
      setActivityLoading(true); setActivityError(null)
      const qs = new URLSearchParams({ limit: "100" })
      if (activitySource !== "all") qs.set("source", activitySource)
      fetch(`/api/governance/audit-stream?${qs}`)
        .then((r) => readJson<{ items?: AuditStreamItem[]; sources?: string[] }>(r))
        .then((d) => {
          setActivityItems(d.items ?? [])
          setActivitySources(d.sources ?? [])
        })
        .catch((e) => { setActivityItems([]); setActivitySources([]); setActivityError(e instanceof Error ? e.message : "failed") })
        .finally(() => setActivityLoading(false))
    }, 0)
    return () => window.clearTimeout(request)
  }, [activitySource, activityReload])

  // client-side search filter on audit items
  const filteredAudit = searchQuery
    ? auditItems.filter((i) => {
        const q = searchQuery.toLowerCase()
        return (
          i.user_id?.toLowerCase().includes(q) ||
          i.user_name?.toLowerCase().includes(q) ||
          i.catalog?.toLowerCase().includes(q) ||
          i.schema_name?.toLowerCase().includes(q) ||
          i.query_text?.toLowerCase().includes(q) ||
          i.status?.toLowerCase().includes(q)
        )
      })
    : auditItems

  // pie chart data
  const pieData = riskDist
    ? [
        { name: "Normal (low)", value: riskDist.low,    color: "var(--dp-good)" },
        { name: "Caution (medium)", value: riskDist.medium, color: "var(--dp-warn)" },
        { name: "High risk (high)", value: riskDist.high,   color: "var(--destructive)" },
      ]
    : []

  const totalRisk = pieData.reduce((s, d) => s + d.value, 0)

  const piiColumnCount = piiTables.reduce((s, t) => s + t.pii_columns.length, 0)

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Governance &amp; Trust</h1>
        <p className="text-muted-foreground text-sm">Data protection, AI safety, and compliance auditing</p>
      </div>

      {/* Stats row — only cards backed by a genuine data source. AI SQL
          execution count and blocked-query count have no dedicated storage
          or enforcement counter yet, so those cards are omitted rather than
          showing a fabricated 0 (see backend/app/api/governance.py). */}
      <div className="grid grid-cols-2 gap-4 max-w-xl">
        <StatCard
          label="Queries today"
          value={stats?.queries_today ?? null}
          icon={<Database className="h-5 w-5" />}
          colorClass="text-[var(--chart-1)]"
          bgClass="bg-[var(--chart-1)]/10"
          loading={statsLoading}
          error={statsError}
          onRetry={loadStats}
        />
        <StatCard
          label="Personal-data columns"
          value={piiScanned ? piiColumnCount : null}
          icon={<ShieldAlert className="h-5 w-5" />}
          colorClass="text-[var(--dp-warn-text)]"
          bgClass="bg-[var(--dp-warn)]/10"
          loading={piiLoading}
          error={piiError}
          onRetry={loadPii}
        />
      </div>

      {/* Tabs */}
      <Tabs value={tab} onValueChange={v => setTab(String(v))}>
        <TabsList>
          <TabsTrigger value="tool-calls">Tool calls</TabsTrigger>
          <TabsTrigger value="audit">Query log</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
          <TabsTrigger value="ai-safety">AI Safety</TabsTrigger>
          <TabsTrigger value="data-protection">Data Protection</TabsTrigger>
          <TabsTrigger value="access-control">Access policies</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
        </TabsList>

        {/* ── Tab: Tool calls (every caller's search, answers, metrics, SQL) ── */}
        <TabsContent value="tool-calls" className="mt-4 space-y-4">
          <ToolCallsTab />
        </TabsContent>

        {/* ── Tab: Access Control (RLS) ─────────────────────────────────── */}
        <TabsContent value="access-control" className="mt-4 space-y-4">
          <AccessPolicies />
        </TabsContent>

        {/* ── Tab: Query log (SQL executions) ──────────────────────────────── */}
        <TabsContent value="audit" className="mt-4 space-y-4">
          {/* Filter bar */}
          <div className="flex flex-col sm:flex-row gap-3">
            <Select items={{ all: "All events", query_executed: "Query executed", query_error: "Query error", query_timeout: "Query timeout" }}
                    value={eventTypeFilter} onValueChange={(v) => {
                // A new filter is a new result set: start it at the top rather than at
                // the offset the previous one had reached.
                setEventTypeFilter(v ?? "all")
                setAuditOffset(0)
              }}>
              <SelectTrigger className="w-full sm:w-52">
                <SelectValue placeholder="Event type" />
              </SelectTrigger>
              <SelectContent>
                {/* Only filters the backend can actually resolve — the audit
                    log is derived solely from query_history.status. The
                    previously-offered ai_sql_generated / pii_detected /
                    login_success / login_failure options always returned 0
                    rows (nothing writes those event types), so they were
                    removed rather than left as dead, misleading filters. */}
                <SelectItem value="all">All events</SelectItem>
                <SelectItem value="query_executed">Query executed</SelectItem>
                <SelectItem value="query_error">Query error</SelectItem>
                <SelectItem value="query_timeout">Query timeout</SelectItem>
              </SelectContent>
            </Select>
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search user, resource, action..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>
            <Button
              variant="outline"
              size="icon"
              aria-label="Refresh query log"
              onClick={() => { setAuditOffset(0); setAuditReload((n) => n + 1) }}
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>

          {/* Summary strip — pass vs. needs-attention within the loaded window.
              Counts describe the rows currently shown; the total/cap is stated
              below the table so a partial window never reads as complete. */}
          {!auditLoading && filteredAudit.length > 0 && (() => {
            const attention = new Set(["error", "failure", "failed", "timeout", "blocked", "차단"])
            const needsAttention = filteredAudit.filter((i) => i.status && attention.has(i.status)).length
            const passed = filteredAudit.length - needsAttention
            return (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <StatPill value={filteredAudit.length} label="shown" />
                {needsAttention > 0 && <StatPill value={needsAttention} label={`error${needsAttention === 1 ? "" : "s"} / timeout`} tone="bad" />}
                <StatPill value={passed} label="passed" tone="good" />
              </div>
            )
          })()}

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-36">Time</TableHead>
                    <TableHead>User</TableHead>
                    <TableHead>Event</TableHead>
                    <TableHead>Target</TableHead>
                    <TableHead className="w-24">Result</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {auditLoading ? (
                    Array.from({ length: 8 }).map((_, i) => (
                      <TableRow key={i}>
                        {Array.from({ length: 5 }).map((_, j) => (
                          <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                        ))}
                      </TableRow>
                    ))
                  ) : auditError && auditItems.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="p-4">
                        <SourceState status="error" what="the query log" error={auditError}
                                     onRetry={() => { setAuditOffset(0); setAuditReload((n) => n + 1) }}>{null}</SourceState>
                      </TableCell>
                    </TableRow>
                  ) : filteredAudit.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center py-12 text-muted-foreground">
                        No audit log entries
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredAudit.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                          {relativeTime(item.created_at)}
                        </TableCell>
                        <TableCell className="text-sm" title={callerLabel(item.user_name, item.user_id).title}>{callerLabel(item.user_name, item.user_id).text}</TableCell>
                        <TableCell><EventBadge type={item.event_type} /></TableCell>
                        <TableCell className="text-sm font-mono text-xs max-w-[200px] truncate">
                          {[item.catalog, item.schema_name].filter(Boolean).join(".") || item.query_text || "—"}
                        </TableCell>
                        <TableCell><ResultBadge result={item.status} /></TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs text-muted-foreground">
              Showing {filteredAudit.length} of {auditTotal} total
              {searchQuery && " — search filters the entries loaded so far"}
            </p>
            {auditItems.length < auditTotal && (
              <Button
                variant="outline"
                size="sm"
                disabled={auditLoading}
                onClick={() => setAuditOffset(auditItems.length)}
              >
                {auditLoading ? "Loading…" : `Load ${Math.min(AUDIT_PAGE, auditTotal - auditItems.length)} more`}
              </Button>
            )}
          </div>
        </TabsContent>

        {/* ── Tab: Activity (unified audit stream) ──────────────────────── */}
        <TabsContent value="activity" className="mt-4 space-y-4">
          <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
            <Select items={{ all: "All sources", query: "Query (SQL executions)", auth: "Auth (logins, policy, denials)", connector: "Connector (sync runs)" }}
                    value={activitySource} onValueChange={(v) => { setActivitySource(v ?? "all"); setAttentionOnly(false) }}>
              <SelectTrigger className="w-full sm:w-52">
                <SelectValue placeholder="Source" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All sources</SelectItem>
                <SelectItem value="query">Query (SQL executions)</SelectItem>
                <SelectItem value="auth">Auth (logins, policy, denials)</SelectItem>
                <SelectItem value="connector">Connector (sync runs)</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              One time-ordered feed across query, auth, and connector events.
            </p>
          </div>

          {/* Summary strip — surface totals and anything that needs attention
              before the raw feed. Source pills double as quick filters; per-source
              counts only read true in the unfiltered ("all") window. */}
          {!activityLoading && activityItems.length > 0 && (() => {
            const needsAttention = activityItems.filter(needsAttentionItem).length
            const bySource: Record<string, number> = { query: 0, auth: 0, connector: 0 }
            for (const i of activityItems) if (i.source in bySource) bySource[i.source] += 1
            const sources: { key: string; label: string }[] = [
              { key: "query", label: "Query" }, { key: "auth", label: "Auth" }, { key: "connector", label: "Connector" },
            ]
            return (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1">
                  <span className="font-semibold tabular-nums">{activityItems.length}</span>
                  <span className="text-muted-foreground">events</span>
                </span>
                <button type="button" disabled={needsAttention === 0} aria-pressed={attentionOnly}
                  onClick={() => setAttentionOnly(a => !a)}
                  title={needsAttention ? (attentionOnly ? "Show every event" : "Show only these") : undefined}
                  className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 transition-colors ${needsAttention > 0 ? "border-destructive/30 bg-destructive/5 text-destructive hover:bg-destructive/10" : "text-muted-foreground"} ${attentionOnly ? "ring-2 ring-destructive/40" : ""}`}>
                  <span className="font-semibold tabular-nums">{needsAttention}</span>
                  <span>need{needsAttention === 1 ? "s" : ""} attention</span>
                </button>
                {activitySource === "all" && (
                  <>
                    <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
                    {sources.map(s => (
                      <button key={s.key} onClick={() => setActivitySource(s.key)}
                        className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 transition-colors hover:border-primary/40 hover:bg-muted/40">
                        <span className="font-semibold tabular-nums">{bySource[s.key]}</span>
                        <span className="text-muted-foreground">{s.label}</span>
                      </button>
                    ))}
                  </>
                )}
                {activitySource !== "all" && (
                  <button onClick={() => setActivitySource("all")}
                    className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-muted-foreground transition-colors hover:border-primary/40 hover:bg-muted/40">
                    Clear filter
                  </button>
                )}
              </div>
            )
          })()}

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-32">Time</TableHead>
                    <TableHead className="w-24">Source</TableHead>
                    <TableHead>Event</TableHead>
                    <TableHead>Actor</TableHead>
                    <TableHead>Target</TableHead>
                    <TableHead className="w-24">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {activityLoading ? (
                    Array.from({ length: 8 }).map((_, i) => (
                      <TableRow key={i}>
                        {Array.from({ length: 6 }).map((_, j) => (
                          <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                        ))}
                      </TableRow>
                    ))
                  ) : activityError ? (
                    <TableRow>
                      <TableCell colSpan={6} className="p-4">
                        <SourceState status="error" what="the activity stream" error={activityError}
                                     onRetry={() => setActivityReload((n) => n + 1)}>{null}</SourceState>
                      </TableCell>
                    </TableRow>
                  ) : activityItems.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center py-12 text-muted-foreground">
                        No activity recorded yet
                      </TableCell>
                    </TableRow>
                  ) : (
                    activityItems.filter(i => !attentionOnly || needsAttentionItem(i)).map((item) => (
                      <TableRow key={`${item.source}-${item.id}`}>
                        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                          {relativeTime(item.created_at)}
                        </TableCell>
                        <TableCell><SourceBadge source={item.source} /></TableCell>
                        <TableCell className="text-sm">
                          <span className="font-medium">{item.event_type}</span>
                          {item.detail && (
                            <span className="block font-mono text-xs text-muted-foreground max-w-[280px] truncate">
                              {item.detail}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm max-w-[160px] truncate" title={callerLabel(item.actor_name, item.actor).title}>{callerLabel(item.actor_name, item.actor).text}</TableCell>
                        <TableCell className="text-sm font-mono text-xs max-w-[200px] truncate">
                          {item.target ?? "—"}
                        </TableCell>
                        <TableCell>{item.status ? <ResultBadge result={item.status} /> : "—"}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {!activityLoading && !activityError && (
            <p className="text-xs text-muted-foreground">
              {activityItems.length} event{activityItems.length === 1 ? "" : "s"}
              {activitySources.length > 0 && <> · sources: {activitySources.join(", ")}</>}
            </p>
          )}
        </TabsContent>

        {/* ── Tab 2: AI Safety ──────────────────────────────────────────── */}
        <TabsContent value="ai-safety" className="mt-4 space-y-4">
          {/* Summary strip — high-risk count leads, before the distribution
              charts. Counts are the real assessed totals from /ai-safety. */}
          {!safetyLoading && riskDist && totalRisk > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <StatPill value={totalRisk} label="assessed" />
              {riskDist.high > 0 && <StatPill value={riskDist.high} label="high risk" tone="bad" />}
              {riskDist.medium > 0 && <StatPill value={riskDist.medium} label="caution" tone="warn" />}
              <StatPill value={riskDist.low} label="normal" tone="good" />
            </div>
          )}

          {safetyError && (
            <SourceState status="error" what="AI safety assessments" error={safetyError}
                         onRetry={() => setSafetyReload((n) => n + 1)}>{null}</SourceState>
          )}
          {!safetyError && <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Pie chart */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Risk Distribution</CardTitle>
              </CardHeader>
              <CardContent>
                {safetyLoading ? (
                  <div className="flex items-center justify-center h-52">
                    <Skeleton className="h-44 w-44 rounded-full" />
                  </div>
                ) : pieData.length === 0 || totalRisk === 0 ? (
                  <p className="text-center text-muted-foreground py-12 text-sm">
                    No AI Safety data
                  </p>
                ) : (
                  <>
                    <ResponsiveContainer width="100%" height={220}>
                      <PieChart>
                        <Pie
                          data={pieData}
                          cx="50%"
                          cy="50%"
                          innerRadius={55}
                          outerRadius={85}
                          paddingAngle={3}
                          dataKey="value"
                          // recharts 3.8.1 draws an animated Pie as nothing at all.
                          // See components/query/chart-renderer.tsx.
                          isAnimationActive={false}
                        >
                          {pieData.map((entry, index) => (
                            <Cell key={index} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip
                          formatter={(v: unknown, name: unknown) => {
                            const count = typeof v === "number" ? v : 0
                            const label = typeof name === "string" ? name : ""
                            return [`${count} (${sharePct(count, totalRisk)})`, label]
                          }}
                        />
                        <Legend />
                      </PieChart>
                    </ResponsiveContainer>
                    {/* distribution percentages */}
                    <div className="grid grid-cols-3 gap-2 mt-2">
                      {pieData.map((d) => (
                        <div key={d.name} className="text-center">
                          <p className="text-lg font-bold" style={{ color: d.color }}>
                            {sharePct(d.value, totalRisk)}
                          </p>
                          <p className="text-xs text-muted-foreground">{d.name}</p>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Recent flags */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Recently Flagged Queries</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {safetyLoading ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))
                ) : recentFlags.length === 0 ? (
                  <p className="text-center text-muted-foreground py-8 text-sm">
                    No flagged queries
                  </p>
                ) : (
                  recentFlags.map((flag, i) => (
                    <div
                      key={i}
                      className="flex flex-col gap-1 p-3 rounded-lg border bg-muted/20"
                    >
                      <div className="flex items-center gap-2">
                        <RiskBadge risk={flag.risk} />
                        <span className="text-xs text-muted-foreground ml-auto">
                          {relativeTime(flag.ts)}
                        </span>
                      </div>
                      <p className="text-xs font-mono text-foreground/80">
                        {truncate(flag.sql_preview, 60)}
                      </p>
                      {flag.reason && <p className="text-xs text-foreground/80">{flag.reason}</p>}
                      <p className="text-xs text-muted-foreground">{flag.user_name || flag.user}</p>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </div>}
        </TabsContent>

        {/* ── Tab 3: Data Protection ───────────────────────────────────── */}
        <TabsContent value="data-protection" className="mt-4 space-y-4">
          <PiiEvidenceSection />

          {/* Summary cards */}
          <div className="grid grid-cols-2 gap-4">
            <Card>
              <CardContent className="pt-5 pb-4">
                <p className="text-sm text-muted-foreground">Tables with personal-data column names</p>
                {piiLoading ? (
                  <Skeleton className="h-8 w-12 mt-1" />
                ) : (
                  <p className="dp-num text-3xl font-bold mt-1 text-primary">{piiScanned ? piiTables.length : "—"}</p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-5 pb-4">
                <p className="text-sm text-muted-foreground">Columns named like personal data</p>
                {piiLoading ? (
                  <Skeleton className="h-8 w-12 mt-1" />
                ) : (
                  <p className="dp-num text-3xl font-bold mt-1 text-[var(--chart-4)]">{piiScanned ? piiColumnCount : "—"}</p>
                )}
              </CardContent>
            </Card>
          </div>

          {/* PII table */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Column names that look like personal data</CardTitle>
              {/* "Tables scanned 1" sat under "23 tables · 23 clean": this list is the
                  column-name check over the catalog, not the value sample above, and
                  holds only tables with a match. */}
              <p className="text-xs text-muted-foreground">
                Read from column names in the catalog, not from values; only tables with a match are listed.
                The sample above is what checks the values.
              </p>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Table name</TableHead>
                    <TableHead>PII columns</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {piiLoading ? (
                    Array.from({ length: 4 }).map((_, i) => (
                      <TableRow key={i}>
                        <TableCell><Skeleton className="h-4 w-32" /></TableCell>
                        <TableCell><Skeleton className="h-4 w-full" /></TableCell>
                      </TableRow>
                    ))
                  ) : piiTables.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={2} className="text-center py-12 text-muted-foreground">
                        {piiScanned
                          ? "0 tables scanned — no PII columns detected."
                          : "No PII scan available on the active query engine" +
                            (typeof caps.query_engine === "string" && caps.query_engine
                              ? ` (${caps.query_engine}).`
                              : ".") +
                            " Column-level PII detection requires a Trino/Polaris catalog."}
                      </TableCell>
                    </TableRow>
                  ) : (
                    piiTables.map((t) => (
                      <TableRow key={t.table}>
                        <TableCell className="font-mono text-sm">{t.table}</TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1.5">
                            {t.pii_columns.map((col) => (
                              <PiiTypeBadge key={col.column} column={col.column} type={col.type} />
                            ))}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Tab 4: Reports ───────────────────────────────────────────── */}
        <TabsContent value="reports" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <FileText className="h-4 w-4" />
                Generate Compliance Report
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Date range */}
              <div className="space-y-2">
                <p className="text-sm font-medium">Date range</p>
                <p className="text-xs text-muted-foreground">Leave both empty for everything on record.</p>
                <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
                  <div className="space-y-1">
                    <Label htmlFor="report-from" className="text-xs text-muted-foreground">Start date</Label>
                    <Input
                      id="report-from"
                      type="date"
                      value={reportFrom}
                      onChange={(e) => setReportFrom(e.target.value)}
                      className="w-44"
                    />
                  </div>
                  <span className="text-muted-foreground text-sm sm:mt-5">~</span>
                  <div className="space-y-1">
                    <Label htmlFor="report-to" className="text-xs text-muted-foreground">End date</Label>
                    <Input
                      id="report-to"
                      type="date"
                      value={reportTo}
                      onChange={(e) => setReportTo(e.target.value)}
                      className="w-44"
                    />
                  </div>
                </div>
              </div>

              {/* Report content checkboxes */}
              <div className="space-y-2">
                <p className="text-sm font-medium">Include in report</p>
                <div className="space-y-2.5">
                  {[
                    { key: "queries",  label: "Full query execution history" },
                    { key: "aiSql",    label: "AI SQL generation and safety assessment" },
                    { key: "pii",      label: "PII detection and masking status" },
                    { key: "toolCalls", label: "Agent tool calls (search, cited answers, SQL) by caller" },
                  ].map(({ key, label }) => (
                    <div key={key} className="flex items-center gap-2">
                      <Checkbox
                        id={`check-${key}`}
                        checked={reportChecks[key as keyof typeof reportChecks]}
                        onCheckedChange={(v) =>
                          setReportChecks((prev) => ({ ...prev, [key]: !!v }))
                        }
                      />
                      <Label htmlFor={`check-${key}`} className="text-sm cursor-pointer">
                        {label}
                      </Label>
                    </div>
                  ))}
                </div>
              </div>

              {/* Note */}
              <p className="text-xs text-muted-foreground bg-muted/40 px-3 py-2 rounded-md">
                Can be used as compliance evidence
              </p>

              {/* Export button */}
              <Button onClick={exportReport} disabled={exporting} className="gap-2">
                {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                Export report (JSON)
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
