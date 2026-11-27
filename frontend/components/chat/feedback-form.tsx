"use client"

import { useEffect, useState } from "react"
import { usePathname } from "next/navigation"
import { Bug, Lightbulb, Loader2, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useCapabilities } from "@/lib/capabilities"
import { useToast } from "@/lib/toast"
import {
  feedbackPayload, KIND_LABEL, STATUS_LABEL, type FeedbackItem, type FeedbackKind,
} from "@/lib/feedback"

/** The Assistant panel's footer: report a problem or ask for a feature, without
 *  leaving the page it is about. The page path, app version and browser go with it,
 *  shown before sending. Administrators see reports in Settings → Feedback (and by
 *  email when SES is set up); the reporter sees each one's status under "Your reports". */
export function FeedbackFooter() {
  const [open, setOpen] = useState<FeedbackKind | "mine" | null>(null)
  return (
    <div className="border-t px-2 py-1.5">
      {open === null ? (
        <div className="flex items-center gap-3 text-2xs text-muted-foreground">
          <button type="button" className="flex items-center gap-1 hover:text-foreground" onClick={() => setOpen("bug")}>
            <Bug className="h-3 w-3" aria-hidden /> Report a problem
          </button>
          <button type="button" className="flex items-center gap-1 hover:text-foreground" onClick={() => setOpen("feature")}>
            <Lightbulb className="h-3 w-3" aria-hidden /> Request a feature
          </button>
          <button type="button" className="ml-auto hover:text-foreground" onClick={() => setOpen("mine")}>Your reports</button>
        </div>
      ) : open === "mine" ? (
        <MyReports onClose={() => setOpen(null)} />
      ) : (
        <ReportForm kind={open} onKind={setOpen} onClose={() => setOpen(null)} />
      )}
    </div>
  )
}

function ReportForm({ kind, onKind, onClose }: { kind: FeedbackKind; onKind: (k: FeedbackKind) => void; onClose: () => void }) {
  const pathname = usePathname()
  const reported = useCapabilities().version
  const version = typeof reported === "string" ? reported : null
  const { toast } = useToast()
  const [title, setTitle] = useState("")
  const [body, setBody] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const payload = feedbackPayload(kind, title, body, pathname ?? "/", version,
                                  typeof navigator === "undefined" ? "" : navigator.userAgent)

  const send = async () => {
    if (!payload) return
    setBusy(true); setErr(null)
    try {
      const r = await fetch("/api/feedback", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => null) as { detail?: unknown } | null
        throw new Error(typeof d?.detail === "string" ? d.detail : `Could not send (${r.status})`)
      }
      toast(kind === "bug" ? "Problem reported. Administrators will see it." : "Request sent. Administrators will see it.", "success")
      onClose()
    } catch (e) { setErr(e instanceof Error ? e.message : "Could not send") }
    finally { setBusy(false) }
  }

  return (
    <form className="space-y-1.5 py-1" onSubmit={e => { e.preventDefault(); void send() }}>
      <div className="flex items-center justify-between">
        <div role="radiogroup" aria-label="Kind" className="inline-flex rounded-md border p-0.5 text-2xs">
          {(["bug", "feature"] as const).map(k => (
            <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => onKind(k)}
                    className={`rounded px-2 py-0.5 ${kind === k ? "bg-secondary font-medium text-foreground" : "text-muted-foreground"}`}>
              {k === "bug" ? "Problem" : "Feature"}
            </button>
          ))}
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded p-0.5 text-muted-foreground hover:text-foreground">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <Input aria-label="Title" value={title} onChange={e => setTitle(e.target.value)} maxLength={200} autoFocus
             placeholder={kind === "bug" ? "What went wrong, in a line" : "What you would like, in a line"} className="h-7 text-xs" />
      <Textarea aria-label="Details" rows={3} value={body} onChange={e => setBody(e.target.value)} maxLength={5000}
                placeholder={kind === "bug" ? "What you did, what you expected, what happened instead" : "What it is for, and how you would use it"}
                className="min-h-0 resize-none text-xs" />
      <p className="text-2xs text-muted-foreground">
        Sent with: page {payload?.page ?? (pathname || "/")}{version ? ` · version ${version}` : ""} · your browser.
        No query results or messages from this conversation are included.
      </p>
      {err && <p role="alert" className="text-2xs text-destructive">{err}</p>}
      <div className="flex gap-1.5">
        <Button type="submit" size="sm" className="h-7 text-xs" disabled={busy || !payload}>
          {busy && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}Send
        </Button>
        <Button type="button" size="sm" variant="ghost" className="h-7 text-xs" onClick={onClose} disabled={busy}>Cancel</Button>
      </div>
    </form>
  )
}

function MyReports({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<FeedbackItem[] | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    let live = true
    fetch("/api/feedback/mine").then(r => (r.ok ? r.json() : Promise.reject()))
      .then((d: { items: FeedbackItem[] }) => { if (live) setItems(d.items ?? []) })
      .catch(() => { if (live) setErr(true) })
    return () => { live = false }
  }, [])
  return (
    <div className="space-y-1.5 py-1">
      <div className="flex items-center justify-between">
        <span className="text-2xs font-medium">Your reports</span>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded p-0.5 text-muted-foreground hover:text-foreground">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {err ? <p className="text-2xs text-destructive">Could not load your reports.</p>
        : items === null ? <p className="text-2xs text-muted-foreground">Loading…</p>
        : items.length === 0 ? <p className="text-2xs text-muted-foreground">You have not sent any yet.</p>
        : (
          <ul className="max-h-48 space-y-1 overflow-y-auto">
            {items.map(i => (
              <li key={i.id} className="rounded border px-2 py-1 text-2xs">
                <div className="flex items-center gap-1.5">
                  <span className="truncate font-medium">{i.title}</span>
                  <span className="ml-auto shrink-0 text-muted-foreground">{KIND_LABEL[i.kind]} · {STATUS_LABEL[i.status]}</span>
                </div>
                {i.admin_note && <p className="mt-0.5 text-muted-foreground">{i.admin_note}</p>}
              </li>
            ))}
          </ul>
        )}
    </div>
  )
}
