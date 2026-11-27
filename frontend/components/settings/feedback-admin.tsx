"use client"

import { useCallback, useEffect, useState } from "react"
import { Bug, Lightbulb, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/lib/toast"
import { whenLabel } from "@/lib/source-freshness"
import {
  KIND_LABEL, STATUS_LABEL, type FeedbackItem, type FeedbackStatus,
} from "@/lib/feedback"

const FILTERS: (FeedbackStatus | "all")[] = ["open", "planned", "done", "dismissed", "all"]

/** Settings → Feedback: problem reports and feature requests people sent from the
 *  Assistant panel. Move each along and leave a note; the reporter sees both. */
export function FeedbackAdmin() {
  const [filter, setFilter] = useState<FeedbackStatus | "all">("open")
  const [data, setData] = useState<{ items: FeedbackItem[]; counts: Record<FeedbackStatus, number> } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [now, setNow] = useState(0)

  const fetchList = useCallback(() =>
    fetch(`/api/feedback${filter === "all" ? "" : `?status=${filter}`}`).then(async r => {
      if (!r.ok) throw new Error(`Could not load reports (${r.status})`)
      return r.json() as Promise<{ items: FeedbackItem[]; counts: Record<FeedbackStatus, number> }>
    }), [filter])
  const apply = (d: { items: FeedbackItem[]; counts: Record<FeedbackStatus, number> }) => {
    setData(d); setErr(null); setNow(Date.now())
  }
  const fail = (e: unknown) => setErr(e instanceof Error ? e.message : "Could not load reports")
  useEffect(() => {
    let live = true
    fetchList().then(d => { if (live) apply(d) }).catch(e => { if (live) fail(e) })
    return () => { live = false }
  }, [fetchList])
  const load = async () => { try { apply(await fetchList()) } catch (e) { fail(e) } }

  const sel = data?.items.find(i => i.id === selected) ?? null
  return (
    <div className="flex flex-wrap items-start gap-5">
      <section className="min-w-0 flex-[3_1_480px] space-y-3">
        <div role="group" aria-label="Status" className="flex flex-wrap gap-1">
          {FILTERS.map(f => (
            <Button key={f} size="sm" variant={filter === f ? "secondary" : "ghost"} aria-pressed={filter === f}
                    className="h-7 text-xs" onClick={() => { setFilter(f); setSelected(null) }}>
              {f === "all" ? "All" : STATUS_LABEL[f]}
              {f !== "all" && data?.counts ? <span className="ml-1 tabular-nums text-muted-foreground">{data.counts[f]}</span> : null}
            </Button>
          ))}
        </div>
        {err ? <p role="alert" className="text-sm text-destructive">{err}</p>
          : data === null ? <p className="text-sm text-muted-foreground">Loading…</p>
          : data.items.length === 0 ? (
            <p className="rounded-xl border bg-card p-6 text-sm text-muted-foreground">
              {filter === "open" ? "Nothing open. People send reports from the Assistant panel's footer (Report a problem, Request a feature)." : "None here."}
            </p>
          ) : (
            <ul className="divide-y rounded-xl border bg-card">
              {data.items.map(i => (
                <li key={i.id}>
                  <button type="button" onClick={() => setSelected(i.id)} aria-pressed={selected === i.id}
                          className={`flex w-full items-start gap-2.5 px-4 py-2.5 text-left text-sm hover:bg-muted/40 ${selected === i.id ? "bg-muted/50" : ""}`}>
                    {i.kind === "bug" ? <Bug className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-label="Problem" />
                      : <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-label="Feature request" />}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{i.title}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {i.created_by_name || "someone"} · {whenLabel(i.created_at, now)}{i.page ? ` · ${i.page}` : ""}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">{STATUS_LABEL[i.status]}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
      </section>
      {sel ? <Detail key={sel.id} item={sel} onChanged={load} /> : (
        <aside className="min-w-0 flex-[2_1_300px] space-y-2 rounded-xl border bg-muted/40 p-5 text-sm">
          <p className="font-medium">Pick a report</p>
          <p className="text-xs text-muted-foreground">
            Each one carries the page it was sent from, the app version and the browser. Mark it planned, done or
            dismissed and leave a note: the person who sent it sees both under &ldquo;Your reports&rdquo;.
          </p>
        </aside>
      )}
    </div>
  )
}

function Detail({ item, onChanged }: { item: FeedbackItem; onChanged: () => Promise<void> }) {
  const { toast } = useToast()
  const [note, setNote] = useState(item.admin_note ?? "")
  const [busy, setBusy] = useState(false)
  const save = async (status?: FeedbackStatus) => {
    setBusy(true)
    try {
      const r = await fetch(`/api/feedback/${item.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...(status ? { status } : {}), admin_note: note }),
      })
      if (!r.ok) throw new Error(`Could not save (${r.status})`)
      toast(status ? `Marked ${STATUS_LABEL[status].toLowerCase()}` : "Note saved", "success")
      await onChanged()
    } catch (e) { toast(e instanceof Error ? e.message : "Could not save", "error") }
    finally { setBusy(false) }
  }
  return (
    <aside aria-label={`Report: ${item.title}`} className="min-w-0 flex-[2_1_300px] space-y-3 rounded-xl border border-primary/50 bg-muted/40 p-5 text-sm lg:sticky lg:top-6">
      <div>
        <p className="text-xs text-muted-foreground">{KIND_LABEL[item.kind]} · {STATUS_LABEL[item.status]}</p>
        <h3 className="text-base font-semibold">{item.title}</h3>
      </div>
      {item.body ? <p className="whitespace-pre-wrap">{item.body}</p> : <p className="text-muted-foreground">No details given.</p>}
      <dl className="grid grid-cols-[6rem_1fr] gap-x-2 gap-y-1 text-xs">
        <dt className="text-muted-foreground">From</dt><dd>{item.created_by_name || "—"}</dd>
        <dt className="text-muted-foreground">Sent</dt><dd>{new Date(item.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</dd>
        <dt className="text-muted-foreground">Page</dt><dd className="font-mono">{item.page || "—"}</dd>
        <dt className="text-muted-foreground">Version</dt><dd className="font-mono">{item.app_version || "—"}</dd>
        <dt className="text-muted-foreground">Browser</dt><dd className="truncate" title={item.user_agent ?? undefined}>{item.user_agent || "—"}</dd>
      </dl>
      <div className="space-y-1.5">
        <label htmlFor="fb-note" className="text-xs font-medium">Note to the reporter</label>
        <Textarea id="fb-note" rows={3} value={note} onChange={e => setNote(e.target.value)} maxLength={2000} className="text-xs" />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {(["planned", "done", "dismissed", "open"] as FeedbackStatus[]).filter(s => s !== item.status).map(s => (
          <Button key={s} size="sm" variant={s === "done" || s === "planned" ? "default" : "outline"} className="h-7 text-xs"
                  disabled={busy} onClick={() => void save(s)}>
            {busy && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}{s === "open" ? "Reopen" : `Mark ${STATUS_LABEL[s].toLowerCase()}`}
          </Button>
        ))}
        <Button size="sm" variant="ghost" className="h-7 text-xs" disabled={busy || note === (item.admin_note ?? "")} onClick={() => void save()}>Save note</Button>
      </div>
    </aside>
  )
}
