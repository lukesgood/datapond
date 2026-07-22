"use client"

import { useCallback, useEffect, useState } from "react"
import { useToast } from "@/lib/toast"
import { ErrorBox } from "@/components/ui/error-box"
import { useConfirm } from "@/lib/confirm"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import {
  Sparkles, Plus, Trash2, CheckCircle2, XCircle, Loader2, RefreshCw,
  Eye, EyeOff, Zap, Server, AlertCircle, Star, KeyRound, Copy, DollarSign, CalendarRange,
} from "lucide-react"

// Provider catalog — mirrors PROVIDERS in backend/app/api/ai_backends.py.
// `fields` drives which inputs the Add-backend form shows.
const PROVIDERS: Record<string, {
  label: string
  modelPlaceholder: string
  fields: ("api_base" | "api_key" | "aws")[]
  external: boolean   // sends data outside the cluster (blocked under local-only egress policy)
  hint?: string
}> = {
  bedrock:   { label: "AWS Bedrock",              modelPlaceholder: "us.anthropic.claude-haiku-4-5-20251001-v1:0", fields: ["aws"],              external: true,  hint: "Leave keys blank to use the instance IAM role (EC2/EKS IRSA)." },
  anthropic: { label: "Anthropic API",            modelPlaceholder: "claude-haiku-4-5-20251001",                   fields: ["api_key"],          external: true,  hint: "Requires outbound internet to api.anthropic.com." },
  openai:    { label: "OpenAI",                   modelPlaceholder: "gpt-4o",                                       fields: ["api_key"],          external: true },
  gemini:    { label: "Google Gemini",            modelPlaceholder: "gemini-1.5-pro",                               fields: ["api_key"],          external: true },
  ollama:    { label: "Ollama (self-hosted)",     modelPlaceholder: "qwen2.5-coder:7b",                             fields: ["api_base"],         external: false, hint: "On-prem / air-gap friendly. Point at your Ollama server." },
  vllm:      { label: "vLLM / OpenAI-compatible", modelPlaceholder: "your-model",                                  fields: ["api_base", "api_key"], external: false, hint: "Any in-house OpenAI-compatible endpoint (vLLM, TGI, etc.)." },
}

interface Backend {
  id: string | null
  model_name: string
  model: string
  provider: string
  api_base?: string | null
  is_active: boolean
}

interface GatewayStatus {
  gateway: "healthy" | "unhealthy" | "unreachable" | "unconfigured"
  active: string | null
  backend_count: number
  egress_policy?: "local-only" | "cloud-allowed"
  detail?: string
}

type TestResult = { ok: boolean; latency_ms: number; message: string; testing?: boolean }

const emptyForm = {
  model_name: "",
  provider: "bedrock",
  model: "",
  api_base: "",
  api_key: "",
  aws_region_name: "us-east-1",
  aws_access_key_id: "",
  aws_secret_access_key: "",
  temperature: "",
  max_tokens: "",
  rpm: "",
  tpm: "",
  set_active: true,
}

const numOrUndef = (s: string) => (s.trim() === "" ? undefined : Number(s))

export function AiBackends() {
  const [status, setStatus]     = useState<GatewayStatus | null>(null)
  const [backends, setBackends] = useState<Backend[]>([])
  const [loading, setLoading]   = useState(true)
  const [loadErr, setLoadErr]   = useState<string | null>(null)

  const [tests, setTests]       = useState<Record<string, TestResult>>({})
  const [busy, setBusy]         = useState<string | null>(null)   // model_name currently mutating
  const [actionErr, setActionErr] = useState<string | null>(null) // surfaced delete/activate errors

  const [showAdd, setShowAdd]   = useState(false)
  const [form, setForm]         = useState({ ...emptyForm })
  const [adding, setAdding]     = useState(false)
  const [addErr, setAddErr]     = useState<string | null>(null)
  const [showSecret, setShowSecret] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadErr(null)
    try {
      const [stRes, bkRes] = await Promise.all([
        fetch("/api/settings/ai/status"),
        fetch("/api/settings/ai/backends"),
      ])
      if (stRes.ok) setStatus(await stRes.json())
      if (bkRes.ok) {
        const d = await bkRes.json()
        setBackends(d.backends || [])
      } else {
        const d = await bkRes.json().catch(() => ({}))
        setLoadErr(d.detail || "Failed to load backends from the gateway.")
        setBackends([])
      }
    } catch {
      setLoadErr("Cannot reach the backend API.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => { void load() }, 0)
    return () => clearTimeout(timer)
  }, [load])

  const addBackend = async () => {
    setAdding(true); setAddErr(null)
    try {
      const res = await fetch("/api/settings/ai/backends", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_name: form.model_name.trim(),
          provider: form.provider,
          model: form.model.trim(),
          api_base: form.api_base.trim() || undefined,
          api_key: form.api_key.trim() || undefined,
          aws_region_name: form.aws_region_name.trim() || undefined,
          aws_access_key_id: form.aws_access_key_id.trim() || undefined,
          aws_secret_access_key: form.aws_secret_access_key.trim() || undefined,
          temperature: numOrUndef(form.temperature),
          max_tokens: numOrUndef(form.max_tokens),
          rpm: numOrUndef(form.rpm),
          tpm: numOrUndef(form.tpm),
          set_active: form.set_active,
        }),
      })
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || "Failed to add backend") }
      setShowAdd(false); setForm({ ...emptyForm })
      toast(`Backend '${form.model_name.trim()}' added`, "success")
      await load()
    } catch (e) { setAddErr(e instanceof Error ? e.message : "Failed") }
    finally { setAdding(false) }
  }

  const { toast } = useToast()
  const confirm = useConfirm()
  const deleteBackend = async (b: Backend) => {
    if (!b.id) return
    if (!(await confirm({ title: "Remove backend", message: `Remove backend '${b.model_name}'. This cannot be undone.`, destructive: true, confirmText: "Remove" }))) return
    setBusy(b.model_name); setActionErr(null)
    try {
      const res = await fetch(`/api/settings/ai/backends/${encodeURIComponent(b.id)}`, { method: "DELETE" })
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || `Delete failed (${res.status})`) }
      toast(`Backend '${b.model_name}' removed`, "success")
      await load()
    } catch (e) { setActionErr(e instanceof Error ? e.message : "Delete failed") }
    finally { setBusy(null) }
  }

  const setActive = async (b: Backend) => {
    setBusy(b.model_name); setActionErr(null)
    try {
      const res = await fetch("/api/settings/ai/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_name: b.model_name }),
      })
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || `Activate failed (${res.status})`) }
      toast(`Switched to '${b.model_name}' as the active backend`, "success")
      await load()
    } catch (e) { setActionErr(e instanceof Error ? e.message : "Activate failed") }
    finally { setBusy(null) }
  }

  const testBackend = async (b: Backend) => {
    setTests(t => ({ ...t, [b.model_name]: { ok: false, latency_ms: 0, message: "", testing: true } }))
    try {
      const res = await fetch(`/api/settings/ai/backends/${encodeURIComponent(b.model_name)}/test`, { method: "POST" })
      const d = await res.json()
      setTests(t => ({ ...t, [b.model_name]: { ...d, testing: false } }))
    } catch {
      setTests(t => ({ ...t, [b.model_name]: { ok: false, latency_ms: 0, message: "Request failed", testing: false } }))
    }
  }

  const prov = PROVIDERS[form.provider]
  const localOnly = status?.egress_policy === "local-only"
  // Under a local-only egress policy, external providers are blocked.
  const providerBlocked = localOnly && !!prov?.external
  // First unmet requirement, in field order — drives both the disabled submit and
  // an actionable hint so the button never reads as broken-with-no-reason.
  const formIssue =
    providerBlocked ? "This provider is blocked by the local-only egress policy." :
    !form.model_name.trim() ? "Enter a name for this backend." :
    !form.model.trim() ? "Enter the provider model ID." :
    (prov?.fields.includes("api_base") && !form.api_base.trim()) ? "Enter the API base URL." :
    (form.provider === "bedrock" && !form.aws_region_name.trim()) ? "Enter an AWS region." :
    // api_key is required for anthropic/openai/gemini (vllm allows blank)
    (prov?.fields.includes("api_key") && form.provider !== "vllm" && !form.api_key.trim()) ? "Enter the API key." :
    null

  return (
    <div className="space-y-5">
      {/* Gateway status banner */}
      <GatewayBanner status={status} loading={loading} onRefresh={load} />

      {/* Token & cost usage */}
      <UsagePanel />

      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />Model Backends
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Every provider routes through the LiteLLM gateway. Add a backend, test it, set one active.
          </p>
          {status?.egress_policy && (
            <p className="mt-1">
              <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-medium ${
                localOnly
                  ? "border-[var(--dp-good)]/30 bg-[var(--dp-good)]/10 text-[var(--dp-good)]"
                  : "border-border bg-muted text-muted-foreground"}`}>
                AI egress: {localOnly
                  ? "local-only — external LLMs blocked (no data egress)"
                  : "cloud-allowed — external providers permitted"}
              </span>
            </p>
          )}
        </div>
        <Button size="sm" className="gap-1.5"
          disabled={status?.gateway === "unconfigured"}
          onClick={() => { setForm({ ...emptyForm, provider: localOnly ? "ollama" : "bedrock" }); setAddErr(null); setShowAdd(true) }}>
          <Plus className="h-3.5 w-3.5" />Add Backend
        </Button>
      </div>

      {loadErr && (
        <div className="flex items-center gap-2 rounded-lg border border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/10 px-4 py-2.5 text-xs text-[var(--dp-warn)]">
          <AlertCircle className="h-4 w-4 shrink-0" />{loadErr}
        </div>
      )}
      {actionErr && (
        <div className="flex items-center justify-between gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-2.5 text-xs text-destructive">
          <span className="flex items-center gap-2"><XCircle className="h-4 w-4 shrink-0" />{actionErr}</span>
          <button onClick={() => setActionErr(null)}>✕</button>
        </div>
      )}

      {/* Backend list */}
      {loading ? (
        <div className="space-y-2">{[0, 1].map(i => <Skeleton key={i} className="h-20 rounded-lg" />)}</div>
      ) : backends.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center">
            <Server className="h-8 w-8 text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-sm font-medium">No backends configured</p>
            <p className="text-xs text-muted-foreground mt-1 max-w-md mx-auto">
              {status?.gateway === "unconfigured"
                ? "The LiteLLM gateway is not reachable. Enable litellm in your Helm values."
                : "Add a provider backend (Bedrock, Anthropic, OpenAI, or self-hosted) to enable AI SQL."}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2.5">
          {backends.map(b => {
            const t = tests[b.model_name]
            return (
              <Card key={b.id || b.model_name} className={b.is_active ? "border-primary/40 bg-primary/[0.02]" : ""}>
                <CardContent className="p-4">
                  <div className="flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-sm">{b.model_name}</span>
                        {b.is_active && (
                          <Badge className="h-5 gap-1 bg-primary/10 text-primary border-primary/20 text-[10px]">
                            <Star className="h-2.5 w-2.5 fill-primary" />Active
                          </Badge>
                        )}
                        <Badge variant="secondary" className="h-5 text-[10px]">
                          {PROVIDERS[b.provider]?.label || b.provider}
                        </Badge>
                      </div>
                      <p className="text-[11px] text-muted-foreground font-mono mt-1 truncate">
                        {b.model}{b.api_base ? ` · ${b.api_base}` : ""}
                      </p>
                      {t && !t.testing && (
                        <p className={`text-[11px] mt-1.5 flex items-center gap-1 ${t.ok ? "text-[var(--dp-good)]" : "text-destructive"}`}>
                          {t.ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                          {t.ok ? `OK · ${t.latency_ms}ms` : `Failed · ${t.message}`}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <Button variant="outline" size="sm" className="h-7 text-xs gap-1"
                        disabled={t?.testing} onClick={() => testBackend(b)}>
                        {t?.testing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
                        Test
                      </Button>
                      {!b.is_active && (
                        <Button variant="outline" size="sm" className="h-7 text-xs gap-1"
                          disabled={busy === b.model_name} onClick={() => setActive(b)}>
                          {busy === b.model_name ? <Loader2 className="h-3 w-3 animate-spin" /> : <Star className="h-3 w-3" />}
                          Set Active
                        </Button>
                      )}
                      <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive"
                        disabled={busy === b.model_name || !b.id} aria-label="Remove" title="Remove" onClick={() => deleteBackend(b)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* Virtual keys / budgets / spend */}
      <VirtualKeys backends={backends} />

      {/* Add backend dialog */}
      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>Add Model Backend</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Provider</Label>
                <Select value={form.provider} onValueChange={v => v && setForm(f => ({ ...f, provider: v }))}>
                  <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(PROVIDERS).map(([k, v]) => {
                      const blocked = localOnly && v.external
                      return (
                        <SelectItem key={k} value={k} disabled={blocked}>
                          {v.label}{blocked ? " — blocked (local-only)" : ""}
                        </SelectItem>
                      )
                    })}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Name <span className="text-destructive">*</span></Label>
                <Input className="h-9 font-mono text-sm" placeholder="default"
                  value={form.model_name} onChange={e => setForm(f => ({ ...f, model_name: e.target.value }))} />
              </div>
            </div>

            {providerBlocked && (
              <div className="flex items-start gap-2 rounded-md border border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/10 px-3 py-2 text-[11px] text-[var(--dp-warn)]">
                <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                <span>This environment runs a <b>local-only</b> AI egress policy — external
                providers are blocked to keep data in your environment. Choose Ollama or vLLM, or change
                <code className="mx-1">ai.egressPolicy</code> for this deployment.</span>
              </div>
            )}

            <div className="space-y-1.5">
              <Label className="text-xs">Model <span className="text-destructive">*</span></Label>
              <Input className="h-9 font-mono text-sm" placeholder={prov?.modelPlaceholder}
                value={form.model} onChange={e => setForm(f => ({ ...f, model: e.target.value }))} />
            </div>

            {prov?.fields.includes("api_base") && (
              <div className="space-y-1.5">
                <Label className="text-xs">API Base URL <span className="text-destructive">*</span></Label>
                <Input className="h-9 font-mono text-sm"
                  placeholder={form.provider === "ollama" ? "http://ollama.datapond.svc.cluster.local:11434" : "http://my-llm.internal:8000"}
                  value={form.api_base} onChange={e => setForm(f => ({ ...f, api_base: e.target.value }))} />
              </div>
            )}

            {prov?.fields.includes("aws") && (
              <>
                <div className="space-y-1.5">
                  <Label className="text-xs">AWS Region <span className="text-destructive">*</span></Label>
                  <Input className="h-9 font-mono text-sm" placeholder="us-east-1"
                    value={form.aws_region_name} onChange={e => setForm(f => ({ ...f, aws_region_name: e.target.value }))} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs">Access Key ID</Label>
                    <Input className="h-9 font-mono text-sm" type={showSecret ? "text" : "password"} placeholder="optional (IAM role)"
                      value={form.aws_access_key_id} onChange={e => setForm(f => ({ ...f, aws_access_key_id: e.target.value }))} />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs">Secret Access Key</Label>
                    <Input className="h-9 font-mono text-sm" type={showSecret ? "text" : "password"} placeholder="optional"
                      value={form.aws_secret_access_key} onChange={e => setForm(f => ({ ...f, aws_secret_access_key: e.target.value }))} />
                  </div>
                </div>
              </>
            )}

            {prov?.fields.includes("api_key") && (
              <div className="space-y-1.5">
                <Label className="text-xs">
                  API Key {form.provider !== "vllm" && <span className="text-destructive">*</span>}
                </Label>
                <div className="relative">
                  <Input className="h-9 font-mono text-sm pr-9" type={showSecret ? "text" : "password"} placeholder="sk-…"
                    value={form.api_key} onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))} />
                  <button type="button" className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" tabIndex={-1}
                    onClick={() => setShowSecret(v => !v)}>
                    {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
            )}

            {prov?.hint && <p className="text-[11px] text-muted-foreground">{prov.hint}</p>}

            {/* Advanced per-model params (optional) */}
            <details className="rounded-lg border bg-muted/10 px-3 py-2">
              <summary className="text-xs font-medium cursor-pointer select-none text-muted-foreground">Advanced parameters (optional)</summary>
              <div className="grid grid-cols-2 gap-3 pt-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Temperature</Label>
                  <Input className="h-8 text-sm" type="number" step="0.1" placeholder="0.0–2.0"
                    value={form.temperature} onChange={e => setForm(f => ({ ...f, temperature: e.target.value }))} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Max Tokens</Label>
                  <Input className="h-8 text-sm" type="number" placeholder="e.g. 1024"
                    value={form.max_tokens} onChange={e => setForm(f => ({ ...f, max_tokens: e.target.value }))} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">RPM Limit</Label>
                  <Input className="h-8 text-sm" type="number" placeholder="requests/min"
                    value={form.rpm} onChange={e => setForm(f => ({ ...f, rpm: e.target.value }))} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">TPM Limit</Label>
                  <Input className="h-8 text-sm" type="number" placeholder="tokens/min"
                    value={form.tpm} onChange={e => setForm(f => ({ ...f, tpm: e.target.value }))} />
                </div>
              </div>
            </details>

            <label className="flex items-center gap-2 text-xs cursor-pointer select-none pt-1">
              <input type="checkbox" checked={form.set_active}
                onChange={e => setForm(f => ({ ...f, set_active: e.target.checked }))} />
              Set as active default after creating
            </label>

            {addErr && <ErrorBox msg={addErr} />}
          </div>
          <DialogFooter className="items-center sm:justify-between">
            {/* Tell the admin exactly what is missing rather than a dead disabled button. */}
            <span className="text-[11px] text-muted-foreground flex items-center gap-1.5 mr-auto">
              {formIssue && !addErr && <><AlertCircle className="h-3.5 w-3.5 shrink-0" />{formIssue}</>}
            </span>
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={() => setShowAdd(false)}>Cancel</Button>
              <Button onClick={addBackend} disabled={!!formIssue || adding}>
                {adding ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : null}
                {adding ? "Adding…" : "Add Backend"}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ── Gateway status banner ────────────────────────────────────────────────────────

interface ModelUsage { model: string; spend: number; requests: number; total_tokens: number; prompt_tokens: number; completion_tokens: number }
interface KeyUsage { key_alias: string | null; spend: number; max_budget: number | null; pct: number | null }
interface UserUsage { user: string; spend: number; requests: number; total_tokens: number }
interface Usage { total_spend: number; max_budget: number | null; total_tokens: number; models: ModelUsage[]; keys: KeyUsage[]; users?: UserUsage[]; egress_policy?: string }

const fmt$ = (n: number) => "$" + (n < 0.01 ? n.toFixed(6) : n.toFixed(4))
const fmtN = (n: number) => n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n)

// Shape of GET /api/settings/ai/budget-alerts — covers both per-key breaches and
// the account-wide global budget, which the client-side usage summary cannot see.
interface KeyBudgetAlert { key_alias: string | null; spend: number; max_budget: number; pct: number }
interface GlobalBudget { spend: number; max_budget: number; pct: number; alert: boolean }
interface BudgetAlerts { threshold: number; global: GlobalBudget | null; alerts: KeyBudgetAlert[] }

function UsagePanel() {
  const [u, setU] = useState<Usage | null>(null)
  const [ba, setBa] = useState<BudgetAlerts | null>(null)
  const [loading, setLoading] = useState(true)
  const load = useCallback(() => {
    setLoading(true)
    // Budget alerts are best-effort — a failure here must never blank the usage panel.
    fetch("/api/settings/ai/budget-alerts")
      .then(r => (r.ok ? r.json() : null)).then(setBa).catch(() => setBa(null))
    fetch("/api/settings/ai/usage").then(r => r.json()).then(setU).catch(() => {}).finally(() => setLoading(false))
  }, [])
  useEffect(() => {
    const timer = setTimeout(() => { void load() }, 0)
    return () => clearTimeout(timer)
  }, [load])

  if (loading) return <Skeleton className="h-32 rounded-lg" />
  if (!u) return null
  // Per-key alerts come from the endpoint (same /key/list source the usage summary uses),
  // so this replaces — not duplicates — the old client-side u.keys filter.
  const keyAlerts = ba?.alerts ?? []
  const globalAlert = ba?.global?.alert ? ba.global : null
  return (
    <Card>
      {(globalAlert || keyAlerts.length > 0) && (
        <div className="mx-6 mt-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive flex items-start gap-2">
          <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
          <span>
            {globalAlert && (
              <span className="block">
                <b>Global budget alert:</b> {globalAlert.pct}% used ({fmt$(globalAlert.spend)} / {fmt$(globalAlert.max_budget)}).
              </span>
            )}
            {keyAlerts.length > 0 && (
              <span className="block">
                <b>Budget alert:</b> {keyAlerts.map(a => `${a.key_alias || "key"} ${a.pct}%`).join(", ")} of budget used.
              </span>
            )}
          </span>
        </div>
      )}
      <CardHeader className="pb-3 flex-row items-center justify-between">
        <div>
          <CardTitle className="text-base flex items-center gap-2"><DollarSign className="h-4 w-4 text-primary" />Token & Cost Usage</CardTitle>
          <CardDescription>Spend and token usage across LLM backends (via the LiteLLM gateway).</CardDescription>
        </div>
        <Button size="sm" variant="outline" onClick={load} className="gap-1.5"><RefreshCw className="h-3.5 w-3.5" />Refresh</Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg border p-3">
            <div className="text-[11px] text-muted-foreground">Total spend</div>
            <div className="text-lg font-semibold">{fmt$(u.total_spend)}{u.max_budget ? <span className="text-xs text-muted-foreground"> / {fmt$(u.max_budget)}</span> : null}</div>
          </div>
          <div className="rounded-lg border p-3">
            <div className="text-[11px] text-muted-foreground">Tokens (recent)</div>
            <div className="text-lg font-semibold">{fmtN(u.total_tokens)}</div>
          </div>
          <div className="rounded-lg border p-3">
            <div className="text-[11px] text-muted-foreground">Models</div>
            <div className="text-lg font-semibold">{u.models.length}</div>
          </div>
        </div>

        {u.models.length > 0 && (() => {
          // Rank by spend so the biggest cost driver reads first, and back each
          // row with a faint share bar (spend ÷ top spend) — spend distribution
          // becomes scannable without leaving the table.
          const ranked = [...u.models].sort((a, b) => b.spend - a.spend)
          const maxSpend = Math.max(...ranked.map(m => m.spend), 0)
          return (
          <div>
            <div className="text-xs font-medium mb-1.5">By model</div>
            <div className="rounded-lg border divide-y">
              <div className="grid grid-cols-[1fr_auto_auto_auto] gap-3 px-3 py-1.5 text-[11px] text-muted-foreground">
                <span>Model</span><span className="text-right">Spend</span><span className="text-right">Req</span><span className="text-right">Tokens (in/out)</span>
              </div>
              {ranked.map(m => (
                <div key={m.model} className="relative grid grid-cols-[1fr_auto_auto_auto] gap-3 px-3 py-1.5 text-xs items-center">
                  {maxSpend > 0 && (
                    <span aria-hidden className="pointer-events-none absolute inset-y-0 left-0 bg-primary/[0.06]"
                      style={{ width: `${Math.max(2, (m.spend / maxSpend) * 100)}%` }} />
                  )}
                  <span className="relative font-mono truncate">{m.model}</span>
                  <span className="relative text-right tabular-nums">{fmt$(m.spend)}</span>
                  <span className="relative text-right tabular-nums text-muted-foreground">{m.requests}</span>
                  <span className="relative text-right tabular-nums text-muted-foreground">{fmtN(m.total_tokens)} <span className="opacity-60">({fmtN(m.prompt_tokens)}/{fmtN(m.completion_tokens)})</span></span>
                </div>
              ))}
            </div>
          </div>
          )
        })()}

        {u.users && u.users.length > 0 && (
          <div>
            <div className="text-xs font-medium mb-1.5">By user</div>
            <div className="rounded-lg border divide-y">
              <div className="grid grid-cols-[1fr_auto_auto] gap-3 px-3 py-1.5 text-[11px] text-muted-foreground">
                <span>User</span><span className="text-right">Spend</span><span className="text-right">Req / Tokens</span>
              </div>
              {u.users.map((x, i) => (
                <div key={i} className="grid grid-cols-[1fr_auto_auto] gap-3 px-3 py-1.5 text-xs items-center">
                  <span className="font-mono truncate">{x.user}</span>
                  <span className="text-right">{fmt$(x.spend)}</span>
                  <span className="text-right text-muted-foreground">{x.requests} / {fmtN(x.total_tokens)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {u.keys.filter(k => k.max_budget).length > 0 && (
          <div>
            <div className="text-xs font-medium mb-1.5">Virtual key budgets</div>
            <div className="space-y-2">
              {u.keys.filter(k => k.max_budget).map((k, i) => (
                <div key={i} className="text-xs">
                  <div className="flex justify-between mb-0.5">
                    <span className="font-mono">{k.key_alias || "key"}</span>
                    <span className="text-muted-foreground">{fmt$(k.spend)} / {fmt$(k.max_budget!)} ({k.pct}%)</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                    <div className={`h-full ${(k.pct || 0) >= 90 ? "bg-destructive" : (k.pct || 0) >= 70 ? "bg-[var(--dp-warn)]" : "bg-primary"}`}
                      style={{ width: `${Math.min(100, k.pct || 0)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <SpendReportSection />
      </CardContent>
    </Card>
  )
}

// ── Date-ranged spend report ──────────────────────────────────────────────────────

interface SpendReport { start_date: string; end_date: string; report: unknown[]; detail?: string }

type JsonRecord = Record<string, unknown>

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null
}

function reportRows(report: unknown[]): { label: string; spend: number }[] {
  if (!Array.isArray(report)) return []
  return report.flatMap((entry) => {
    if (!isRecord(entry)) return []
    const label = entry.group_by_day || entry.api_key || entry.model || entry.team_id || entry.date || "—"
    let spend = Number(entry.total_spend ?? entry.spend ?? 0) || 0
    if (!spend && Array.isArray(entry.teams)) {
      spend = entry.teams.reduce<number>((sum, team) =>
        sum + (isRecord(team) ? Number(team.total_spend) || 0 : 0), 0)
    }
    return [{ label: String(label).slice(0, 10), spend }]
  }).filter(row => row.spend > 0 || row.label !== "—")
}

// Lightweight column chart for the date-ranged spend series — no chart lib:
// bars scaled to the peak, the peak day emphasized, a baseline rule so zero
// reads as zero. Kept in the app's inline-bar idiom (matches key-budget bars).
function SpendBars({ rows }: { rows: { label: string; spend: number }[] }) {
  const peak = Math.max(...rows.map(r => r.spend), 0)
  if (peak <= 0) return null
  const peakLabel = rows.reduce((a, b) => (b.spend > a.spend ? b : a), rows[0])
  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 flex items-baseline justify-between text-[11px] text-muted-foreground">
        <span>Daily spend</span>
        <span className="tabular-nums">peak {fmt$(peak)} · {peakLabel.label}</span>
      </div>
      <div className="flex h-24 items-end gap-px overflow-x-auto border-b pb-px">
        {rows.map((r, i) => {
          const isPeak = r.spend === peak
          return (
            <div key={i} title={`${r.label} · ${fmt$(r.spend)}`}
              className="group flex min-w-[3px] flex-1 flex-col justify-end self-stretch">
              <div className={`w-full rounded-t-sm transition-colors ${isPeak ? "bg-primary" : "bg-primary/35 group-hover:bg-primary/60"}`}
                style={{ height: `${Math.max(2, (r.spend / peak) * 100)}%` }} />
            </div>
          )
        })}
      </div>
      {rows.length > 1 && (
        <div className="mt-1 flex justify-between text-[10px] tabular-nums text-muted-foreground">
          <span>{rows[0].label}</span>
          <span>{rows[rows.length - 1].label}</span>
        </div>
      )}
    </div>
  )
}

function SpendReportSection() {
  const [open, setOpen] = useState(false)
  const [start, setStart] = useState("")
  const [end, setEnd] = useState("")
  const [data, setData] = useState<SpendReport | null>(null)
  const [loading, setLoading] = useState(false)
  const load = useCallback(() => {
    setLoading(true)
    const qs = new URLSearchParams()
    if (start) qs.set("start_date", start)
    if (end) qs.set("end_date", end)
    fetch(`/api/settings/ai/spend/report${qs.toString() ? "?" + qs : ""}`)
      .then(r => r.json()).then(setData).catch(() => {}).finally(() => setLoading(false))
  }, [start, end])

  return (
    <div className="rounded-lg border">
      <button onClick={() => { const n = !open; setOpen(n); if (n && !data) load() }}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium">
        <span className="flex items-center gap-1.5"><CalendarRange className="h-3.5 w-3.5 text-muted-foreground" />Spend report (by date range)</span>
        <span className="text-muted-foreground">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="border-t px-3 py-3 space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">Start</Label>
              <Input type="date" value={start} onChange={e => setStart(e.target.value)} className="h-8 text-xs w-[150px]" />
            </div>
            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">End</Label>
              <Input type="date" value={end} onChange={e => setEnd(e.target.value)} className="h-8 text-xs w-[150px]" />
            </div>
            <Button size="sm" variant="outline" onClick={load} disabled={loading} className="gap-1.5">
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}Apply</Button>
          </div>
          {data && (() => {
            const rows = reportRows(data.report)
            const total = rows.reduce((s, r) => s + r.spend, 0)
            return (
              <>
                <div className="text-[11px] text-muted-foreground">
                  {data.start_date} → {data.end_date} · total {fmt$(total)}
                </div>
                {rows.length > 0 ? (
                  <>
                    {rows.length > 1 && <SpendBars rows={rows} />}
                    <div className="rounded-md border divide-y max-h-56 overflow-auto">
                      {rows.map((r, i) => (
                        <div key={i} className="grid grid-cols-[1fr_auto] gap-3 px-3 py-1.5 text-xs">
                          <span className="font-mono truncate">{r.label}</span>
                          <span className="text-right tabular-nums">{fmt$(r.spend)}</span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="text-[11px] text-muted-foreground">
                    No spend rolled up for this range. LiteLLM rolls report data periodically — the live
                    “By model” usage above (from <span className="font-mono">/global/spend/models</span>) is the most current source.
                  </p>
                )}
                {data.detail && <p className="text-[11px] text-[var(--dp-warn)]">{data.detail}</p>}
              </>
            )
          })()}
        </div>
      )}
    </div>
  )
}

function GatewayBanner({ status, loading, onRefresh }: {
  status: GatewayStatus | null; loading: boolean; onRefresh: () => void
}) {
  const g = status?.gateway
  const tone =
    g === "healthy"      ? { dot: "bg-[var(--dp-good)]", text: "text-[var(--dp-good)]", label: "Gateway healthy" } :
    g === "unhealthy"    ? { dot: "bg-[var(--dp-warn)]", text: "text-[var(--dp-warn)]", label: "Gateway degraded" } :
    g === "unconfigured" ? { dot: "bg-muted-foreground/40", text: "text-muted-foreground", label: "Gateway not configured" } :
                           { dot: "bg-destructive", text: "text-destructive", label: "Gateway unreachable" }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <Server className="h-4 w-4 text-muted-foreground" />LiteLLM Gateway
            </CardTitle>
            <CardDescription>Single OpenAI-compatible entry point for all LLM providers</CardDescription>
          </div>
          <Button variant="outline" size="sm" className="gap-1.5" onClick={onRefresh} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg border p-3">
            <div className="flex items-center gap-1.5 mb-1">
              <span className={`h-2 w-2 rounded-full ${loading ? "bg-muted-foreground/30" : tone.dot}`} />
              <span className="text-xs text-muted-foreground">Status</span>
            </div>
            <div className={`text-sm font-semibold ${loading ? "" : tone.text}`}>
              {loading ? "—" : tone.label}
            </div>
          </div>
          <div className="rounded-lg border p-3">
            <span className="text-xs text-muted-foreground">Active backend</span>
            <div className="text-sm font-semibold font-mono mt-1 truncate">
              {loading ? "—" : (status?.active || "none")}
            </div>
          </div>
          <div className="rounded-lg border p-3">
            <span className="text-xs text-muted-foreground">Registered</span>
            <div className="text-sm font-semibold mt-1">
              {loading ? "—" : `${status?.backend_count ?? 0} backend${(status?.backend_count ?? 0) === 1 ? "" : "s"}`}
            </div>
          </div>
        </div>
        {/* Surface the gateway's own reason when it is not healthy — otherwise a
            degraded/unreachable status reads as a dead-end with no cause. */}
        {!loading && status?.detail && g !== "healthy" && (
          <p className={`mt-3 flex items-start gap-1.5 text-[11px] ${tone.text}`}>
            <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-px" />
            <span>{status.detail}</span>
          </p>
        )}
      </CardContent>
    </Card>
  )
}

// ── Virtual keys / budgets / spend ───────────────────────────────────────────────

interface VKey {
  token: string
  key_alias: string | null
  spend: number
  max_budget: number | null
  models: string[]
  rpm_limit: number | null
  tpm_limit: number | null
}

function VirtualKeys({ backends }: { backends: Backend[] }) {
  const [keys, setKeys]       = useState<VKey[]>([])
  const [spend, setSpend]     = useState<{ total_spend: number; keys_with_spend: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy]       = useState<string | null>(null)

  const [showGen, setShowGen] = useState(false)
  const [alias, setAlias]     = useState("")
  const [models, setModels]   = useState<string[]>([])
  const [budget, setBudget]   = useState("")
  const [rpm, setRpm]         = useState("")
  const [tpm, setTpm]         = useState("")
  const [duration, setDuration] = useState("")
  const [genErr, setGenErr]   = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [newKey, setNewKey]   = useState<string | null>(null)
  const [copied, setCopied]   = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [kRes, sRes] = await Promise.all([
        fetch("/api/settings/ai/keys"),
        fetch("/api/settings/ai/spend"),
      ])
      if (kRes.ok) setKeys((await kRes.json()).keys || [])
      if (sRes.ok) setSpend(await sRes.json())
    } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => { void load() }, 0)
    return () => clearTimeout(timer)
  }, [load])

  const generate = async () => {
    setGenerating(true); setGenErr(null); setNewKey(null)
    try {
      const res = await fetch("/api/settings/ai/keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          key_alias: alias.trim(),
          models,
          max_budget: budget.trim() === "" ? undefined : Number(budget),
          rpm_limit: rpm.trim() === "" ? undefined : Number(rpm),
          tpm_limit: tpm.trim() === "" ? undefined : Number(tpm),
          duration: duration.trim() || undefined,
        }),
      })
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || "Failed") }
      const d = await res.json()
      setNewKey(d.key)
      setAlias(""); setModels([]); setBudget(""); setRpm(""); setTpm(""); setDuration("")
      await load()
    } catch (e) { setGenErr(e instanceof Error ? e.message : "Failed") }
    finally { setGenerating(false) }
  }

  const { toast } = useToast()
  const confirm = useConfirm()
  const remove = async (k: VKey) => {
    if (!(await confirm({ title: "Revoke key", message: `Revoke key '${k.key_alias || k.token}'?`, destructive: true, confirmText: "Revoke" }))) return
    setBusy(k.token); setGenErr(null)
    try {
      const res = await fetch(`/api/settings/ai/keys/${encodeURIComponent(k.token)}`, { method: "DELETE" })
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || `Revoke failed (${res.status})`) }
      toast("API key revoked", "success")
      await load()
    } catch (e) { setGenErr(e instanceof Error ? e.message : "Revoke failed") }
    finally { setBusy(null) }
  }

  const toggleModel = (m: string) =>
    setModels(ms => ms.includes(m) ? ms.filter(x => x !== m) : [...ms, m])

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-muted-foreground" />Virtual Keys & Budgets
            </CardTitle>
            <CardDescription>
              Issue API keys per user/team — scoped by model, budget, and rate limits. Tracks usage.
            </CardDescription>
          </div>
          <Button size="sm" className="gap-1.5" onClick={() => { setNewKey(null); setGenErr(null); setShowGen(true) }}>
            <Plus className="h-3.5 w-3.5" />Generate Key
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Spend summary */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border p-3">
            <span className="text-xs text-muted-foreground flex items-center gap-1"><DollarSign className="h-3 w-3" />Total spend</span>
            <div className="text-lg font-bold mt-1">${spend ? spend.total_spend.toFixed(4) : "0.0000"}</div>
          </div>
          <div className="rounded-lg border p-3">
            <span className="text-xs text-muted-foreground">Active keys</span>
            <div className="text-lg font-bold mt-1">{loading ? "—" : keys.length}</div>
          </div>
        </div>

        {!showGen && genErr && <p className="text-xs text-destructive">{genErr}</p>}

        {/* Keys list */}
        {loading ? (
          <Skeleton className="h-16 rounded-lg" />
        ) : keys.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-4">No keys issued yet — add one with Generate Key</p>
        ) : (
          <div className="space-y-2">
            {keys.map(k => {
              const pct = k.max_budget ? Math.min(100, (k.spend / k.max_budget) * 100) : null
              return (
                <div key={k.token} className="rounded-lg border p-3">
                  <div className="flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-sm">{k.key_alias || "(no alias)"}</span>
                        <code className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">{k.token?.slice(0, 12)}…</code>
                        {k.models.length > 0 && <Badge variant="secondary" className="h-4 text-[10px]">{k.models.join(", ")}</Badge>}
                      </div>
                      <p className="text-[11px] text-muted-foreground mt-1 tabular-nums">
                        spend ${Number(k.spend).toFixed(4)}{k.max_budget != null ? ` / $${k.max_budget}` : " · no budget cap"}
                        {k.rpm_limit != null ? ` · ${k.rpm_limit} rpm` : ""}{k.tpm_limit != null ? ` · ${k.tpm_limit} tpm` : ""}
                      </p>
                      {pct != null && (
                        <div className="mt-1.5">
                          <div className="flex items-center justify-between text-[10px] tabular-nums mb-0.5">
                            <span className={pct >= 100 ? "text-destructive font-medium" : "text-muted-foreground"}>
                              {pct >= 100 ? "Budget exhausted" : `${Math.round(pct)}% of budget`}
                            </span>
                            <span className="text-muted-foreground">
                              ${Math.max(0, (k.max_budget || 0) - k.spend).toFixed(2)} left
                            </span>
                          </div>
                          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                            <div className={`h-full rounded-full ${pct >= 90 ? "bg-destructive" : pct >= 70 ? "bg-[var(--dp-warn)]" : "bg-[var(--dp-good)]"}`} style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      )}
                    </div>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive shrink-0"
                      disabled={busy === k.token} aria-label="Revoke" title="Revoke" onClick={() => remove(k)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>

      {/* Generate key dialog */}
      <Dialog open={showGen} onOpenChange={setShowGen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>Generate Virtual Key</DialogTitle></DialogHeader>
          {newKey ? (
            <div className="space-y-3 py-2">
              <div className="rounded-lg border border-[var(--dp-good)]/30 bg-[var(--dp-good)]/10 p-3">
                <p className="text-xs text-[var(--dp-good)] font-medium mb-2">✓ Key generated — shown only this once. Copy it somewhere safe.</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-xs font-mono bg-background border rounded px-2 py-1.5 break-all">{newKey}</code>
                  <Button size="icon" variant="outline" className="h-8 w-8 shrink-0"
                    onClick={() => { navigator.clipboard.writeText(newKey); setCopied(true); setTimeout(() => setCopied(false), 1500) }}>
                    {copied ? <CheckCircle2 className="h-4 w-4 text-[var(--dp-good)]" /> : <Copy className="h-4 w-4" />}
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-3 py-2">
              <div className="space-y-1.5">
                <Label className="text-xs">Alias <span className="text-destructive">*</span></Label>
                <Input className="h-9 text-sm" placeholder="e.g. team-analytics" value={alias} onChange={e => setAlias(e.target.value)} autoFocus />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Allowed models <span className="text-muted-foreground">(leave blank for all)</span></Label>
                {backends.length === 0 ? (
                  <p className="text-[11px] text-muted-foreground">No backends registered — all allowed</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {backends.map(b => (
                      <button key={b.model_name} type="button" onClick={() => toggleModel(b.model_name)}
                        className={`text-[11px] px-2 py-1 rounded border ${models.includes(b.model_name) ? "bg-primary/10 border-primary/30 text-primary" : "bg-muted/30 text-muted-foreground"}`}>
                        {b.model_name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Budget ($)</Label>
                  <Input className="h-9 text-sm" type="number" step="0.01" placeholder="Unlimited" value={budget} onChange={e => setBudget(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">RPM</Label>
                  <Input className="h-9 text-sm" type="number" placeholder="Unlimited" value={rpm} onChange={e => setRpm(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">TPM</Label>
                  <Input className="h-9 text-sm" type="number" placeholder="Unlimited" value={tpm} onChange={e => setTpm(e.target.value)} />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Duration <span className="text-muted-foreground">(e.g. 30d, 24h — leave blank for no expiry)</span></Label>
                <Input className="h-9 text-sm" placeholder="30d" value={duration} onChange={e => setDuration(e.target.value)} />
              </div>
              {genErr && <ErrorBox msg={genErr} />}
            </div>
          )}
          <DialogFooter className={newKey ? undefined : "items-center sm:justify-between"}>
            {newKey ? (
              <Button onClick={() => { setShowGen(false); setNewKey(null) }}>Done</Button>
            ) : (
              <>
                {/* Explain the one required field instead of a silently-disabled button. */}
                <span className="text-[11px] text-muted-foreground flex items-center gap-1.5 mr-auto">
                  {!alias.trim() && !genErr && <><AlertCircle className="h-3.5 w-3.5 shrink-0" />An alias is required — it labels this key in spend reports.</>}
                </span>
                <div className="flex items-center gap-2">
                  <Button variant="outline" onClick={() => setShowGen(false)}>Cancel</Button>
                  <Button onClick={generate} disabled={!alias.trim() || generating}>
                    {generating ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : null}
                    {generating ? "Generating…" : "Generate"}
                  </Button>
                </div>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
