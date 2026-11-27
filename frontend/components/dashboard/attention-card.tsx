"use client"

import { useState } from "react"
import Link from "next/link"
import { CheckCircle2, Loader2 } from "lucide-react"
import { OpsActionButtons } from "@/components/dashboard/ops-actions"
import { Button, buttonVariants } from "@/components/ui/button"
import { useToast } from "@/lib/toast"
import type { AttentionItem } from "@/lib/overview"

/** Sync every stale source, one after another, and say how many worked. */
function SyncAll({ ids, onDone }: { ids: string[]; onDone: () => void }) {
  const { toast } = useToast()
  const [done, setDone] = useState<number | null>(null)
  const run = async () => {
    let ok = 0
    setDone(0)
    for (const id of ids) {
      try {
        const res = await fetch(`/api/connectors/${encodeURIComponent(id)}/sync`, {
          method: "POST", credentials: "include",
          headers: { "Content-Type": "application/json" }, body: "{}",
        })
        if (res.ok) ok++
      } catch {}
      setDone(d => (d ?? 0) + 1)
    }
    setDone(null)
    toast(ok === ids.length ? `Synced ${ok} source${ok === 1 ? "" : "s"}` : `Synced ${ok} of ${ids.length}; open Sources for the rest`,
          ok === ids.length ? "success" : "error")
    onDone()
  }
  return (
    <Button size="sm" onClick={() => void run()} disabled={done !== null}>
      {done !== null && <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />}
      {done !== null ? `Syncing ${done + 1} of ${ids.length}` : ids.length === 1 ? "Sync now" : `Sync all ${ids.length}`}
    </Button>
  )
}

function Row({ title, detail, advice, children }: { title: string; detail: string; advice?: string; children?: React.ReactNode }) {
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-[var(--dp-warn)]/20 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">{title}</p>
        <p className="text-xs text-muted-foreground">{detail}</p>
        {advice && <p className="mt-0.5 text-xs">{advice}</p>}
      </div>
      {children && <div className="flex flex-wrap gap-2">{children}</div>}
    </li>
  )
}

/** What needs a person today, each with its fix. With nothing to do it is one quiet line. */
export function AttentionCard({ items, canSync, checkedAt, onChanged }: {
  items: AttentionItem[] | null
  canSync: boolean
  checkedAt: string | null
  onChanged: () => void
}) {
  if (items === null) return null
  if (items.length === 0) {
    return (
      <section aria-label="Needs attention" className="flex items-center gap-2 rounded-xl border bg-card px-5 py-3 text-sm">
        <CheckCircle2 className="h-4 w-4" style={{ color: "var(--dp-good)" }} aria-hidden />
        <span className="font-medium">Nothing needs you right now.</span>
        {checkedAt && <span className="ml-auto text-xs text-muted-foreground">checked {checkedAt}</span>}
      </section>
    )
  }
  return (
    <section aria-label="Needs attention" className="rounded-xl border border-[var(--dp-warn)]/40 bg-card px-5 pt-4 pb-1.5">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className="text-base font-semibold">
          Needs attention <span className="font-medium text-[var(--dp-warn-text)]">· {items.length}</span>
        </h3>
        {checkedAt && <span className="text-xs text-muted-foreground">checked {checkedAt}</span>}
      </div>
      <ul>
        {items.map(item => {
          if (item.kind === "issue") {
            return (
              <Row key={item.key} title={item.title} detail={item.detail} advice={item.advice}>
                <OpsActionButtons actions={item.actions} onDone={onChanged} />
              </Row>
            )
          }
          if (item.kind === "stale") {
            return (
              <li key={item.key} className="border-t border-[var(--dp-warn)]/20 py-2.5">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                  <p className="min-w-0 flex-1 text-sm font-semibold">{item.title}</p>
                  <div className="flex flex-wrap gap-2">
                    <Link href="/connectors?filter=stale" className={buttonVariants({ variant: "outline", size: "sm" })}>Review</Link>
                    {canSync && <SyncAll ids={item.connectionIds} onDone={onChanged} />}
                  </div>
                </div>
                {/* Each source with why it is stale, so the reason is read here, not guessed. */}
                <ul className="mt-1.5 space-y-1.5">
                  {item.sources.map(src => (
                    <li key={src.id} className="text-xs">
                      <Link href={`/connectors/connections/${encodeURIComponent(src.id)}`} className="font-medium hover:text-primary hover:underline">
                        {src.name}
                      </Link>
                      {src.reasons.length > 0 && <span className="text-muted-foreground"> — {src.reasons.join(" ")}</span>}
                    </li>
                  ))}
                </ul>
              </li>
            )
          }
          return (
            <Row key={item.key} title={item.title} detail={item.detail}>
              <Link href={item.href} className={buttonVariants({ variant: "outline", size: "sm" })}>Open agent</Link>
            </Row>
          )
        })}
      </ul>
    </section>
  )
}
