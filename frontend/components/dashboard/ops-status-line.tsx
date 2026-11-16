"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, Info } from "lucide-react"
import { OpsActionButtons } from "@/components/dashboard/ops-actions"
import { usePermissions } from "@/lib/permissions"
import {
  headline, issueView, parseOpsStatus, staleSummary, statusFacts, type OpsAction, type OpsStatus,
} from "@/lib/ops-status"

const COLLAPSED_KEY = "datapond.dashboard.checklist.collapsed"

function checkedAt(iso: string): string {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
}

function readCollapsed(): boolean {
  try { return window.localStorage.getItem(COLLAPSED_KEY) === "1" } catch { return false }
}

function writeCollapsed(v: boolean) {
  try { window.localStorage.setItem(COLLAPSED_KEY, v ? "1" : "0") } catch {}
}

/** Row: what is wrong on the left, the fix on the right. */
function IssueRow({ title, detail, advice, tone, actions, onDone }: {
  title: string; detail: string; advice?: string; tone: "warn" | "info"; actions: OpsAction[]; onDone: () => void
}) {
  const Icon = tone === "warn" ? AlertTriangle : Info
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
      <Icon className="h-4 w-4 shrink-0"
            style={{ color: tone === "warn" ? "var(--dp-warn)" : "var(--muted-foreground)" }} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">{detail}</p>
        {advice && <p className="mt-0.5 text-xs">{advice}</p>}
      </div>
      <OpsActionButtons actions={actions} onDone={onDone} />
    </li>
  )
}

/** Stale sources are not urgent: one line, and the list lives on Sources. */
function StaleLink({ text }: { text: string }) {
  return (
    <Link href="/connectors?filter=stale"
          className="inline-flex items-center gap-1.5 text-sm text-[var(--dp-warn-text)] hover:underline">
      <span className="h-2 w-2 rounded-full" style={{ background: "var(--dp-warn)" }} aria-hidden />
      {text}
      <span className="inline-flex items-center gap-0.5 font-medium">· Review in Sources<ArrowRight className="h-3.5 w-3.5" aria-hidden /></span>
    </Link>
  )
}

/** Top of Overview: what needs action now — failures and outages, each with its fix, in a
 *  collapsible card (remembered per browser). Stale sources are one line linking to
 *  Sources; with nothing urgent the whole thing is one quiet line. */
export function OpsStatusLine() {
  const { permissions } = usePermissions()
  const [status, setStatus] = useState<OpsStatus | null>(null)
  const [collapsed, setCollapsed] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/ops/status")
      if (!res.ok) return
      setStatus(parseOpsStatus(await res.json()))
    } catch {}
  }, [])

  useEffect(() => {
    const first = window.setTimeout(() => { setCollapsed(readCollapsed()); void load() }, 0)
    const interval = window.setInterval(() => void load(), 60000)
    return () => { window.clearTimeout(first); window.clearInterval(interval) }
  }, [load])

  if (!status) return null
  const head = headline(status)
  const facts = statusFacts(status)
  const when = checkedAt(status.checked_at)
  const urgent = status.issues.filter((i) => i.kind !== "stale_source")
  const stale = staleSummary(status.issues)
  const reload = () => void load()

  if (urgent.length === 0) {
    return (
      <section aria-label="Operations status" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span className="inline-flex items-center gap-2 font-medium">
          <CheckCircle2 className="h-4 w-4" style={{ color: "var(--dp-good)" }} aria-hidden />
          {head.label}
        </span>
        {stale && <StaleLink text={stale} />}
        {facts.map((f) => <span key={f} className="text-muted-foreground">{f}</span>)}
        {when && <span className="ml-auto text-xs text-muted-foreground">checked {when}</span>}
      </section>
    )
  }

  const toggle = () => setCollapsed((c) => { writeCollapsed(!c); return !c })

  return (
    <section aria-label="Operations status"
             className="overflow-hidden rounded-lg border border-l-4 bg-card"
             style={{ borderLeftColor: "var(--dp-warn)" }}>
      <button type="button" onClick={toggle} aria-expanded={!collapsed} aria-controls="ops-checklist"
              className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-left text-sm hover:bg-muted/40">
        <span className="inline-flex items-center gap-2 font-semibold text-[var(--dp-warn-text)]">
          <AlertTriangle className="h-4 w-4" style={{ color: "var(--dp-warn)" }} aria-hidden />
          {head.label}
        </span>
        {facts.map((f) => <span key={f} className="text-muted-foreground">{f}</span>)}
        <span className="ml-auto inline-flex items-center gap-2 text-xs text-muted-foreground">
          {when && <>checked {when}</>}
          <ChevronDown className={`h-4 w-4 transition-transform ${collapsed ? "-rotate-90" : ""}`} aria-hidden />
        </span>
      </button>

      {!collapsed && (
        <ul id="ops-checklist" className="divide-y border-t">
          {urgent.map((issue, i) => {
            const v = issueView(issue, permissions)
            return <IssueRow key={i} title={v.title} detail={v.detail} advice={v.advice} tone={v.tone}
                             actions={v.actions} onDone={reload} />
          })}
          {stale && <li className="px-4 py-2.5"><StaleLink text={stale} /></li>}
        </ul>
      )}
    </section>
  )
}
