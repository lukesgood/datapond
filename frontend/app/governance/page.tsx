"use client"

import { useEffect, useState } from "react"
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
  Sparkles,
  ShieldAlert,
  Ban,
  Lock,
  Search,
  FileText,
  RefreshCw,
} from "lucide-react"
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts"
import type {
  GovernanceStats,
  AuditLogItem,
  PiiTable,
  AiSafetyFlag,
} from "@/lib/api"

// ─── helpers ────────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return `${diff}초 전`
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`
  return `${Math.floor(diff / 86400)}일 전`
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
  const map: Record<string, { label: string; className: string }> = {
    query_executed:    { label: "쿼리 실행",    className: "border-blue-400 text-blue-500" },
    ai_sql_generated:  { label: "AI SQL",       className: "border-violet-400 text-violet-500" },
    pii_detected:      { label: "PII 탐지",     className: "border-amber-400 text-amber-500" },
    login_success:     { label: "로그인 성공",  className: "border-gray-400 text-gray-500" },
    login_failure:     { label: "로그인 실패",  className: "border-red-400 text-red-500" },
  }
  const cfg = map[type] ?? { label: type, className: "border-gray-300 text-gray-400" }
  return (
    <Badge variant="outline" className={cfg.className}>
      {cfg.label}
    </Badge>
  )
}

// ─── result badge ─────────────────────────────────────────────────────────────

function ResultBadge({ result }: { result: string }) {
  if (result === "통과" || result === "pass" || result === "success")
    return <Badge className="bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20 border-0">통과</Badge>
  if (result === "차단" || result === "blocked")
    return <Badge className="bg-red-500/10 text-red-500 hover:bg-red-500/20 border-0">차단</Badge>
  if (result === "마스킹" || result === "masked")
    return <Badge className="bg-amber-500/10 text-yellow-500 hover:bg-amber-500/20 border-0">마스킹</Badge>
  return <Badge variant="secondary">{result}</Badge>
}

// ─── risk badge ───────────────────────────────────────────────────────────────

function RiskBadge({ risk }: { risk: string }) {
  if (risk === "high")
    return <Badge className="bg-red-500/10 text-red-500 border-0">고위험</Badge>
  if (risk === "medium")
    return <Badge className="bg-amber-500/10 text-yellow-500 border-0">주의</Badge>
  return <Badge className="bg-blue-500/10 text-blue-500 border-0">정상</Badge>
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
interface RoleOption { name: string; display_name: string }

const MASK_TYPES = ["full", "partial_email", "partial_ssn", "partial_phone", "hash", "null", "custom"]

function AccessControlTab() {
  const [policies, setPolicies] = useState<RlsPolicy[]>([])
  const [masks, setMasks] = useState<MaskPolicy[]>([])
  const [roles, setRoles] = useState<RoleOption[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  // create-policy form
  const [form, setForm] = useState({
    name: "", catalog_name: "iceberg", schema_name: "", table_name: "",
    filter_expression: "", role_names: "",
  })
  // preview
  const [pvSql, setPvSql] = useState("SELECT * FROM sales.orders")
  const [pvRoles, setPvRoles] = useState("business_analyst")
  const [pvAttrs, setPvAttrs] = useState('{"region":"us-east"}')
  const [pvResult, setPvResult] = useState<any>(null)

  const load = () => {
    setLoading(true); setErr(null)
    Promise.all([
      fetch("/api/governance/rls/policies").then((r) => r.ok ? r.json() : Promise.reject(r.status)),
      fetch("/api/governance/masking/policies").then((r) => r.ok ? r.json() : []),
      fetch("/api/governance/roles").then((r) => r.ok ? r.json() : []),
    ])
      .then(([p, m, ro]) => { setPolicies(p ?? []); setMasks(m ?? []); setRoles(ro ?? []) })
      .catch((e) => setErr(e === 403 || e === 401 ? "admin 권한이 필요합니다" : `로드 실패 (${e})`))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  // Default the policy catalog to the active engine's catalog (Athena →
  // AwsDataCatalog, Trino → iceberg) instead of a hardcoded "iceberg".
  const caps = useCapabilities()
  useEffect(() => {
    const qc = caps.query_catalog
    if (typeof qc === "string" && qc && form.catalog_name === "iceberg") {
      setForm((f) => ({ ...f, catalog_name: qc }))
    }
  }, [caps.query_catalog])

  const createPolicy = async () => {
    setErr(null)
    const body = {
      name: form.name, catalog_name: form.catalog_name, schema_name: form.schema_name,
      table_name: form.table_name, filter_expression: form.filter_expression,
      role_names: form.role_names.split(",").map((s) => s.trim()).filter(Boolean),
    }
    const r = await fetch("/api/governance/rls/policies", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    })
    if (r.ok) { setForm({ ...form, name: "", schema_name: "", table_name: "", filter_expression: "", role_names: "" }); load() }
    else setErr((await r.json().catch(() => ({})))?.detail ?? "생성 실패")
  }

  const togglePolicy = async (p: RlsPolicy) => {
    await fetch(`/api/governance/rls/policies/${p.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !p.enabled }),
    }); load()
  }
  const confirm = useConfirm()
  const deletePolicy = async (id: string) => {
    if (!(await confirm({ title: "정책 삭제", message: "이 RLS 정책을 삭제할까요?", destructive: true, confirmText: "삭제" }))) return
    await fetch(`/api/governance/rls/policies/${id}`, { method: "DELETE" }); load()
  }
  const runPreview = async () => {
    let attrs = {}
    try { attrs = JSON.parse(pvAttrs || "{}") } catch { setPvResult({ error: "attributes JSON 파싱 실패" }); return }
    const r = await fetch("/api/governance/rls/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql: pvSql, roles: pvRoles.split(",").map((s) => s.trim()).filter(Boolean), attributes: attrs }),
    })
    setPvResult(await r.json().catch(() => ({ error: "응답 파싱 실패" })))
  }

  if (loading) return <Skeleton className="h-64" />
  if (err) return (
    <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
      <Lock className="h-5 w-5 mx-auto mb-2" />{err}
    </CardContent></Card>
  )

  return (
    <div className="space-y-4">
      {/* Create policy */}
      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><Lock className="h-4 w-4" />RLS 정책 추가</CardTitle></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <Input placeholder="정책 이름" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Input placeholder="schema (예: sales)" value={form.schema_name} onChange={(e) => setForm({ ...form, schema_name: e.target.value })} />
          <Input placeholder="table (예: orders)" value={form.table_name} onChange={(e) => setForm({ ...form, table_name: e.target.value })} />
          <Input className="md:col-span-2 font-mono text-xs" placeholder="filter (예: region = current_user_attribute('region'))" value={form.filter_expression} onChange={(e) => setForm({ ...form, filter_expression: e.target.value })} />
          <Input placeholder="적용 역할 (쉼표, 예: business_analyst)" value={form.role_names} onChange={(e) => setForm({ ...form, role_names: e.target.value })} />
          <div className="md:col-span-3">
            <Button size="sm" onClick={createPolicy} disabled={!form.name || !form.schema_name || !form.table_name || !form.filter_expression}>정책 생성</Button>
          </div>
        </CardContent>
      </Card>

      {/* Policy list */}
      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-base">RLS 정책 ({policies.length})</CardTitle></CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader><TableRow>
              <TableHead>테이블</TableHead><TableHead>필터식</TableHead><TableHead>역할</TableHead>
              <TableHead>우선순위</TableHead><TableHead>상태</TableHead><TableHead></TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {policies.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-muted-foreground py-6">등록된 정책 없음 — default_deny로 모든 테이블이 차단됩니다.</TableCell></TableRow>}
              {policies.map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="font-mono text-xs">{p.catalog_name}.{p.schema_name}.{p.table_name}</TableCell>
                  <TableCell className="font-mono text-xs max-w-[260px] truncate" title={p.filter_expression}>{p.filter_expression}</TableCell>
                  <TableCell>{p.roles.map((r) => <Badge key={r} variant="secondary" className="text-[10px] mr-1">{r}</Badge>)}{p.exempt_roles.map((r) => <Badge key={r} variant="outline" className="text-[10px] mr-1">면제:{r}</Badge>)}</TableCell>
                  <TableCell className="text-xs">{p.priority}</TableCell>
                  <TableCell><Badge variant={p.enabled ? "secondary" : "outline"} className="text-[10px] cursor-pointer" onClick={() => togglePolicy(p)}>{p.enabled ? "활성" : "비활성"}</Badge></TableCell>
                  <TableCell><Button variant="ghost" size="sm" className="text-red-500 h-7" onClick={() => deletePolicy(p.id)}>삭제</Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Masking list (read + delete) */}
      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-base">컬럼 마스킹 정책 ({masks.length})</CardTitle></CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader><TableRow><TableHead>테이블.컬럼</TableHead><TableHead>마스킹</TableHead><TableHead>역할</TableHead><TableHead>상태</TableHead></TableRow></TableHeader>
            <TableBody>
              {masks.length === 0 && <TableRow><TableCell colSpan={4} className="text-center text-sm text-muted-foreground py-6">마스킹 정책 없음</TableCell></TableRow>}
              {masks.map((m) => (
                <TableRow key={m.id}>
                  <TableCell className="font-mono text-xs">{m.schema_name}.{m.table_name}.{m.column_name}</TableCell>
                  <TableCell><Badge variant="outline" className="text-[10px]">{m.masking_type}</Badge></TableCell>
                  <TableCell>{m.roles.map((r) => <Badge key={r} variant="secondary" className="text-[10px] mr-1">{r}</Badge>)}</TableCell>
                  <TableCell><Badge variant={m.enabled ? "secondary" : "outline"} className="text-[10px]">{m.enabled ? "활성" : "비활성"}</Badge></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Preview / simulate */}
      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><Search className="h-4 w-4" />정책 미리보기 (시뮬레이션)</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <Input className="font-mono text-xs" value={pvSql} onChange={(e) => setPvSql(e.target.value)} placeholder="SQL" />
          <div className="grid gap-3 md:grid-cols-2">
            <Input placeholder="역할 (쉼표)" value={pvRoles} onChange={(e) => setPvRoles(e.target.value)} />
            <Input className="font-mono text-xs" placeholder='attributes JSON' value={pvAttrs} onChange={(e) => setPvAttrs(e.target.value)} />
          </div>
          <Button size="sm" variant="outline" onClick={runPreview}>적용 결과 보기</Button>
          {pvResult && (
            <div className={`rounded-md p-3 text-xs font-mono whitespace-pre-wrap ${pvResult.allowed ? "bg-emerald-500/10" : "bg-red-500/10"}`}>
              {pvResult.error ? `오류: ${pvResult.error}`
                : pvResult.allowed ? `✅ 허용 → ${pvResult.rewritten_sql}`
                : `⛔ 차단: ${pvResult.reason}`}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ─── main page ────────────────────────────────────────────────────────────────

export default function GovernancePage() {
  const { toast } = useToast()
  // stats
  const [stats, setStats] = useState<GovernanceStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(true)

  // audit log
  const [auditItems, setAuditItems] = useState<AuditLogItem[]>([])
  const [auditTotal, setAuditTotal] = useState(0)
  const [auditLoading, setAuditLoading] = useState(true)
  const [eventTypeFilter, setEventTypeFilter] = useState("all")
  const [searchQuery, setSearchQuery] = useState("")

  // pii
  const [piiTables, setPiiTables] = useState<PiiTable[]>([])
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
    blocked: false,
  })

  useEffect(() => {
    fetch("/api/governance/stats")
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {})
      .finally(() => setStatsLoading(false))

    fetch("/api/governance/pii-report")
      .then((r) => r.json())
      .then((d) => setPiiTables(d.tables ?? []))
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
  }, [eventTypeFilter])

  // client-side search filter on audit items
  const filteredAudit = searchQuery
    ? auditItems.filter(
        (i) =>
          i.user_email?.toLowerCase().includes(searchQuery.toLowerCase()) ||
          i.resource?.toLowerCase().includes(searchQuery.toLowerCase()) ||
          i.action?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : auditItems

  // pie chart data
  const pieData = riskDist
    ? [
        { name: "정상 (low)", value: riskDist.low,    color: "#3b82f6" },
        { name: "주의 (medium)", value: riskDist.medium, color: "#f59e0b" },
        { name: "고위험 (high)", value: riskDist.high,   color: "#ef4444" },
      ]
    : []

  const totalRisk = pieData.reduce((s, d) => s + d.value, 0)

  const piiColumnCount = piiTables.reduce((s, t) => s + t.pii_columns.length, 0)

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Governance &amp; Trust</h1>
        <p className="text-muted-foreground text-sm">데이터 보호, AI 안전성, 규정 준수 감사</p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="오늘 쿼리"
          value={stats?.queries_today ?? null}
          icon={<Database className="h-5 w-5" />}
          colorClass="text-blue-500"
          bgClass="bg-blue-500/10"
          loading={statsLoading}
        />
        <StatCard
          label="AI SQL 실행"
          value={stats?.ai_sql_count ?? null}
          icon={<Sparkles className="h-5 w-5" />}
          colorClass="text-violet-500"
          bgClass="bg-violet-500/10"
          loading={statsLoading}
        />
        <StatCard
          label="PII 탐지"
          value={stats?.pii_detections ?? null}
          icon={<ShieldAlert className="h-5 w-5" />}
          colorClass="text-yellow-500"
          bgClass="bg-amber-500/10"
          loading={statsLoading}
        />
        <StatCard
          label="차단 건수"
          value={stats?.blocked_count ?? null}
          icon={<Ban className="h-5 w-5" />}
          colorClass="text-red-500"
          bgClass="bg-red-500/10"
          loading={statsLoading}
        />
      </div>

      {/* Tabs */}
      <Tabs defaultValue="audit">
        <TabsList>
          <TabsTrigger value="audit">Audit Log</TabsTrigger>
          <TabsTrigger value="ai-safety">AI Safety</TabsTrigger>
          <TabsTrigger value="data-protection">Data Protection</TabsTrigger>
          <TabsTrigger value="access-control">Access Control</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
        </TabsList>

        {/* ── Tab: Access Control (RLS) ─────────────────────────────────── */}
        <TabsContent value="access-control" className="mt-4 space-y-4">
          <AccessControlTab />
        </TabsContent>

        {/* ── Tab 1: Audit Log ──────────────────────────────────────────── */}
        <TabsContent value="audit" className="mt-4 space-y-4">
          {/* Filter bar */}
          <div className="flex flex-col sm:flex-row gap-3">
            <Select value={eventTypeFilter} onValueChange={(v) => setEventTypeFilter(v ?? "all")}>
              <SelectTrigger className="w-full sm:w-52">
                <SelectValue placeholder="이벤트 유형" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">전체 이벤트</SelectItem>
                <SelectItem value="query_executed">쿼리 실행</SelectItem>
                <SelectItem value="ai_sql_generated">AI SQL 생성</SelectItem>
                <SelectItem value="pii_detected">PII 탐지</SelectItem>
                <SelectItem value="login_success">로그인 성공</SelectItem>
                <SelectItem value="login_failure">로그인 실패</SelectItem>
              </SelectContent>
            </Select>
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="사용자, 리소스, 액션 검색..."
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
                    <TableHead className="w-36">시각</TableHead>
                    <TableHead>사용자</TableHead>
                    <TableHead>이벤트</TableHead>
                    <TableHead>대상</TableHead>
                    <TableHead className="w-24">결과</TableHead>
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
                        감사 로그가 없습니다
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredAudit.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                          {relativeTime(item.created_at)}
                        </TableCell>
                        <TableCell className="text-sm">{item.user_email}</TableCell>
                        <TableCell><EventBadge type={item.event_type} /></TableCell>
                        <TableCell className="text-sm font-mono text-xs max-w-[200px] truncate">
                          {item.resource}
                        </TableCell>
                        <TableCell><ResultBadge result={item.result} /></TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {!auditLoading && (
            <p className="text-xs text-muted-foreground">
              전체 {auditTotal}건 중 {filteredAudit.length}건 표시
            </p>
          )}
        </TabsContent>

        {/* ── Tab 2: AI Safety ──────────────────────────────────────────── */}
        <TabsContent value="ai-safety" className="mt-4 space-y-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Pie chart */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">위험도 분포</CardTitle>
              </CardHeader>
              <CardContent>
                {safetyLoading ? (
                  <div className="flex items-center justify-center h-52">
                    <Skeleton className="h-44 w-44 rounded-full" />
                  </div>
                ) : pieData.length === 0 || totalRisk === 0 ? (
                  <p className="text-center text-muted-foreground py-12 text-sm">
                    AI Safety 데이터가 없습니다
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
                            return [`${count}건 (${totalRisk > 0 ? Math.round((count / totalRisk) * 100) : 0}%)`, label]
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
                <CardTitle className="text-base">최근 플래그된 쿼리</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {safetyLoading ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))
                ) : recentFlags.length === 0 ? (
                  <p className="text-center text-muted-foreground py-8 text-sm">
                    플래그된 쿼리가 없습니다
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
                <p className="text-sm text-muted-foreground">스캔된 테이블</p>
                {piiLoading ? (
                  <Skeleton className="h-8 w-12 mt-1" />
                ) : (
                  <p className="text-3xl font-bold mt-1 text-blue-500">{piiTables.length}</p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-5 pb-4">
                <p className="text-sm text-muted-foreground">PII 컬럼 수</p>
                {piiLoading ? (
                  <Skeleton className="h-8 w-12 mt-1" />
                ) : (
                  <p className="text-3xl font-bold mt-1 text-violet-500">{piiColumnCount}</p>
                )}
              </CardContent>
            </Card>
          </div>

          {/* PII table */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">PII 탐지 현황</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>테이블명</TableHead>
                    <TableHead>PII 컬럼</TableHead>
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
                        PII 탐지된 테이블이 없습니다
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
                규정 준수 리포트 생성
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Date range */}
              <div className="space-y-2">
                <p className="text-sm font-medium">기간 선택</p>
                <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
                  <div className="space-y-1">
                    <Label htmlFor="report-from" className="text-xs text-muted-foreground">시작일</Label>
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
                    <Label htmlFor="report-to" className="text-xs text-muted-foreground">종료일</Label>
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
                <p className="text-sm font-medium">포함할 내용</p>
                <div className="space-y-2.5">
                  {[
                    { key: "queries",  label: "전체 쿼리 실행 이력" },
                    { key: "aiSql",    label: "AI SQL 생성 및 안전성 평가" },
                    { key: "pii",      label: "PII 탐지 및 마스킹 현황" },
                    { key: "blocked",  label: "접근 차단 이벤트" },
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
                규정 준수 증적(Compliance Evidence)으로 활용 가능합니다
              </p>

              {/* Export button */}
              <Button
                onClick={() => toast("리포트 생성 기능은 준비 중입니다.", "info")}
                className="gap-2"
              >
                <FileText className="h-4 w-4" />
                PDF 내보내기
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
