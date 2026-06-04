"use client"

import { useCallback, useEffect, useState } from "react"
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
  Eye, EyeOff, Zap, Server, AlertCircle, Star, KeyRound, Copy, DollarSign,
} from "lucide-react"

// Provider catalog — mirrors PROVIDERS in backend/app/api/ai_backends.py.
// `fields` drives which inputs the Add-backend form shows.
const PROVIDERS: Record<string, {
  label: string
  modelPlaceholder: string
  fields: ("api_base" | "api_key" | "aws")[]
  hint?: string
}> = {
  bedrock:   { label: "AWS Bedrock",              modelPlaceholder: "us.anthropic.claude-haiku-4-5-20251001-v1:0", fields: ["aws"],              hint: "Leave keys blank to use the instance IAM role (EC2/EKS IRSA)." },
  anthropic: { label: "Anthropic API",            modelPlaceholder: "claude-haiku-4-5-20251001",                   fields: ["api_key"],          hint: "Requires outbound internet to api.anthropic.com." },
  openai:    { label: "OpenAI",                   modelPlaceholder: "gpt-4o",                                       fields: ["api_key"] },
  gemini:    { label: "Google Gemini",            modelPlaceholder: "gemini-1.5-pro",                               fields: ["api_key"] },
  ollama:    { label: "Ollama (self-hosted)",     modelPlaceholder: "qwen2.5-coder:7b",                             fields: ["api_base"],         hint: "On-prem / air-gap friendly. Point at your Ollama server." },
  vllm:      { label: "vLLM / OpenAI-compatible", modelPlaceholder: "your-model",                                  fields: ["api_base", "api_key"], hint: "Any in-house OpenAI-compatible endpoint (vLLM, TGI, etc.)." },
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

  useEffect(() => { load() }, [load])

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
      await load()
    } catch (e) { setAddErr(e instanceof Error ? e.message : "Failed") }
    finally { setAdding(false) }
  }

  const deleteBackend = async (b: Backend) => {
    if (!b.id) return
    if (!confirm(`Remove backend '${b.model_name}'? This cannot be undone.`)) return
    setBusy(b.model_name)
    try {
      await fetch(`/api/settings/ai/backends/${encodeURIComponent(b.id)}`, { method: "DELETE" })
      await load()
    } finally { setBusy(null) }
  }

  const setActive = async (b: Backend) => {
    setBusy(b.model_name)
    try {
      await fetch("/api/settings/ai/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_name: b.model_name }),
      })
      await load()
    } finally { setBusy(null) }
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
  const formValid = form.model_name.trim() && form.model.trim() &&
    (!prov?.fields.includes("api_base") || form.api_base.trim()) &&
    (form.provider !== "bedrock" || form.aws_region_name.trim())

  return (
    <div className="space-y-5">
      {/* Gateway status banner */}
      <GatewayBanner status={status} loading={loading} onRefresh={load} />

      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />Model Backends
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Every provider routes through the LiteLLM gateway. Add a backend, test it, set one active.
          </p>
        </div>
        <Button size="sm" className="gap-1.5"
          disabled={status?.gateway === "unconfigured"}
          onClick={() => { setForm({ ...emptyForm }); setAddErr(null); setShowAdd(true) }}>
          <Plus className="h-3.5 w-3.5" />Add Backend
        </Button>
      </div>

      {loadErr && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50/50 px-4 py-2.5 text-xs text-amber-700">
          <AlertCircle className="h-4 w-4 shrink-0" />{loadErr}
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
                        <p className={`text-[11px] mt-1.5 flex items-center gap-1 ${t.ok ? "text-green-600" : "text-destructive"}`}>
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
                        disabled={busy === b.model_name || !b.id} title="Remove" onClick={() => deleteBackend(b)}>
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
                    {Object.entries(PROVIDERS).map(([k, v]) => (
                      <SelectItem key={k} value={k}>{v.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Name <span className="text-destructive">*</span></Label>
                <Input className="h-9 font-mono text-sm" placeholder="default"
                  value={form.model_name} onChange={e => setForm(f => ({ ...f, model_name: e.target.value }))} />
              </div>
            </div>

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
              <summary className="text-xs font-medium cursor-pointer select-none text-muted-foreground">고급 파라미터 (선택)</summary>
              <div className="grid grid-cols-2 gap-3 pt-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Temperature</Label>
                  <Input className="h-8 text-sm" type="number" step="0.1" placeholder="0.0–2.0"
                    value={form.temperature} onChange={e => setForm(f => ({ ...f, temperature: e.target.value }))} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Max Tokens</Label>
                  <Input className="h-8 text-sm" type="number" placeholder="예: 1024"
                    value={form.max_tokens} onChange={e => setForm(f => ({ ...f, max_tokens: e.target.value }))} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">RPM 한도</Label>
                  <Input className="h-8 text-sm" type="number" placeholder="requests/min"
                    value={form.rpm} onChange={e => setForm(f => ({ ...f, rpm: e.target.value }))} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">TPM 한도</Label>
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

            {addErr && <p className="text-xs text-destructive">{addErr}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAdd(false)}>Cancel</Button>
            <Button onClick={addBackend} disabled={!formValid || adding}>
              {adding ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : null}
              {adding ? "Adding…" : "Add Backend"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ── Gateway status banner ────────────────────────────────────────────────────────

function GatewayBanner({ status, loading, onRefresh }: {
  status: GatewayStatus | null; loading: boolean; onRefresh: () => void
}) {
  const g = status?.gateway
  const tone =
    g === "healthy"      ? { dot: "bg-green-500", text: "text-green-700", label: "Gateway healthy" } :
    g === "unhealthy"    ? { dot: "bg-amber-400", text: "text-amber-700", label: "Gateway degraded" } :
    g === "unconfigured" ? { dot: "bg-muted-foreground/40", text: "text-muted-foreground", label: "Gateway not configured" } :
                           { dot: "bg-red-500", text: "text-destructive", label: "Gateway unreachable" }

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

  useEffect(() => { load() }, [load])

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

  const remove = async (k: VKey) => {
    if (!confirm(`Revoke key '${k.key_alias || k.token}'?`)) return
    setBusy(k.token)
    try {
      await fetch(`/api/settings/ai/keys/${encodeURIComponent(k.token)}`, { method: "DELETE" })
      await load()
    } finally { setBusy(null) }
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
              사용자/팀별 API 키 발급 — 모델 범위·예산·속도 제한. 사용량 추적.
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

        {/* Keys list */}
        {loading ? (
          <Skeleton className="h-16 rounded-lg" />
        ) : keys.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-4">발급된 키 없음 — Generate Key로 추가</p>
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
                      <p className="text-[11px] text-muted-foreground mt-1">
                        spend ${Number(k.spend).toFixed(4)}{k.max_budget != null ? ` / $${k.max_budget}` : ""}
                        {k.rpm_limit != null ? ` · ${k.rpm_limit} rpm` : ""}{k.tpm_limit != null ? ` · ${k.tpm_limit} tpm` : ""}
                      </p>
                      {pct != null && (
                        <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden mt-1.5">
                          <div className={`h-full rounded-full ${pct >= 90 ? "bg-destructive" : pct >= 70 ? "bg-amber-500" : "bg-green-500"}`} style={{ width: `${pct}%` }} />
                        </div>
                      )}
                    </div>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive shrink-0"
                      disabled={busy === k.token} title="Revoke" onClick={() => remove(k)}>
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
              <div className="rounded-lg border border-green-200 bg-green-50/50 p-3">
                <p className="text-xs text-green-700 font-medium mb-2">✓ 키가 생성됐습니다 — 지금만 표시됩니다. 안전하게 복사하세요.</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-xs font-mono bg-background border rounded px-2 py-1.5 break-all">{newKey}</code>
                  <Button size="icon" variant="outline" className="h-8 w-8 shrink-0"
                    onClick={() => { navigator.clipboard.writeText(newKey); setCopied(true); setTimeout(() => setCopied(false), 1500) }}>
                    {copied ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-3 py-2">
              <div className="space-y-1.5">
                <Label className="text-xs">별칭 (alias) <span className="text-destructive">*</span></Label>
                <Input className="h-9 text-sm" placeholder="예: team-analytics" value={alias} onChange={e => setAlias(e.target.value)} autoFocus />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">허용 모델 <span className="text-muted-foreground">(비우면 전체)</span></Label>
                {backends.length === 0 ? (
                  <p className="text-[11px] text-muted-foreground">등록된 백엔드 없음 — 전체 허용</p>
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
                  <Label className="text-xs">예산 ($)</Label>
                  <Input className="h-9 text-sm" type="number" step="0.01" placeholder="무제한" value={budget} onChange={e => setBudget(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">RPM</Label>
                  <Input className="h-9 text-sm" type="number" placeholder="무제한" value={rpm} onChange={e => setRpm(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">TPM</Label>
                  <Input className="h-9 text-sm" type="number" placeholder="무제한" value={tpm} onChange={e => setTpm(e.target.value)} />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">유효기간 <span className="text-muted-foreground">(예: 30d, 24h — 비우면 무기한)</span></Label>
                <Input className="h-9 text-sm" placeholder="30d" value={duration} onChange={e => setDuration(e.target.value)} />
              </div>
              {genErr && <p className="text-xs text-destructive">{genErr}</p>}
            </div>
          )}
          <DialogFooter>
            {newKey ? (
              <Button onClick={() => { setShowGen(false); setNewKey(null) }}>완료</Button>
            ) : (
              <>
                <Button variant="outline" onClick={() => setShowGen(false)}>Cancel</Button>
                <Button onClick={generate} disabled={!alias.trim() || generating}>
                  {generating ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : null}
                  {generating ? "생성 중…" : "Generate"}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
