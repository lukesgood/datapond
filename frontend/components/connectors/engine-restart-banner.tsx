"use client"

import { useEffect, useState } from "react"
import { Loader2, AlertTriangle } from "lucide-react"
import {
  engineBanner, parseEngineStatus, pollDelayMs, type EngineStatus,
} from "@/lib/engine-restart"

// Shown wherever a page has just changed a Trino-backed source, or lands on one: polls
// GET /api/connectors/engine while the engine reports a restart, says so in one line,
// and goes quiet when it is back. Renders nothing on a profile without the engine.
export function EngineRestartBanner({ active, onStatus }: {
  active: boolean
  onStatus?: (s: EngineStatus | null) => void
}) {
  const [status, setStatus] = useState<EngineStatus | null>(null)

  useEffect(() => {
    if (!active) return
    let cancelled = false
    let timer: number | undefined
    const poll = async () => {
      let next: EngineStatus | null = null
      try {
        const res = await fetch("/api/connectors/engine")
        next = parseEngineStatus(res.ok ? await res.json() : null)
        if (!res.ok) next = { engine: "trino", ready: null, restarting: null, error: `HTTP ${res.status}` }
      } catch {
        next = { engine: "trino", ready: null, restarting: null, error: "unreachable" }
      }
      if (cancelled) return
      setStatus(next)
      onStatus?.(next)
      const delay = pollDelayMs(next)
      if (delay > 0) timer = window.setTimeout(() => void poll(), delay)
    }
    void poll()
    return () => { cancelled = true; if (timer) window.clearTimeout(timer) }
    // onStatus is a notification, not an input: re-polling on every parent render would
    // restart the timer each time the parent updates its own state from it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  const banner = engineBanner(status)
  if (!banner) return null
  const Icon = banner.tone === "info" ? Loader2 : AlertTriangle
  const cls = banner.tone === "info"
    ? "border-primary/20 bg-primary/5 text-foreground"
    : "border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/10 text-[var(--dp-warn-text)]"
  return (
    <div role="status" className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${cls}`}>
      <Icon className={`h-4 w-4 shrink-0 ${banner.tone === "info" ? "animate-spin" : ""}`} />
      <span>{banner.text}</span>
    </div>
  )
}
