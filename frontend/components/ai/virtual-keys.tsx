"use client"

import { useCallback, useEffect, useState } from "react"
import { Check, Copy, Loader2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorBox } from "@/components/ui/error-box"
import { ChoiceGroup } from "@/components/ui/choice-group"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"

interface VKey {
  token: string; key_alias: string | null; spend: number; max_budget: number | null
  models: string[]; rpm_limit: number | null; tpm_limit: number | null; created_at?: string | null
}

const usd = (n: number | null | undefined) => (n == null ? "—" : `$${n.toFixed(n < 1 ? 4 : 2)}`)
const num = (s: string) => (s.trim() === "" ? null : Number(s))

/** LiteLLM virtual keys: a key an outside tool calls the gateway with directly, with
 *  its own model list, budget and rate limits. The API existed (/settings/ai/keys) with
 *  no screen. These are not DataPond agent keys — those are in Agents, and carry
 *  DataPond permissions; a virtual key reaches models only. */
export function VirtualKeys() {
  const confirm = useConfirm()
  const { toast } = useToast()
  const [keys, setKeys] = useState<VKey[] | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setErr(null)
    try {
      const r = await fetch("/api/settings/ai/keys")
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`)
      setKeys(d.keys ?? [])
      // The route answers 200 with an empty list and a detail when the gateway refused.
      setNote(typeof d.detail === "string" && (d.keys ?? []).length === 0 ? d.detail : null)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read keys")
    }
  }, [])

  useEffect(() => {
    const t = window.setTimeout(() => void load(), 0)
    fetch("/api/settings/ai/backends").then(r => (r.ok ? r.json() : null))
      .then(d => {
        const list: { model_name: string }[] = Array.isArray(d) ? d : d?.backends ?? []
        setModels([...new Set(list.map(b => b.model_name))])
      }).catch(() => {})
    return () => window.clearTimeout(t)
  }, [load])

  const revoke = async (k: VKey) => {
    if (!(await confirm({
      title: `Revoke ${k.key_alias || "this key"}?`,
      message: "Anything calling the gateway with it is refused from now on. This cannot be undone.",
      destructive: true, confirmText: "Revoke key",
    }))) return
    const r = await fetch(`/api/settings/ai/keys/${encodeURIComponent(k.token)}`, { method: "DELETE" })
    if (!r.ok) {
      const d = await r.json().catch(() => ({}))
      toast(typeof d.detail === "string" ? d.detail : `Could not revoke (HTTP ${r.status})`, "error")
      return
    }
    toast(`${k.key_alias || "Key"} revoked`, "success")
    void load()
  }

  return (
    <div className="flex flex-wrap items-start gap-5">
      <div className="min-w-0 flex-[3_1_480px] space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-base font-semibold">Gateway keys{keys ? <span className="text-sm font-normal text-muted-foreground"> · {keys.length}</span> : null}</h3>
          <Button size="sm" onClick={() => setCreating(true)} disabled={creating}>New key</Button>
        </div>
        {err ? (
          <div role="alert"><ErrorBox msg={err} action={<Button size="sm" variant="outline" onClick={load}>Retry</Button>} /></div>
        ) : keys === null ? (
          <Skeleton className="h-40" />
        ) : (
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Models</th>
                  <th className="px-4 py-2 text-right font-medium">Spent / budget</th>
                  <th className="px-4 py-2 font-medium">Limits</th>
                  <th className="px-4 py-2 pr-5" />
                </tr>
              </thead>
              <tbody>
                {keys.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-muted-foreground">
                    {note ? `The gateway did not list keys: ${note}` : "No gateway keys. DataPond features do not need one."}
                  </td></tr>
                )}
                {keys.map(k => {
                  const over = k.max_budget != null && k.spend >= k.max_budget
                  return (
                    <tr key={k.token} className="border-b last:border-0">
                      <td className="px-4 py-2">
                        <div className="font-medium">{k.key_alias || "(no name)"}</div>
                        <div className="font-mono text-2xs text-muted-foreground">{k.token.slice(0, 10)}…</div>
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">{k.models.length ? k.models.join(", ") : "all"}</td>
                      <td className={`dp-num px-4 py-2 text-right text-xs ${over ? "font-semibold text-destructive" : ""}`}>
                        {usd(k.spend)} / {k.max_budget != null ? usd(k.max_budget) : "no cap"}
                      </td>
                      <td className="px-4 py-2 text-xs text-muted-foreground">
                        {[k.rpm_limit != null && `${k.rpm_limit}/min`, k.tpm_limit != null && `${k.tpm_limit.toLocaleString()} tokens/min`].filter(Boolean).join(" · ") || "none"}
                      </td>
                      <td className="px-4 py-2 pr-5 text-right">
                        <Button size="sm" variant="ghost" className="text-destructive" onClick={() => revoke(k)}>Revoke…</Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {creating ? (
        <NewKeyRail models={models} onClose={() => setCreating(false)} onCreated={() => void load()} />
      ) : (
        <ExplainRail label="About gateway keys">
          <RailSection title="What a gateway key is">
            A key an outside tool uses to call the model gateway directly, with an OpenAI-compatible client.
            It reaches models only: no tables, no Knowledge.
          </RailSection>
          <RailSection title="Agents use a different key">
            A DataPond agent key (Agents) carries DataPond permissions, PII mode and audit, and its model use
            is billed to the agent here anyway. Prefer it unless a tool must talk to the gateway itself.
          </RailSection>
          <RailSection title="Caps">
            A key over its budget is refused by the gateway. Spend per key is under Spend.
          </RailSection>
        </ExplainRail>
      )}
    </div>
  )
}

type Duration = "" | "30d" | "90d" | "365d"

function NewKeyRail({ models, onClose, onCreated }: { models: string[]; onClose: () => void; onCreated: () => void }) {
  const [alias, setAlias] = useState("")
  const [picked, setPicked] = useState<string[]>([])
  const [budget, setBudget] = useState("")
  const [rpm, setRpm] = useState("")
  const [tpm, setTpm] = useState("")
  const [duration, setDuration] = useState<Duration>("90d")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [plain, setPlain] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const bad = [budget, rpm, tpm].some(v => v.trim() !== "" && !(Number(v) >= 0))
  const create = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await fetch("/api/settings/ai/keys", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          key_alias: alias.trim(), models: picked, max_budget: num(budget),
          rpm_limit: num(rpm), tpm_limit: num(tpm), duration: duration || null,
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setErr(typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`); return }
      setPlain(d.key ?? null)
      onCreated()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not create the key")
    } finally { setBusy(false) }
  }

  return (
    <aside aria-label="New gateway key" className="min-w-0 flex-[2_1_320px] space-y-4 rounded-xl border border-primary/50 bg-muted/40 p-5 text-sm lg:sticky lg:top-6">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-base font-semibold">New gateway key</h3>
        <Button size="icon-sm" variant="ghost" aria-label="Close" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>

      {plain ? (
        <div className="space-y-3">
          <RailAttention title="Copy it now">It is shown once. The gateway keeps only a hash.</RailAttention>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-md border bg-background px-2 py-1.5 font-mono text-xs">{plain}</code>
            <Button size="icon-sm" variant="outline" aria-label="Copy key"
                    onClick={() => { void navigator.clipboard?.writeText(plain).then(() => setCopied(true)) }}>
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            </Button>
          </div>
          <Button size="sm" onClick={onClose}>Done</Button>
        </div>
      ) : (
        <>
          <fieldset disabled={busy} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="vk-alias">Name</Label>
              <Input id="vk-alias" value={alias} onChange={e => setAlias(e.target.value)} placeholder="reporting-script" />
            </div>
            <div className="space-y-1.5">
              <Label>Models</Label>
              <div role="group" aria-label="Models" className="flex flex-wrap gap-1.5">
                {models.length === 0 && <span className="text-xs text-muted-foreground">No models found; the key will reach all.</span>}
                {models.map(m => {
                  const on = picked.includes(m)
                  return (
                    <button key={m} type="button" aria-pressed={on} onClick={() => setPicked(on ? picked.filter(x => x !== m) : [...picked, m])}
                            className={`h-7 rounded-md border px-2.5 font-mono text-xs ${on ? "border-primary bg-primary/10 font-semibold text-primary" : "bg-card hover:border-primary/50"}`}>{m}</button>
                  )
                })}
              </div>
              <p className="text-xs text-muted-foreground">None chosen means every model.</p>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5"><Label htmlFor="vk-budget">Budget ($)</Label><Input id="vk-budget" inputMode="decimal" value={budget} onChange={e => setBudget(e.target.value)} placeholder="no cap" /></div>
              <div className="space-y-1.5"><Label htmlFor="vk-rpm">Requests/min</Label><Input id="vk-rpm" inputMode="numeric" value={rpm} onChange={e => setRpm(e.target.value)} /></div>
              <div className="space-y-1.5"><Label htmlFor="vk-tpm">Tokens/min</Label><Input id="vk-tpm" inputMode="numeric" value={tpm} onChange={e => setTpm(e.target.value)} /></div>
            </div>
            <div className="space-y-1.5">
              <Label>Expires</Label>
              <ChoiceGroup<Duration> label="Expires" value={duration} onChange={setDuration}
                options={[{ label: "30 days", value: "30d" }, { label: "90 days", value: "90d" }, { label: "1 year", value: "365d" }, { label: "Never", value: "" }]} />
            </div>
          </fieldset>
          <RailSection title="This key">
            Reaches {picked.length ? picked.join(", ") : "every model"}, {budget.trim() ? `stops at $${budget.trim()}` : "with no spending cap"},
            {" "}{duration ? `and expires in ${duration.replace("d", " days")}` : "and never expires"}.
          </RailSection>
          {!budget.trim() && !duration && <RailAttention title="No cap and no expiry">A leaked key can spend without limit until someone revokes it.</RailAttention>}
          {bad && <p role="alert" className="text-xs text-destructive">Budget and limits must be numbers of 0 or more.</p>}
          {err && <p role="alert" className="text-xs text-destructive">{err}</p>}
          <div className="flex gap-2">
            <Button size="sm" onClick={create} disabled={busy || !alias.trim() || bad}>{busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Create key</Button>
            <Button size="sm" variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          </div>
        </>
      )}
    </aside>
  )
}
