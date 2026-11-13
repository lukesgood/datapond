"use client"

import { useCallback, useEffect, useState } from "react"
import { OpsActionButtons } from "@/components/dashboard/ops-actions"
import { usePermissions } from "@/lib/permissions"
import { headline, issueView, parseOpsStatus, statusFacts, type OpsStatus } from "@/lib/ops-status"

function checkedAt(iso: string): string {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
}

/** One line on top of Overview: healthy, or N things to check — each with its fix. */
export function OpsStatusLine() {
  const { permissions } = usePermissions()
  const [status, setStatus] = useState<OpsStatus | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/ops/status")
      if (!res.ok) return
      setStatus(parseOpsStatus(await res.json()))
    } catch {}
  }, [])

  useEffect(() => {
    const first = window.setTimeout(() => void load(), 0)
    const interval = window.setInterval(() => void load(), 60000)
    return () => { window.clearTimeout(first); window.clearInterval(interval) }
  }, [load])

  if (!status) return null
  const head = headline(status)
  const facts = statusFacts(status)
  const when = checkedAt(status.checked_at)

  return (
    <section aria-label="Operations status" className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span className="inline-flex items-center gap-2 font-medium">
          <span className="h-2.5 w-2.5 rounded-full"
                style={{ background: head.tone === "good" ? "var(--dp-good)" : "var(--dp-warn)" }} />
          <span className={head.tone === "warn" ? "text-[var(--dp-warn-text)]" : undefined}>{head.label}</span>
        </span>
        {facts.map((f) => <span key={f} className="text-muted-foreground">{f}</span>)}
        {when && <span className="ml-auto text-xs text-muted-foreground">checked {when}</span>}
      </div>

      {status.issues.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {status.issues.map((issue, i) => {
            const v = issueView(issue, permissions)
            return (
              <li key={i} className="space-y-2 px-4 py-3">
                <div>
                  <p className="text-sm font-medium">{v.title}</p>
                  <p className="text-xs text-muted-foreground">{v.detail}</p>
                  {v.advice && <p className="mt-1 text-xs">{v.advice}</p>}
                </div>
                <OpsActionButtons actions={v.actions} onDone={() => void load()} />
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
