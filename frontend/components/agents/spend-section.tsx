"use client"

import { useState } from "react"
import { Wallet } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useToast } from "@/lib/toast"
import { formatUsd } from "@/lib/format-usd"
import { parseCap } from "@/lib/caller-budgets"
import { Loading, Section, SectionError, errorText } from "./section"
import { useJson } from "./use-json"

type Usage = { spend: number; requests: number }
type Cap = { max_budget: number | null; spend: number; blocked: boolean }

/** What this agent has cost and its cap. The gateway sees the DataPond user id on
 *  every model call, so the agent's spend is exactly its own. */
export function SpendSection({ accountId }: { accountId: string }) {
  const usage = useJson<Usage>(`/api/service-accounts/${accountId}/usage`)
  const cap = useJson<Cap>(`/api/settings/ai/budgets/${encodeURIComponent(accountId)}`)
  const { toast } = useToast()
  const [draft, setDraft] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [formErr, setFormErr] = useState<string | null>(null)

  const save = async (text: string) => {
    // An empty box clears the cap; anything else must be a valid amount.
    let max: number | null = null
    if (text.trim() !== "") {
      const p = parseCap(text)
      if ("error" in p) { setFormErr(p.error); return }
      max = p.value
    }
    setBusy(true); setFormErr(null)
    try {
      const res = await fetch(`/api/settings/ai/budgets/${encodeURIComponent(accountId)}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ max_budget: max }),
      })
      if (!res.ok) { setFormErr(await errorText(res, "Could not change the cap")); return }
      toast(max === null ? "Cap cleared" : "Cap saved", "success")
      setDraft(null)
      cap.reload()
    } finally { setBusy(false) }
  }

  const current = cap.data?.max_budget ?? null
  return (
    <Section title="Spend" icon={<Wallet className="h-4 w-4 text-primary" />}
             description="A call over the cap is refused (402).">
      {usage.loading ? <Loading what="spend" /> : usage.data ? (
        <p className="text-xs tabular-nums">
          {usage.data.requests === 0
            ? "No model calls yet."
            : `${usage.data.requests} model call${usage.data.requests === 1 ? "" : "s"} · ${formatUsd(usage.data.spend)} spent`}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">Spend is unavailable: {usage.error}.</p>
      )}

      {cap.loading ? <Loading what="cap" /> : cap.error && !cap.data ? (
        <SectionError message={`Cap could not be read: ${cap.error}`} onRetry={cap.reload} />
      ) : (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">Cap</span>
          {draft === null ? (
            <>
              <span className="tabular-nums">{current === null ? "no cap" : formatUsd(current)}</span>
              {cap.data?.blocked && <span className="text-destructive">blocked</span>}
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => { setDraft(current === null ? "" : String(current)); setFormErr(null) }}>
                {current === null ? "Set a cap" : "Edit"}
              </Button>
              {current !== null && (
                <Button size="sm" variant="ghost" className="h-7 text-xs" disabled={busy} onClick={() => void save("")}>Clear</Button>
              )}
            </>
          ) : (
            <>
              <Input value={draft} onChange={e => setDraft(e.target.value)} inputMode="decimal"
                     placeholder="cap in $ (empty clears)" aria-label="Cap in dollars"
                     className="h-7 w-44 text-xs" onKeyDown={e => e.key === "Enter" && void save(draft)} />
              <Button size="sm" className="h-7 text-xs" disabled={busy} onClick={() => void save(draft)}>Save</Button>
              <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => { setDraft(null); setFormErr(null) }}>Cancel</Button>
            </>
          )}
        </div>
      )}
      {formErr && <p className="text-2xs text-destructive">{formErr}</p>}
    </Section>
  )
}
