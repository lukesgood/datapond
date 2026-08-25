"use client"

import { useCallback, useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { DollarSign, Loader2 } from "lucide-react"

type AppRow = { app: string; spend: number; requests: number; total_tokens: number }
type Mine = { spend: number; requests: number; total_tokens: number; models: string[]; apps: AppRow[] }

const LABELS: Record<string, string> = {
  ai_chat: "Assistant", ai_sql: "Ask AI", ai_rag: "Cited answers",
  ai_embed: "Embedding", ai_rerank: "Rerank", untagged: "Untagged",
}

/** What the signed-in user has spent on models.
 *
 *  The deployment-wide usage view needs spend:read, which is the permission to see
 *  *everyone's* — an operator's question. A role that can spend was left with no way
 *  to see its own, which is the wrong half to withhold: attribution exists so a
 *  person can be accountable for their own use.
 */
export function MySpend() {
  const [m, setM] = useState<Mine | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/settings/ai/usage/me")
      if (r.ok) setM(await r.json())
    } catch { /* the card simply does not appear */ } finally {
      setLoading(false)
    }
  }, [])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])

  if (loading) {
    return (
      <Card><CardContent className="flex items-center gap-1.5 py-6 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />Loading your usage…
      </CardContent></Card>
    )
  }
  if (!m) return null

  const fmt$ = (n: number) => n >= 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(6)}`
  const fmtN = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <DollarSign className="h-4 w-4 text-primary" />Your model usage
        </CardTitle>
        <CardDescription>
          Only yours. What the whole deployment spent is in AI Gateway, and needs a
          different permission.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          {[["Spend", fmt$(m.spend)], ["Requests", fmtN(m.requests)],
            ["Tokens", fmtN(m.total_tokens)]].map(([k, v]) => (
            <div key={k} className="rounded-lg border p-3">
              <div className="text-[11px] text-muted-foreground">{k}</div>
              <div className="text-lg font-semibold tabular-nums">{v}</div>
            </div>
          ))}
        </div>
        {m.requests === 0 ? (
          <p className="text-xs text-muted-foreground">
            Nothing recorded against your account yet.
          </p>
        ) : (
          <div className="divide-y rounded-lg border">
            {m.apps.map(a => (
              <div key={a.app} className="flex items-center justify-between px-3 py-1.5 text-xs">
                <span>{LABELS[a.app] ?? a.app}</span>
                <span className="flex gap-4 tabular-nums text-muted-foreground">
                  <span>{fmtN(a.requests)} req</span>
                  <span className="w-16 text-right font-medium text-foreground">{fmt$(a.spend)}</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
