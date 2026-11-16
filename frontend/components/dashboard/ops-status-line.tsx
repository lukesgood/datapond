"use client"

import { useCallback, useEffect, useState } from "react"
import { AlertTriangle, CheckCircle2, ChevronDown, Info, Loader2, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { OpsActionButtons } from "@/components/dashboard/ops-actions"
import { usePermissions } from "@/lib/permissions"
import { useToast } from "@/lib/toast"
import {
  ageLabel, groupIssues, headline, issueView, parseOpsStatus, statusFacts,
  type OpsAction, type OpsStatus, type StaleIssue,
} from "@/lib/ops-status"

const COLLAPSED_KEY = "datapond.dashboard.checklist.collapsed"
const STALE_PREVIEW = 3

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

/** Every stale source in one block: one compact line each, a few shown, "Sync all". */
function StaleGroup({ items, canSync, onDone }: { items: StaleIssue[]; canSync: boolean; onDone: () => void }) {
  const { permissions } = usePermissions()
  const { toast } = useToast()
  const [showAll, setShowAll] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)
  const shown = showAll ? items : items.slice(0, STALE_PREVIEW)
  const hidden = items.length - shown.length

  // One at a time: the reference runs on a single node, and each sync is a Trino job.
  const syncAll = async () => {
    const failed: string[] = []
    for (let i = 0; i < items.length; i++) {
      setProgress(i + 1)
      try {
        const res = await fetch(`/api/connectors/${encodeURIComponent(items[i].connection_id)}/sync`, {
          method: "POST", credentials: "include",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
        })
        if (!res.ok) failed.push(items[i].source)
      } catch {
        failed.push(items[i].source)
      }
    }
    setProgress(null)
    const ok = items.length - failed.length
    toast(failed.length
      ? `${ok} of ${items.length} synced. Failed: ${failed.join(", ")}`
      : `Synced ${items.length} source${items.length === 1 ? "" : "s"}`, failed.length ? "error" : "success")
    onDone()
  }

  return (
    <li className="px-4 py-2.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <AlertTriangle className="h-4 w-4 shrink-0" style={{ color: "var(--dp-warn)" }} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">
            {items.length === 1 ? "1 source has" : `${items.length} sources have`} not synced recently
          </p>
          <p className="text-xs text-muted-foreground">Their lake tables may be out of date.</p>
        </div>
        {canSync && items.length > 1 && (
          <Button variant="outline" size="sm" disabled={progress !== null} onClick={() => void syncAll()}>
            {progress !== null
              ? <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />Syncing {progress} of {items.length}…</>
              : <><RefreshCw className="mr-1 h-3.5 w-3.5" />Sync all {items.length}</>}
          </Button>
        )}
      </div>
      <ul className="mt-2 ml-8 divide-y rounded-md border bg-muted/30">
        {shown.map((item) => {
          const v = issueView(item, permissions)
          return (
            <li key={item.connection_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5">
              <span className="min-w-0 flex-1 truncate text-sm">{item.source}</span>
              <span className="text-xs tabular-nums text-muted-foreground">{ageLabel(item.hours)}</span>
              <OpsActionButtons actions={v.actions} onDone={onDone} />
            </li>
          )
        })}
      </ul>
      {items.length > STALE_PREVIEW && (
        <button type="button" onClick={() => setShowAll((s) => !s)}
                className="mt-1.5 ml-8 text-xs font-medium text-primary hover:underline">
          {showAll ? "Show fewer" : `Show ${hidden} more`}
        </button>
      )}
    </li>
  )
}

/** Top of Overview: one quiet line when healthy; otherwise a compact checklist, each item
 *  with its fix. Collapsible, and the choice is remembered in this browser. */
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
  const groups = groupIssues(status.issues)
  const reload = () => void load()

  if (groups.length === 0) {
    return (
      <section aria-label="Operations status" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span className="inline-flex items-center gap-2 font-medium">
          <CheckCircle2 className="h-4 w-4" style={{ color: "var(--dp-good)" }} aria-hidden />
          {head.label}
        </span>
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
          {groups.map((g, i) => {
            if (g.kind === "stale") {
              return <StaleGroup key="stale" items={g.items} canSync={permissions.has("connector:write")} onDone={reload} />
            }
            const v = issueView(g.issue, permissions)
            return <IssueRow key={i} title={v.title} detail={v.detail} advice={v.advice} tone={v.tone}
                             actions={v.actions} onDone={reload} />
          })}
        </ul>
      )}
    </section>
  )
}
