"use client"

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"
import { usePathname } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useHasPermission } from "@/lib/permissions"
import {
  readPanelOpen, serverPanelOpen, subscribeToPanelState, togglePanel,
} from "@/lib/assistant-panel-state"
import { Markdown } from "@/components/ui/markdown"
import { Bot, Loader2, PanelRightClose, Check, X, Play } from "lucide-react"

type Turn = {
  role: "user" | "assistant"
  content: string
  /** The action's own result, kept whole. It used to be flattened into a sentence by
   *  summarise(), which had no case for SQL — so asking a data question printed
   *  "Generate SQL: done" and the statement itself was never shown at all. */
  action?: { id: string; label: string; result: Record<string, unknown> | null }
}
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

/** The assistant panel.
 *
 *  Turns live in this component and nowhere else — the transcript is not persisted
 *  (design §9). What the server keeps is the single request that produced an action,
 *  stored on that action. Reloading starts a new conversation, on purpose.
 */
export function AssistantPanel() {
  const pathname = usePathname()
  const canUse = useHasPermission("ai:generate")
  // localStorage is state living outside React, so it is read the way external
  // state is read. Setting it from an effect meant a synchronous setState on every
  // mount, and a lazy useState initialiser cannot be used either: the server has no
  // localStorage, so it would render a different value than it hydrates to.
  const open = useSyncExternalStore(subscribeToPanelState, readPanelOpen, serverPanelOpen)
  const [turns, setTurns] = useState<Turn[]>([])
  const [pending, setPending] = useState<ActionCard | null>(null)
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Scroll the transcript container itself. scrollIntoView walks up and scrolls
    // ancestors too, which moved the whole page — the behaviour this panel is
    // supposed to keep out of.
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [turns, pending, busy])

  const toggle = useCallback(() => { togglePanel() }, [])

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

      // Every step the turn took, in order. A turn now continues while the model
      // keeps choosing reads — asking about data used to end at "found the table"
      // — so a single message can produce a search, then the SQL it led to.
      const steps: ActionCard[] = data.steps?.length ? data.steps
        : data.action ? [data.action] : []
      for (const step of steps) {
        if (step.needs_approval && step.status === "proposed") {
          setPending(step)
        } else {
          setTurns(t => [...t, {
            role: "assistant", content: "",
            action: { id: step.action_id, label: step.label, result: step.result },
          }])
        }
      }
    } finally {
      setBusy(false)
    }
  }

  /** Propose an action the person chose from a result — "run this SQL". Goes through
   *  the same gate as anything the model proposes: a write still parks for approval,
   *  and the preview is still computed on the server. */
  const propose = async (actionId: string, params: Record<string, unknown>) => {
    if (busy) return
    setBusy(true)
    try {
      const res = await fetch("/api/chat/actions/propose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_id: actionId, params, page: pathname }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setTurns(t => [...t, { role: "assistant", content: data.detail || "That could not be started." }])
        return
      }
      if (data.needs_approval && data.status === "proposed") setPending(data)
      else setTurns(t => [...t, { role: "assistant", content: "",
                                  action: { id: data.action_id, label: data.label, result: data.result } }])
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
      setTurns(t => [...t, !res.ok
        ? { role: "assistant" as const, content: data.detail || "That could not be completed." }
        : accept
          ? { role: "assistant" as const, content: "",
              action: { id: pending.action_id, label: pending.label, result: data.result } }
          : { role: "assistant" as const, content: `${pending.label} — dismissed.` }])
      setPending(null)
    } finally {
      setBusy(false)
    }
  }

  if (!canUse) return null

  // Closed, this component renders nothing: the control that opens it is
  // <AssistantTrigger /> in the top bar, beside the sidebar's own trigger. It used to
  // be a floating button pinned to the middle of the right edge, which meant you
  // clicked at mid-height to open and had to travel to the panel header to close.
  if (!open) return null

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
            Ask about this deployment — the data, your sources and syncs, collections,
            services, storage, policies and spend. With your approval I can run a query,
            save a dashboard, or create a collection. I cannot delete anything, run a
            sync, or change settings.
          </p>
        )}
        {turns.map((turn, i) => turn.action ? (
          <ActionResult key={i} action={turn.action} onPropose={propose} busy={busy} />
        ) : (
          <div key={i} className={turn.role === "user" ? "text-right" : ""}>
            <span className={`inline-block max-w-[92%] rounded-lg px-2.5 py-1.5 text-left ${
              turn.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"}`}>
              {/* The user's own words go through unparsed — they typed them, and
                  turning their asterisks into emphasis misquotes them. Only the
                  model's side is Markdown. */}
              {turn.role === "user"
                ? <span className="whitespace-pre-wrap">{turn.content}</span>
                : <Markdown text={turn.content} />}
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

/** What an action produced, rendered rather than flattened.
 *
 *  The previous version turned every result into one sentence and had no case for a
 *  SQL string, so asking a data question printed "Generate SQL: done" — the statement
 *  invisible, and no way to reach an answer from it. A question about data should end
 *  in rows, and each step of getting there should be legible.
 */
function ActionResult({ action, onPropose, busy }: {
  action: { id: string; label: string; result: Record<string, unknown> | null }
  onPropose: (id: string, params: Record<string, unknown>) => void
  busy: boolean
}) {
  const r = action.result ?? {}

  if (typeof r.sql === "string" && r.sql.trim()) {
    return (
      <div className="rounded-lg border bg-muted/30 p-2.5 text-xs">
        {typeof r.explanation === "string" && r.explanation && (
          <p className="mb-1.5 text-muted-foreground">{r.explanation}</p>
        )}
        <pre className="overflow-x-auto rounded border bg-background p-2 font-mono text-[10.5px] leading-relaxed">
{String(r.sql)}
        </pre>
        {r.validated === false ? (
          <p className="mt-1.5 text-[11px] text-destructive">
            The catalog rejected this statement, so it is not offered to run.
          </p>
        ) : (
          <Button size="sm" className="mt-2 h-7 gap-1.5 text-xs" disabled={busy}
                  onClick={() => onPropose("query.run", { sql: String(r.sql) })}>
            <Play className="h-3.5 w-3.5" />Run this
          </Button>
        )}
        {r.needs_input === true && (
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            The question was ambiguous — check the statement before running it.
          </p>
        )}
      </div>
    )
  }

  if (Array.isArray(r.columns) && Array.isArray(r.rows)) {
    const cols = r.columns as string[]
    const rows = r.rows as unknown[][]
    return (
      <div className="rounded-lg border text-xs">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b bg-muted/40">
              <tr>{cols.map(c => (
                <th key={c} className="px-2 py-1 text-left text-[10.5px] font-medium">{c}</th>
              ))}</tr>
            </thead>
            <tbody className="divide-y">
              {rows.slice(0, 20).map((row, i) => (
                <tr key={i}>{row.map((cell, j) => (
                  <td key={j} className="px-2 py-1 font-mono text-[10.5px] tabular-nums">
                    {cell === null ? <span className="text-muted-foreground">null</span> : String(cell)}
                  </td>
                ))}</tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="border-t px-2 py-1 text-[10px] text-muted-foreground">
          {typeof r.row_count === "number" ? `${r.row_count} row(s)` : `${rows.length} row(s)`}
          {rows.length > 20 && " · showing the first 20"}
          {r.truncated === true && " · the result was truncated"}
        </p>
      </div>
    )
  }

  return (
    <p className="text-xs text-muted-foreground">
      {action.label}: {summarise(action.result)}
    </p>
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
  if (typeof r.answer === "string") return r.answer
  return "done"
}
