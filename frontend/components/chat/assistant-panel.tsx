"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { usePathname } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useHasPermission } from "@/lib/permissions"
import { Bot, Loader2, PanelRightClose, PanelRightOpen, Check, X } from "lucide-react"

type Turn = { role: "user" | "assistant"; content: string }
type ActionCard = {
  id: string
  action_id: string
  label: string
  kind: "read" | "create" | "mutate" | "destructive"
  status: string
  preview: Record<string, unknown> | null
  result: Record<string, unknown> | null
  needs_approval: boolean
}

const STORAGE_KEY = "datapond_assistant_open"

/** The assistant panel.
 *
 *  Turns live in this component and nowhere else — the transcript is not persisted
 *  (design §9). What the server keeps is the single request that produced an action,
 *  stored on that action. Reloading starts a new conversation, on purpose.
 */
export function AssistantPanel() {
  const pathname = usePathname()
  const canUse = useHasPermission("ai:generate")
  const [open, setOpen] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([])
  const [pending, setPending] = useState<ActionCard | null>(null)
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setOpen(localStorage.getItem(STORAGE_KEY) === "1")
  }, [])

  useEffect(() => {
    // Scroll the transcript container itself. scrollIntoView walks up and scrolls
    // ancestors too, which moved the whole page — the behaviour this panel is
    // supposed to keep out of.
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [turns, pending, busy])

  const toggle = useCallback(() => {
    setOpen(v => {
      localStorage.setItem(STORAGE_KEY, v ? "0" : "1")
      return !v
    })
  }, [])

  const send = async () => {
    const message = input.trim()
    if (!message || busy) return
    setInput("")
    setTurns(t => [...t, { role: "user", content: message }])
    setPending(null)
    setBusy(true)
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          page: pathname,
          conversation_id: conversationId,
          history: turns.slice(-12),
        }),
      })
      if (!res.ok) {
        setTurns(t => [...t, { role: "assistant", content: "The assistant is unavailable." }])
        return
      }
      const data = await res.json()
      if (data.conversation_id) setConversationId(data.conversation_id)
      if (data.reply) setTurns(t => [...t, { role: "assistant", content: data.reply }])
      if (data.action) {
        if (data.action.needs_approval && data.action.status === "proposed") {
          setPending(data.action)
        } else {
          setTurns(t => [...t, {
            role: "assistant",
            content: `${data.action.label}: ${summarise(data.action.result)}`,
          }])
        }
      }
    } finally {
      setBusy(false)
    }
  }

  const resolveAction = async (accept: boolean) => {
    if (!pending || busy) return
    setBusy(true)
    try {
      const res = await fetch(
        `/api/chat/actions/${pending.id}/${accept ? "approve" : "reject"}`,
        { method: "POST" },
      )
      const data = await res.json().catch(() => ({}))
      setTurns(t => [...t, {
        role: "assistant",
        content: !res.ok
          ? (data.detail || "That could not be completed.")
          : accept
            ? `${pending.label}: ${summarise(data.result)}`
            : `${pending.label} — dismissed.`,
      }])
      setPending(null)
    } finally {
      setBusy(false)
    }
  }

  if (!canUse) return null

  if (!open) {
    return (
      <button
        onClick={toggle}
        aria-label="Open assistant"
        className="fixed right-3 top-1/2 z-40 flex h-10 w-10 -translate-y-1/2 items-center
                   justify-center rounded-full border bg-background shadow-sm
                   hover:bg-muted"
      >
        <PanelRightOpen className="h-4 w-4 text-muted-foreground" />
      </button>
    )
  }

  return (
    /* `h-full` resolved against a parent free to grow (body is min-h-full), so a long
       conversation stretched the panel and scrolled the whole page instead of the
       transcript. Pinned to the viewport and made sticky so it stays put. */
    <aside className="sticky top-0 flex h-dvh w-[360px] shrink-0 flex-col border-l bg-background">
      <div className="flex h-11 shrink-0 items-center justify-between border-b px-3">
        <span className="flex items-center gap-2 text-sm font-medium">
          <Bot className="h-4 w-4 text-primary" /> Assistant
        </span>
        <button onClick={toggle} aria-label="Close assistant"
                className="text-muted-foreground hover:text-foreground">
          <PanelRightClose className="h-4 w-4" />
        </button>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 text-sm">
        {turns.length === 0 && !pending && (
          <p className="text-xs text-muted-foreground">
            Ask about the data here. I can look things up and, with your approval, run a
            query, save a dashboard, or create a collection. I cannot delete anything or
            change settings.
          </p>
        )}
        {turns.map((turn, i) => (
          <div key={i} className={turn.role === "user" ? "text-right" : ""}>
            <span className={`inline-block max-w-[92%] whitespace-pre-wrap rounded-lg px-2.5 py-1.5 text-left ${
              turn.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"}`}>
              {turn.content}
            </span>
          </div>
        ))}

        {pending && (
          <div className="rounded-lg border border-primary/40 bg-primary/5 p-3">
            <p className="text-xs font-medium">{pending.label}</p>
            <PreviewBody preview={pending.preview} />
            <div className="mt-2.5 flex gap-2">
              <Button size="sm" className="h-7 gap-1.5 text-xs" disabled={busy}
                      onClick={() => void resolveAction(true)}>
                <Check className="h-3.5 w-3.5" /> Approve
              </Button>
              <Button size="sm" variant="ghost" className="h-7 gap-1.5 text-xs" disabled={busy}
                      onClick={() => void resolveAction(false)}>
                <X className="h-3.5 w-3.5" /> Dismiss
              </Button>
            </div>
            <p className="mt-1.5 text-[10px] text-muted-foreground">
              Nothing runs until you approve. This is what the server will do.
            </p>
          </div>
        )}
        {busy && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Thinking…
          </div>
        )}
      </div>

      <div className="shrink-0 border-t p-2">
        <div className="flex gap-1.5">
          <Input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send() }
            }}
            placeholder="Ask about this page…"
            className="h-8 text-xs"
            disabled={busy}
          />
          <Button size="sm" className="h-8 text-xs" disabled={busy || !input.trim()}
                  onClick={() => void send()}>
            Send
          </Button>
        </div>
        <p className="mt-1 text-[10px] text-muted-foreground">
          Conversation is not saved. Requests that change something are recorded.
        </p>
      </div>
    </aside>
  )
}

function PreviewBody({ preview }: { preview: Record<string, unknown> | null }) {
  if (!preview) return null
  const reads = preview.reads as string[] | undefined
  return (
    <div className="mt-1.5 space-y-1 text-xs text-muted-foreground">
      {reads && reads.length > 0 && (
        <p>Reads: <span className="font-mono text-[11px]">{reads.join(", ")}</span></p>
      )}
      {preview.validated === false && (
        <p className="text-red-600 dark:text-red-400">
          Will not run: {String(preview.error ?? "invalid statement")}
        </p>
      )}
      {preview.already_exists === true && (
        <p className="text-amber-600 dark:text-amber-400">
          A collection with that name already exists.
        </p>
      )}
      {preview.cost_estimate_available === false && (
        <p>No table statistics, so the amount scanned cannot be estimated.</p>
      )}
      {typeof preview.name === "string" && <p>Name: <b>{preview.name}</b></p>}
      {typeof preview.sql === "string" && (
        <pre className="overflow-x-auto rounded border bg-background p-1.5 font-mono text-[10px]">
{String(preview.sql)}
        </pre>
      )}
    </div>
  )
}

function summarise(result: unknown): string {
  if (!result || typeof result !== "object") return "done"
  const r = result as Record<string, unknown>
  if (Array.isArray(r.tables)) {
    return `${r.tables.length} table(s): ${(r.tables as string[]).slice(0, 8).join(", ")}`
  }
  if (Array.isArray(r.columns)) return `${r.columns.length} column(s)`
  if (typeof r.row_count === "number") return `${r.row_count} row(s)`
  if (typeof r.name === "string") return `${r.name} created`
  return "done"
}
