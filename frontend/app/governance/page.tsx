"use client"

import { useCallback, useEffect, useState } from "react"
import { useCapabilities } from "@/lib/capabilities"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
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
  DollarSign,
  ExternalLink,
} from "lucide-react"
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts"
import type {
  GovernanceStats,
  AuditLogItem,
  AuditStreamItem,
  PiiTable,
  AiSafetyFlag,
} from "@/lib/api"

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
}

function StatCard({ label, value, icon, colorClass, bgClass, loading }: StatCardProps) {
  return (
    <Card>
      <CardContent className="pt-5 pb-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{label}</p>
            {loading ? (
              <Skeleton className="h-8 w-16 mt-1" />
            ) : (
              <p className={`text-3xl font-bold mt-1 ${colorClass}`}>{value ?? 0}</p>
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
    query_timeout:     { label: "Query timeout",      className: "border-[var(--dp-warn)]/40 text-[var(--dp-warn)]" },
  }
  const cfg = map[type] ?? { label: type, className: "border-gray-300 text-gray-400" }
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
  const cfg = map[source] ?? { label: source, className: "border-gray-300 text-gray-400" }
  return (
    <Badge variant="outline" className={cfg.className}>
      {cfg.label}
    </Badge>
  )
}

// ─── result badge ─────────────────────────────────────────────────────────────

function ResultBadge({ result }: { result: string }) {
  if (result === "통과" || result === "pass" || result === "success")
    return <Badge className="bg-[var(--dp-good)]/10 text-[var(--dp-good)] border-0">Passed</Badge>
  if (result === "failure" || result === "failed")
    return <Badge className="bg-destructive/10 text-destructive border-0">Failed</Badge>
  if (result === "error")
    return <Badge className="bg-destructive/10 text-destructive border-0">Error</Badge>
  if (result === "timeout")
    return <Badge className="bg-[var(--dp-warn)]/10 text-[var(--dp-warn)] border-0">Timeout</Badge>
  if (result === "차단" || result === "blocked")
    return <Badge className="bg-destructive/10 text-destructive border-0">Blocked</Badge>
  if (result === "마스킹" || result === "masked")
    return <Badge className="bg-[var(--dp-warn)]/10 text-[var(--dp-warn)] border-0">Masked</Badge>
  return <Badge variant="secondary">{result}</Badge>
}

// ─── risk badge ───────────────────────────────────────────────────────────────

function RiskBadge({ risk }: { risk: string }) {
  if (risk === "high")
    return <Badge className="bg-destructive/10 text-destructive border-0">High risk</Badge>
  if (risk === "medium")
    return <Badge className="bg-[var(--dp-warn)]/10 text-[var(--dp-warn)] border-0">Caution</Badge>
  return <Badge className="bg-[var(--dp-good)]/10 text-[var(--dp-good)] border-0">Normal</Badge>
}

// ─── PII type color ───────────────────────────────────────────────────────────

const PII_COLORS: Record<string, string> = {
  email:   "bg-blue-500/10 text-blue-500",
  phone:   "bg-emerald-500/10 text-emerald-600",
  ssn:     "bg-red-500/10 text-red-500",
  card:    "bg-red-500/10 text-red-500",
  name:    "bg-gray-500/10 text-gray-500",
  address: "bg-gray-500/10 text-gray-500",
  dob:     "bg-violet-500/10 text-violet-500",
}

function PiiTypeBadge({ column, type }: { column: string; type: string }) {
  const cls = PII_COLORS[type.toLowerCase()] ?? "bg-gray-500/10 text-gray-500"
  return (
    <Badge className={`${cls} border-0 gap-1`}>
      <Lock className="h-2.5 w-2.5" />
      {column}
      <span className="opacity-60 text-[10px]">({type})</span>
    </Badge>
  )
}

// ─── Access Control (RLS) tab ───────────────────────────────────────────────

interface RlsPolicy {
  id: string; catalog_name: string; schema_name: string; table_name: string
  filter_expression: string; priority: number; enabled: boolean
  roles: string[]; exempt_roles: string[]
}
interface MaskPolicy {
  id: string; catalog_name: string; schema_name: string; table_name: string
  column_name: string; masking_type: string; enabled: boolean; roles: string[]
}
interface PreviewResult {
  allowed?: boolean
  rewritten_sql?: string
  reason?: string
  error?: string
}

type DefaultDenyState = "enabled" | "disabled" | "unknown"

function AccessControlTab() {
  const [policies, setPolicies] = useState<RlsPolicy[]>([])
  const [masks, setMasks] = useState<MaskPolicy[]>([])
  const [defaultDeny, setDefaultDeny] = useState<DefaultDenyState>("unknown")
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  // create-policy form
  const [form, setForm] = useState({
    name: "", catalog_name: "iceberg", schema_name: "", table_name: "",
    filter_expression: "", role_names: "",
  })
  // create-mask form
  const [maskForm, setMaskForm] = useState<{
    name: string; catalog_name: string; schema_name: string; table_name: string
    column_name: string; masking_type: string; custom_expression: string; role_names: string
  }>({
    name: "", catalog_name: "iceberg", schema_name: "", table_name: "",
    column_name: "", masking_type: "full", custom_expression: "", role_names: "",
  })
  const [maskErr, setMaskErr] = useState<string | null>(null)
  // preview
  const [pvSql, setPvSql] = useState("SELECT * FROM sales.orders")
  const [pvRoles, setPvRoles] = useState("business_analyst")
  const [pvAttrs, setPvAttrs] = useState('{"region":"us-east"}')
  const [pvResult, setPvResult] = useState<PreviewResult | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setErr(null); setDefaultDeny("unknown")
    try {
      const [policyResponse, maskResponse, rulesResponse] = await Promise.all([
        fetch("/api/governance/rls/policies"),
        fetch("/api/governance/masking/policies"),
        fetch("/api/governance/rls/trino-rules"),
      ])
      if (!policyResponse.ok) throw policyResponse.status
      if (!maskResponse.ok) throw maskResponse.status
      const policyData: RlsPolicy[] = await policyResponse.json()
      const maskData: MaskPolicy[] = await maskResponse.json()
      setPolicies(policyData ?? [])
      setMasks(maskData ?? [])

      if (rulesResponse.ok) {
        const rulesData: unknown = await rulesResponse.json()
        const summary = rulesData && typeof rulesData === "object"
          ? (rulesData as { summary?: unknown }).summary
          : null
        const value = summary && typeof summary === "object"
          ? (summary as { default_deny?: unknown }).default_deny
          : undefined
        setDefaultDeny(value === true ? "enabled" : value === false ? "disabled" : "unknown")
      }
    } catch (error) {
      setPolicies([])
      setMasks([])
      setDefaultDeny("unknown")
      setErr(error === 403 || error === 401 ? "Admin permission required" : `Failed to load (${String(error)})`)
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(initial)
  }, [load])

  // Apply the runtime catalog at submission time. This preserves user-entered
  // values while keeping the default aligned with Athena/Glue or Trino/Polaris.
  const caps = useCapabilities()
  const queryCatalog = typeof caps.query_catalog === "string" && caps.query_catalog ? caps.query_catalog : "iceberg"

  const createPolicy = async () => {
    setErr(null)
    const body = {
      name: form.name, catalog_name: form.catalog_name === "iceberg" ? queryCatalog : form.catalog_name, schema_name: form.schema_name,
      table_name: form.table_name, filter_expression: form.filter_expression,
      role_names: form.role_names.split(",").map((s) => s.trim()).filter(Boolean),
    }
    const r = await fetch("/api/governance/rls/policies", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    })
    if (r.ok) { setForm({ ...form, name: "", schema_name: "", table_name: "", filter_expression: "", role_names: "" }); load() }
    else setErr((await r.json().catch(() => ({})))?.detail ?? "Failed to create")
  }

  const togglePolicy = async (p: RlsPolicy) => {
    await fetch(`/api/governance/rls/policies/${p.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !p.enabled }),
    }); load()
  }
  const confirm = useConfirm()
  const deletePolicy = async (id: string) => {
    if (!(await confirm({ title: "Delete policy", message: "Delete this RLS policy?", destructive: true, confirmText: "Delete" }))) return
    await fetch(`/api/governance/rls/policies/${id}`, { method: "DELETE" }); load()
  }

  const createMask = async () => {
    setMaskErr(null)
    const body = {
      name: maskForm.name, catalog_name: maskForm.catalog_name === "iceberg" ? queryCatalog : maskForm.catalog_name, schema_name: maskForm.schema_name,
      table_name: maskForm.table_name, column_name: maskForm.column_name,
      masking_type: maskForm.masking_type,
      custom_expression: maskForm.masking_type === "custom" ? maskForm.custom_expression : null,
      role_names: maskForm.role_names.split(",").map((s) => s.trim()).filter(Boolean),
    }
    const r = await fetch("/api/governance/masking/policies", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    })
    if (r.ok) { setMaskForm({ ...maskForm, name: "", schema_name: "", table_name: "", column_name: "", custom_expression: "", role_names: "" }); load() }
    else setMaskErr((await r.json().catch(() => ({})))?.detail ?? "Failed to create")
  }
  const deleteMask = async (id: string) => {
    if (!(await confirm({ title: "Delete masking policy", message: "Delete this column masking policy?", destructive: true, confirmText: "Delete" }))) return
    await fetch(`/api/governance/masking/policies/${id}`, { method: "DELETE" }); load()
  }
  const runPreview = async () => {
    let attrs: Record<string, unknown> = {}
    try {
      const parsed: unknown = JSON.parse(pvAttrs || "{}")
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Attributes must be an object")
      attrs = parsed as Record<string, unknown>
    } catch { setPvResult({ error: "Failed to parse attributes JSON" }); return }
    const r = await fetch("/api/governance/rls/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql: pvSql, roles: pvRoles.split(",").map((s) => s.trim()).filter(Boolean), attributes: attrs }),
    })
    setPvResult(await r.json().catch(() => ({ error: "Failed to parse response" })))
  }

  if (loading) return <Skeleton className="h-64" />
  if (err) return (
    <Card role="alert" aria-live="polite"><CardContent className="py-8 text-center text-sm text-muted-foreground">
      <Lock className="h-5 w-5 mx-auto mb-2" />{err}
    </CardContent></Card>
  )

  const enforcementState: "enabled" | "disabled" | "unknown" = caps.rls === true
    ? "enabled"
    : caps.rls === false
      ? "disabled"
      : "unknown"
  const enforcementEnabled = enforcementState === "enabled"
  const defaultDenyExplanation = defaultDeny === "enabled"
    ? enforcementEnabled
      ? "Tables without a matching policy are denied by the DataPond query API."
      : "The setting is configured, but it is inactive while query API enforcement is not enabled."
    : defaultDeny === "disabled"
      ? "Tables without a matching policy are not denied by default."
      : "The server did not return a default-deny value, so unmatched-table behavior cannot be confirmed."

  return (
    <div className="space-y-4">
      <Card className={enforcementEnabled ? "border-[var(--dp-good)]/30" : enforcementState === "disabled" ? "border-[var(--dp-warn)]/30" : "border-muted"}>
        <CardContent className="py-4 text-sm">
          <p className="font-medium">Query API enforcement: {enforcementState}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            This tab manages and previews policy records; records shown here do not by themselves prove that queries are enforced.
            {enforcementEnabled
              ? " The deployment reports that active row filters and column masks are applied to SQL submitted through DataPond's query API."
              : enforcementState === "disabled"
                ? " The deployment reports that query API enforcement is disabled."
                : " The capability response is unavailable or omitted this value, so query API enforcement cannot be confirmed."}
            {" "}Direct query-engine and object-store access remains outside this UI policy boundary.
          </p>
          <p className="mt-2 text-xs">
            <span className="font-medium">Default-deny setting: {defaultDeny}.</span>{" "}
            <span className="text-muted-foreground">{defaultDenyExplanation}</span>
          </p>
        </CardContent>
      </Card>

      {/* Create policy */}
      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><Lock className="h-4 w-4" />Add RLS Policy</CardTitle></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <Input placeholder="Policy name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Input placeholder="schema (e.g. sales)" value={form.schema_name} onChange={(e) => setForm({ ...form, schema_name: e.target.value })} />
          <Input placeholder="table (e.g. orders)" value={form.table_name} onChange={(e) => setForm({ ...form, table_name: e.target.value })} />
          <Input className="md:col-span-2 font-mono text-xs" placeholder="filter (e.g. region = current_user_attribute('region'))" value={form.filter_expression} onChange={(e) => setForm({ ...form, filter_expression: e.target.value })} />
          <Input placeholder="Roles to apply (comma-separated, e.g. business_analyst)" value={form.role_names} onChange={(e) => setForm({ ...form, role_names: e.target.value })} />
          <div className="md:col-span-3">
            <Button size="sm" onClick={createPolicy} disabled={!form.name || !form.schema_name || !form.table_name || !form.filter_expression}>Create policy</Button>
          </div>
        </CardContent>
      </Card>

      {/* Policy list */}
      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-base">RLS Policies ({policies.length})</CardTitle></CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader><TableRow>
              <TableHead>Table</TableHead><TableHead>Filter expression</TableHead><TableHead>Roles</TableHead>
              <TableHead>Priority</TableHead><TableHead>Status</TableHead><TableHead></TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {policies.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-muted-foreground py-6">No RLS policies registered. Default-deny is {defaultDeny}; {defaultDenyExplanation}</TableCell></TableRow>}
              {policies.map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="font-mono text-xs">{p.catalog_name}.{p.schema_name}.{p.table_name}</TableCell>
                  <TableCell className="font-mono text-xs max-w-[260px] truncate" title={p.filter_expression}>{p.filter_expression}</TableCell>
                  <TableCell>{p.roles.map((r) => <Badge key={r} variant="secondary" className="text-[10px] mr-1">{r}</Badge>)}{p.exempt_roles.map((r) => <Badge key={r} variant="outline" className="text-[10px] mr-1">Exempt: {r}</Badge>)}</TableCell>
                  <TableCell className="text-xs">{p.priority}</TableCell>
                  <TableCell><Badge variant={p.enabled ? "secondary" : "outline"} className="text-[10px] cursor-pointer" onClick={() => togglePolicy(p)}>{p.enabled ? "Active" : "Inactive"}</Badge></TableCell>
                  <TableCell><Button variant="ghost" size="sm" className="text-destructive h-7" onClick={() => deletePolicy(p.id)}>Delete</Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Masking policies (create / list / delete) */}
      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-base">Column Masking Policies ({masks.length})</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {/* Create form — mirrors the RLS form; masking has no update, so edit = delete + recreate */}
          <div className="grid gap-2 md:grid-cols-2">
            <Input placeholder="Policy name" value={maskForm.name} onChange={(e) => setMaskForm({ ...maskForm, name: e.target.value })} />
            <Select value={maskForm.masking_type} onValueChange={(v) => setMaskForm({ ...maskForm, masking_type: v ?? "full" })}>
              <SelectTrigger><SelectValue placeholder="Masking type" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="full">Full (redact entirely)</SelectItem>
                <SelectItem value="partial_email">Partial — email</SelectItem>
                <SelectItem value="partial_ssn">Partial — SSN</SelectItem>
                <SelectItem value="partial_phone">Partial — phone</SelectItem>
                <SelectItem value="hash">Hash</SelectItem>
                <SelectItem value="null">Null out</SelectItem>
                <SelectItem value="custom">Custom expression</SelectItem>
              </SelectContent>
            </Select>
            <Input placeholder="schema (e.g. sales)" value={maskForm.schema_name} onChange={(e) => setMaskForm({ ...maskForm, schema_name: e.target.value })} />
            <Input placeholder="table (e.g. customers)" value={maskForm.table_name} onChange={(e) => setMaskForm({ ...maskForm, table_name: e.target.value })} />
            <Input placeholder="column (e.g. email)" value={maskForm.column_name} onChange={(e) => setMaskForm({ ...maskForm, column_name: e.target.value })} />
            <Input placeholder="Roles to mask for (comma-separated)" value={maskForm.role_names} onChange={(e) => setMaskForm({ ...maskForm, role_names: e.target.value })} />
            {maskForm.masking_type === "custom" && (
              <Input className="md:col-span-2 font-mono text-xs" placeholder="custom SQL expression (e.g. regexp_replace(email, '.+@', '***@'))" value={maskForm.custom_expression} onChange={(e) => setMaskForm({ ...maskForm, custom_expression: e.target.value })} />
            )}
          </div>
          <div className="flex items-center gap-3">
            <Button size="sm" onClick={createMask}
              disabled={!maskForm.name || !maskForm.schema_name || !maskForm.table_name || !maskForm.column_name || (maskForm.masking_type === "custom" && !maskForm.custom_expression)}>
              Create masking policy
            </Button>
            {maskErr && <span role="alert" aria-live="polite" className="text-xs text-destructive">{maskErr}</span>}
          </div>

          <Table>
            <TableHeader><TableRow><TableHead>Table.Column</TableHead><TableHead>Masking</TableHead><TableHead>Roles</TableHead><TableHead>Status</TableHead><TableHead className="w-16"></TableHead></TableRow></TableHeader>
            <TableBody>
              {masks.length === 0 && <TableRow><TableCell colSpan={5} className="text-center text-sm text-muted-foreground py-6">No masking policies</TableCell></TableRow>}
              {masks.map((m) => (
                <TableRow key={m.id}>
                  <TableCell className="font-mono text-xs">{m.schema_name}.{m.table_name}.{m.column_name}</TableCell>
                  <TableCell><Badge variant="outline" className="text-[10px]">{m.masking_type}</Badge></TableCell>
                  <TableCell>{m.roles.map((r) => <Badge key={r} variant="secondary" className="text-[10px] mr-1">{r}</Badge>)}</TableCell>
                  <TableCell><Badge variant={m.enabled ? "secondary" : "outline"} className="text-[10px]">{m.enabled ? "Active" : "Inactive"}</Badge></TableCell>
                  <TableCell><Button variant="ghost" size="sm" className="text-destructive h-7" onClick={() => deleteMask(m.id)}>Delete</Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Preview / simulate */}
      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><Search className="h-4 w-4" />Policy Preview (Simulation)</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <Input className="font-mono text-xs" value={pvSql} onChange={(e) => setPvSql(e.target.value)} placeholder="SQL" />
          <div className="grid gap-3 md:grid-cols-2">
            <Input placeholder="Roles (comma-separated)" value={pvRoles} onChange={(e) => setPvRoles(e.target.value)} />
            <Input className="font-mono text-xs" placeholder='attributes JSON' value={pvAttrs} onChange={(e) => setPvAttrs(e.target.value)} />
          </div>
          <Button size="sm" variant="outline" onClick={runPreview}>Run preview</Button>
          {pvResult && (
            <div role={pvResult.error ? "alert" : undefined} aria-live={pvResult.error ? "polite" : undefined} className={`rounded-md p-3 text-xs font-mono whitespace-pre-wrap ${pvResult.allowed ? "bg-emerald-500/10" : "bg-red-500/10"}`}>
              {pvResult.error ? `Error: ${pvResult.error}`
                : pvResult.allowed ? `✅ Allowed → ${pvResult.rewritten_sql}`
                : `⛔ Blocked: ${pvResult.reason}`}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Cost (AI spend attribution) tab ───────────────────────────────────────

// Matches GET /api/settings/ai/usage (backend/app/api/ai_backends.py) —
// aggregated live from the LiteLLM gateway (/global/spend, /global/spend/models,
// /spend/logs, /key/list). Per-user spend is the "cost attribution" story:
// `users` is keyed by the DataPond user (via the `user` payload field / metadata),
// not by LiteLLM API key.
interface AiUsageModel {
  model: string
  spend: number
  requests: number
  total_tokens: number
  prompt_tokens: number
  completion_tokens: number
}
interface AiUsageUser {
  user: string
  spend: number
  requests: number
  total_tokens: number
}
interface AiUsageKey {
  key_alias: string | null
  spend: number
  max_budget: number | null
  pct: number | null
}
interface AiUsage {
  total_spend: number
  max_budget: number | null
  models: AiUsageModel[]
  users: AiUsageUser[]
  keys: AiUsageKey[]
  total_tokens: number
}

function fmtUsd(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: n < 1 ? 4 : 2 })}`
}

function CostTab() {
  const caps = useCapabilities()
  const [usage, setUsage] = useState<AiUsage | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetch("/api/settings/ai/usage")
      .then((r) => r.ok ? r.json() : Promise.reject(r.status))
      .then(setUsage)
      .catch((e) => setErr(`Failed to load AI usage (${e})`))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Skeleton className="h-64" />
  if (err) return (
    <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
      <DollarSign className="h-5 w-5 mx-auto mb-2" />{err}
    </CardContent></Card>
  )

  const hasSpend = !!usage && usage.total_spend > 0
  const budgetPct = usage?.max_budget ? Math.round((usage.total_spend / usage.max_budget) * 100) : null

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-5 pb-4">
            <p className="text-sm text-muted-foreground">Total AI spend</p>
            <p className="dp-num text-3xl font-bold mt-1 text-[var(--chart-1)]">
              {usage ? fmtUsd(usage.total_spend) : "$0.00"}
            </p>
            {usage?.max_budget != null && (
              <p className="text-xs text-muted-foreground mt-1">
                {budgetPct}% of {fmtUsd(usage.max_budget)} budget
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5 pb-4">
            <p className="text-sm text-muted-foreground">Total tokens</p>
            <p className="dp-num text-3xl font-bold mt-1 text-[var(--chart-2)]">
              {(usage?.total_tokens ?? 0).toLocaleString()}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5 pb-4">
            <p className="text-sm text-muted-foreground">Users attributed</p>
            <p className="dp-num text-3xl font-bold mt-1 text-[var(--chart-4)]">
              {usage?.users.length ?? 0}
            </p>
          </CardContent>
        </Card>
      </div>

      {!hasSpend ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            <DollarSign className="h-5 w-5 mx-auto mb-2" />
            No AI spend recorded yet — usage and provider-reported cost appear here once requests flow through the configured LiteLLM gateway.
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Per-user spend — cost attribution */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <DollarSign className="h-4 w-4" />
                Spend by user
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User</TableHead>
                    <TableHead className="text-right">Spend</TableHead>
                    <TableHead className="text-right">Requests</TableHead>
                    <TableHead className="text-right">Tokens</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {usage!.users.length === 0 ? (
                    <TableRow><TableCell colSpan={4} className="text-center text-sm text-muted-foreground py-6">No per-user spend logs yet</TableCell></TableRow>
                  ) : (
                    usage!.users.map((u) => (
                      <TableRow key={u.user}>
                        <TableCell className="text-sm">{u.user === "unattributed" ? <span className="text-muted-foreground italic">unattributed</span> : u.user}</TableCell>
                        <TableCell className="dp-num text-right">{fmtUsd(u.spend)}</TableCell>
                        <TableCell className="dp-num text-right">{u.requests.toLocaleString()}</TableCell>
                        <TableCell className="dp-num text-right">{u.total_tokens.toLocaleString()}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Per-model spend */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Spend by model</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Model</TableHead>
                    <TableHead className="text-right">Spend</TableHead>
                    <TableHead className="text-right">Requests</TableHead>
                    <TableHead className="text-right">Tokens</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {usage!.models.length === 0 ? (
                    <TableRow><TableCell colSpan={4} className="text-center text-sm text-muted-foreground py-6">No per-model spend logs yet</TableCell></TableRow>
                  ) : (
                    usage!.models.map((m) => (
                      <TableRow key={m.model}>
                        <TableCell className="font-mono text-xs">{m.model}</TableCell>
                        <TableCell className="dp-num text-right">{fmtUsd(m.spend)}</TableCell>
                        <TableCell className="dp-num text-right">{m.requests.toLocaleString()}</TableCell>
                        <TableCell className="dp-num text-right">{m.total_tokens.toLocaleString()}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}

      {caps.query_engine === "athena" && (
        <Card>
          <CardContent className="py-4 flex items-start gap-3">
          <ExternalLink className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
          <p className="text-xs text-muted-foreground">
            Athena query scan cost (estimated at $5/TB) is tracked separately in the{" "}
            <code className="font-mono">DataPond</code> CloudWatch namespace, on the{" "}
            <code className="font-mono">&lt;name_prefix&gt;-foundation</code> dashboard
            (see <code className="font-mono">terraform/cloudwatch.tf</code>) — it isn&rsquo;t exposed via a
            backend API yet, so it isn&rsquo;t rendered here. Open{" "}
            <a
              href="https://console.aws.amazon.com/cloudwatch/home#dashboards"
              target="_blank"
              rel="noreferrer"
              className="underline hover:text-foreground"
            >
              CloudWatch Dashboards
            </a>{" "}
            to view it.
          </p>
        </CardContent>
      </Card>
      )}
    </div>
  )
}

// ─── main page ────────────────────────────────────────────────────────────────

export default function GovernancePage() {
  const { toast } = useToast()
  const caps = useCapabilities()
  // stats
  const [stats, setStats] = useState<GovernanceStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(true)

  // audit log
  const [auditItems, setAuditItems] = useState<AuditLogItem[]>([])
  const [auditTotal, setAuditTotal] = useState(0)
  const [auditLoading, setAuditLoading] = useState(true)
  const [eventTypeFilter, setEventTypeFilter] = useState("all")
  const [searchQuery, setSearchQuery] = useState("")

  // unified activity stream (query + auth + connector)
  const [activityItems, setActivityItems] = useState<AuditStreamItem[]>([])
  const [activityLoading, setActivityLoading] = useState(true)
  const [activitySource, setActivitySource] = useState("all")
  const [activitySources, setActivitySources] = useState<string[]>([])

  // pii
  const [piiTables, setPiiTables] = useState<PiiTable[]>([])
  const [piiScanned, setPiiScanned] = useState(false)  // did a real scan run? (vs engine unsupported)
  const [piiLoading, setPiiLoading] = useState(true)

  // ai safety
  const [riskDist, setRiskDist] = useState<{ low: number; medium: number; high: number } | null>(null)
  const [recentFlags, setRecentFlags] = useState<AiSafetyFlag[]>([])
  const [safetyLoading, setSafetyLoading] = useState(true)

  // reports state
  const [reportFrom, setReportFrom] = useState("")
  const [reportTo, setReportTo] = useState("")
  const [reportChecks, setReportChecks] = useState({
    queries: true,
    aiSql: true,
    pii: true,
  })
  const [exporting, setExporting] = useState(false)

  // Assemble a compliance report (JSON) from the sections that are checked.
  // Each section comes from its real governance dataset — the query audit log
  // is fetched fresh (the API caps at 200 rows / newest-first, so we surface a
  // `capped` flag when we hit it); AI-SQL safety, PII, and the blocked summary
  // are current snapshots already loaded on the page. No placeholders.
  const AUDIT_LIMIT = 200
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
        note: "AI-SQL safety and PII sections are current snapshots; only the query audit log is time-scoped per event.",
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

  useEffect(() => {
    fetch("/api/governance/stats")
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {})
      .finally(() => setStatsLoading(false))

    fetch("/api/governance/pii-report")
      .then((r) => r.json())
      .then((d) => { setPiiTables(d.tables ?? []); setPiiScanned(!!d.scanned) })
      .catch(() => {})
      .finally(() => setPiiLoading(false))

    fetch("/api/governance/ai-safety")
      .then((r) => r.json())
      .then((d) => {
        setRiskDist(d.risk_distribution ?? null)
        setRecentFlags(d.recent_flags ?? [])
      })
      .catch(() => {})
      .finally(() => setSafetyLoading(false))
  }, [])

  // Audit log — re-fetch when filter changes
  useEffect(() => {
    const request = window.setTimeout(() => {
      setAuditLoading(true)
      const qs = new URLSearchParams({ limit: "50", offset: "0" })
      if (eventTypeFilter !== "all") qs.set("event_type", eventTypeFilter)
      fetch(`/api/governance/audit-log?${qs}`)
        .then((r) => r.json())
        .then((d) => {
          setAuditItems(d.items ?? [])
          setAuditTotal(d.total ?? 0)
        })
        .catch(() => {})
        .finally(() => setAuditLoading(false))
    }, 0)
    return () => window.clearTimeout(request)
  }, [eventTypeFilter])

  // Unified activity stream — re-fetch when source filter changes
  useEffect(() => {
    const request = window.setTimeout(() => {
      setActivityLoading(true)
      const qs = new URLSearchParams({ limit: "100" })
      if (activitySource !== "all") qs.set("source", activitySource)
      fetch(`/api/governance/audit-stream?${qs}`)
        .then((r) => r.json())
        .then((d) => {
          setActivityItems(d.items ?? [])
          setActivitySources(d.sources ?? [])
        })
        .catch(() => { setActivityItems([]); setActivitySources([]) })
        .finally(() => setActivityLoading(false))
    }, 0)
    return () => window.clearTimeout(request)
  }, [activitySource])

  // client-side search filter on audit items
  const filteredAudit = searchQuery
    ? auditItems.filter((i) => {
        const q = searchQuery.toLowerCase()
        return (
          i.user_id?.toLowerCase().includes(q) ||
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
        />
        <StatCard
          label="PII detections"
          value={stats?.pii_detections ?? null}
          icon={<ShieldAlert className="h-5 w-5" />}
          colorClass="text-[var(--dp-warn)]"
          bgClass="bg-[var(--dp-warn)]/10"
          loading={statsLoading}
        />
      </div>

      {/* Tabs */}
      <Tabs defaultValue="audit">
        <TabsList>
          <TabsTrigger value="audit">Audit Log</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
          <TabsTrigger value="ai-safety">AI Safety</TabsTrigger>
          <TabsTrigger value="data-protection">Data Protection</TabsTrigger>
          <TabsTrigger value="access-control">Access Control</TabsTrigger>
          <TabsTrigger value="cost">Cost</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
        </TabsList>

        {/* ── Tab: Access Control (RLS) ─────────────────────────────────── */}
        <TabsContent value="access-control" className="mt-4 space-y-4">
          <AccessControlTab />
        </TabsContent>

        {/* ── Tab: Cost (AI spend attribution) ─────────────────────────── */}
        <TabsContent value="cost" className="mt-4 space-y-4">
          <CostTab />
        </TabsContent>

        {/* ── Tab 1: Audit Log ──────────────────────────────────────────── */}
        <TabsContent value="audit" className="mt-4 space-y-4">
          {/* Filter bar */}
          <div className="flex flex-col sm:flex-row gap-3">
            <Select value={eventTypeFilter} onValueChange={(v) => setEventTypeFilter(v ?? "all")}>
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
              onClick={() => {
                setAuditLoading(true)
                const qs = new URLSearchParams({ limit: "50", offset: "0" })
                if (eventTypeFilter !== "all") qs.set("event_type", eventTypeFilter)
                fetch(`/api/governance/audit-log?${qs}`)
                  .then((r) => r.json())
                  .then((d) => { setAuditItems(d.items ?? []); setAuditTotal(d.total ?? 0) })
                  .catch(() => {})
                  .finally(() => setAuditLoading(false))
              }}
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>

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
                        <TableCell className="text-sm">{item.user_id ?? "—"}</TableCell>
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

          {!auditLoading && (
            <p className="text-xs text-muted-foreground">
              Showing {filteredAudit.length} of {auditTotal} total
            </p>
          )}
        </TabsContent>

        {/* ── Tab: Activity (unified audit stream) ──────────────────────── */}
        <TabsContent value="activity" className="mt-4 space-y-4">
          <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
            <Select value={activitySource} onValueChange={(v) => setActivitySource(v ?? "all")}>
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
                  ) : activityItems.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center py-12 text-muted-foreground">
                        No activity recorded yet
                      </TableCell>
                    </TableRow>
                  ) : (
                    activityItems.map((item) => (
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
                        <TableCell className="text-sm max-w-[160px] truncate">{item.actor ?? "—"}</TableCell>
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

          {!activityLoading && (
            <p className="text-xs text-muted-foreground">
              {activityItems.length} event{activityItems.length === 1 ? "" : "s"}
              {activitySources.length > 0 && <> · sources: {activitySources.join(", ")}</>}
            </p>
          )}
        </TabsContent>

        {/* ── Tab 2: AI Safety ──────────────────────────────────────────── */}
        <TabsContent value="ai-safety" className="mt-4 space-y-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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
                        >
                          {pieData.map((entry, index) => (
                            <Cell key={index} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip
                          formatter={(v: unknown, name: unknown) => {
                            const count = typeof v === "number" ? v : 0
                            const label = typeof name === "string" ? name : ""
                            return [`${count} (${totalRisk > 0 ? Math.round((count / totalRisk) * 100) : 0}%)`, label]
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
                            {totalRisk > 0 ? Math.round((d.value / totalRisk) * 100) : 0}%
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
                      <p className="text-xs text-muted-foreground">{flag.user}</p>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ── Tab 3: Data Protection ───────────────────────────────────── */}
        <TabsContent value="data-protection" className="mt-4 space-y-4">
          {/* Summary cards */}
          <div className="grid grid-cols-2 gap-4">
            <Card>
              <CardContent className="pt-5 pb-4">
                <p className="text-sm text-muted-foreground">Tables scanned</p>
                {piiLoading ? (
                  <Skeleton className="h-8 w-12 mt-1" />
                ) : (
                  <p className="dp-num text-3xl font-bold mt-1 text-primary">{piiScanned ? piiTables.length : "—"}</p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-5 pb-4">
                <p className="text-sm text-muted-foreground">PII columns</p>
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
              <CardTitle className="text-base">PII Detection Status</CardTitle>
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
