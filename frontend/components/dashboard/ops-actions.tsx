"use client"

import { useState } from "react"
import Link from "next/link"
import { Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"
import type { OpsAction } from "@/lib/ops-status"

async function errorText(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === "string") return body.detail
  } catch {}
  return `HTTP ${res.status}`
}

/** Buttons for a list of OpsAction. Recreate asks in-page first; both API actions report the
 *  result in a toast and call `onDone` so the caller can reload its status or history. */
export function OpsActionButtons({ actions, onDone }: { actions: OpsAction[]; onDone?: () => void }) {
  const confirm = useConfirm()
  const { toast } = useToast()
  const [busy, setBusy] = useState<string | null>(null)

  const run = async (action: OpsAction, key: string) => {
    if (action.type === "link") return
    if (action.type === "recreate") {
      const ok = await confirm({
        title: "Recreate target table?",
        message: `Drop the lake table for ${action.table} and re-sync it from the source? Queries on it fail for the few seconds the sync takes.`,
        confirmText: "Drop and re-sync",
        destructive: true,
      })
      if (!ok) return
    }
    setBusy(key)
    try {
      const url = action.type === "recreate"
        ? `/api/connectors/${encodeURIComponent(action.connectionId)}/tables/${encodeURIComponent(action.table)}/recreate`
        : `/api/connectors/${encodeURIComponent(action.connectionId)}/sync`
      const res = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: action.type === "sync" && action.table
          ? JSON.stringify({ source_table: action.table, sync_mode: "full" })
          : action.type === "sync" ? JSON.stringify({}) : undefined,
      })
      if (!res.ok) {
        toast(`${action.label} failed: ${await errorText(res)}`, "error")
      } else {
        const body = await res.json().catch(() => ({}))
        const rows = typeof body?.rows_processed === "number" ? ` (${body.rows_processed.toLocaleString("en-US")} rows)` : ""
        toast(action.type === "recreate" && body?.recreated
          ? `Recreated ${body.recreated} and re-synced${rows}`
          : `Sync finished${rows}`, "success")
        onDone?.()
      }
    } catch (err) {
      toast(`${action.label} failed: ${err instanceof Error ? err.message : String(err)}`, "error")
    } finally {
      setBusy(null)
    }
  }

  if (actions.length === 0) return null
  return (
    <div className="flex flex-wrap gap-2">
      {actions.map((a, i) => {
        const key = `${a.type}:${i}`
        if (a.type === "link") {
          return (
            <Button key={key} variant="outline" size="sm" render={<Link href={a.href} />}>{a.label}</Button>
          )
        }
        return (
          <Button key={key} variant={a.type === "recreate" ? "destructive" : "outline"} size="sm"
                  disabled={busy !== null} onClick={() => void run(a, key)}>
            {busy === key && <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />}
            {busy === key ? "Working…" : a.label}
          </Button>
        )
      })}
    </div>
  )
}
