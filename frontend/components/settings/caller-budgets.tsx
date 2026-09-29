"use client"

import { useCallback, useEffect, useState } from "react"
import { AlertCircle, Loader2, Wallet } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useToast } from "@/lib/toast"
import { formatUsd } from "@/lib/format-usd"
import { callerLabel } from "@/lib/caller-label"
import {
  budgetStatus, parseCap, unlistedCallers,
  type BudgetStatus, type CallerBudget, type KnownCaller,
} from "@/lib/caller-budgets"

const STATUS: Record<BudgetStatus, { text: string; cls: string }> = {
  blocked: { text: "Blocked", cls: "border-destructive/40 text-destructive" },
  over: { text: "Over cap", cls: "border-destructive/40 text-destructive" },
  ok: { text: "OK", cls: "" },
  uncapped: { text: "No cap", cls: "text-muted-foreground" },
}

/** Per-caller model spend caps (GET/PUT /api/settings/ai/budgets). The caller id the
 *  gateway sees is the DataPond user id, so service accounts and people both appear.
 *  A call over its cap is refused with HTTP 402. */
export function CallerBudgets({ canEdit }: { canEdit: boolean }) {
  const { toast } = useToast()
  const [rows, setRows] = useState<CallerBudget[]>([])
  const [unavailable, setUnavailable] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [known, setKnown] = useState<KnownCaller[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState("")
  const [addId, setAddId] = useState("")
  const [addCap, setAddCap] = useState("")
  const [busy, setBusy] = useState(false)
  const [formErr, setFormErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    setErr(null)
    try {
      const r = await fetch("/api/settings/ai/budgets")
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`)
      const d = await r.json()
      setRows(d.customers ?? []); setUnavailable(d.unavailable ?? null)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load budgets")
    } finally {
      setLoading(false)
    }
  }, [])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  // Admin-only lists for the "add a caller" picker. Best-effort: without them the
  // picker is simply empty, and the table still works.
  useEffect(() => {
    if (!canEdit) return
    void (async () => {
      const out: KnownCaller[] = []
      try {
        const r = await fetch("/api/service-accounts")
        if (r.ok) for (const a of (await r.json()).accounts ?? [])
          out.push({ id: a.id, label: `${a.display_name || a.username} (service account)` })
      } catch { /* picker stays partial */ }
      try {
        const r = await fetch("/api/auth/users")
        if (r.ok) for (const u of await r.json())
          out.push({ id: u.id, label: u.display_name || u.username })
      } catch { /* picker stays partial */ }
      setKnown(out)
    })()
  }, [canEdit])

  const put = async (userId: string, max: number | null, done: string) => {
    setBusy(true); setFormErr(null)
    try {
      const r = await fetch(`/api/settings/ai/budgets/${encodeURIComponent(userId)}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ max_budget: max }),
      })
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`)
      toast(done, "success")
      setEditing(null); setAddId(""); setAddCap("")
      await load()
    } catch (e) {
      setFormErr(e instanceof Error ? e.message : "Could not change the cap")
    } finally {
      setBusy(false)
    }
  }

  const saveEdit = (id: string) => {
    const p = parseCap(draft)
    if ("error" in p) { setFormErr(p.error); return }
    void put(id, p.value, "Cap saved")
  }
  const saveAdd = () => {
    const p = parseCap(addCap)
    if (!addId) { setFormErr("Choose a caller."); return }
    if ("error" in p) { setFormErr(p.error); return }
    void put(addId, p.value, "Cap saved")
  }

  const addable = unlistedCallers(known, rows)

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Wallet className="h-4 w-4 text-primary" />Caller budgets</CardTitle>
        <CardDescription>
          A spend cap per caller. Model calls from a caller at or over its cap are refused (HTTP 402).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />Loading…</div>
        ) : err ? (
          <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />{err}</div>
        ) : unavailable ? (
          <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>Budgets could not be read: {unavailable}. This does not mean no caps are set,
              and it does not show whether any are being enforced.</span>
          </div>
        ) : rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">No caller has spent or been capped yet.</p>
        ) : (
          <div className="divide-y rounded-lg border">
            <div className="grid grid-cols-[1fr_5rem_9rem_5.5rem] gap-3 px-3 py-1.5 text-2xs text-muted-foreground">
              <span>Caller</span><span className="text-right">Spent</span><span className="text-right">Cap</span><span>Status</span>
            </div>
            {rows.map(c => {
              const label = callerLabel(c.alias, c.user_id)
              const st = STATUS[budgetStatus(c)]
              return (
                <div key={c.user_id} className="grid grid-cols-[1fr_5rem_9rem_5.5rem] items-center gap-3 px-3 py-1.5 text-xs">
                  <span className="truncate" title={label.title}>{label.text}</span>
                  <span className="text-right tabular-nums">{formatUsd(c.spend)}</span>
                  <span className="flex items-center justify-end gap-1.5 tabular-nums">
                    {editing === c.user_id ? (
                      <>
                        <Input value={draft} onChange={e => setDraft(e.target.value)} inputMode="decimal"
                               aria-label={`Cap in dollars for ${label.text}`} className="h-7 w-20 text-xs"
                               onKeyDown={e => e.key === "Enter" && saveEdit(c.user_id)} />
                        <button className="text-primary disabled:opacity-40" disabled={busy}
                                onClick={() => saveEdit(c.user_id)}>Save</button>
                        <button className="text-muted-foreground" onClick={() => { setEditing(null); setFormErr(null) }}>Cancel</button>
                      </>
                    ) : (
                      <>
                        <span>{c.max_budget == null ? "—" : formatUsd(c.max_budget)}</span>
                        {canEdit && (
                          <>
                            <button className="text-primary"
                                    onClick={() => { setEditing(c.user_id); setDraft(c.max_budget == null ? "" : String(c.max_budget)); setFormErr(null) }}>Edit</button>
                            {c.max_budget != null && (
                              <button className="text-muted-foreground hover:text-destructive disabled:opacity-40"
                                      disabled={busy} onClick={() => void put(c.user_id, null, "Cap cleared")}>Clear</button>
                            )}
                          </>
                        )}
                      </>
                    )}
                  </span>
                  <span><Badge variant="outline" className={`text-2xs ${st.cls}`}>{st.text}</Badge></span>
                </div>
              )
            })}
          </div>
        )}

        {canEdit && !loading && (
          <div className="flex flex-wrap items-center gap-2">
            <select value={addId} onChange={e => setAddId(e.target.value)} aria-label="Caller to cap"
                    className="h-8 min-w-48 flex-1 rounded-md border bg-background px-2 text-xs">
              <option value="">Set a cap for another caller…</option>
              {addable.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}
            </select>
            <Input value={addCap} onChange={e => setAddCap(e.target.value)} inputMode="decimal"
                   placeholder="cap in $" aria-label="Cap in dollars" className="h-8 w-28 text-xs" />
            <Button size="sm" onClick={saveAdd} disabled={busy || !addId || !addCap.trim()}>Set cap</Button>
          </div>
        )}
        {formErr && <p className="text-2xs text-destructive">{formErr}</p>}
      </CardContent>
    </Card>
  )
}
