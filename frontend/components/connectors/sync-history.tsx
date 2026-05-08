"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  CheckCircle2, XCircle, Loader2, ChevronDown, ChevronRight,
  Clock, Database, Rows3, Timer,
} from "lucide-react"

// ── Types ──────────────────────────────────────────────────────────────────────

export interface SyncTableStep {
  step: string          // schema_check | drop | create | clear | insert | skip | done
  message: string
  pct?: number          // insert progress 0-100
  rows_done?: number
  rows_total?: number
  action?: string       // ok | done | skip | drop
}

export interface SyncTableResult {
  table: string
  status: "pending" | "running" | "success" | "failed"
  rows?: number
  error?: string
  steps?: SyncTableStep[]   // live sub-steps from iceberg_writer
}

export interface SyncSession {
  id: string                          // history_id or "live"
  status: "running" | "success" | "failed"
  started_at: string
  completed_at?: string
  rows_processed: number
  rows_failed: number
  duration_ms?: number
  sync_mode?: string
  tables: SyncTableResult[]
  // live-only: set while SSE is streaming
  isLive?: boolean
}

interface SyncHistoryProps {
  sessions: SyncSession[]
  onDismissLive?: () => void
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtDate(s: string | null | undefined) {
  if (!s) return "—"
  const utc = s.endsWith("Z") || s.includes("+") ? s : s + "Z"
  const d = new Date(utc)
  const now = Date.now()
  const diffMs = now - d.getTime()
  if (diffMs < 60_000)   return "just now"
  if (diffMs < 3_600_000) return `${Math.floor(diffMs / 60_000)}m ago`
  if (diffMs < 86_400_000) return `${Math.floor(diffMs / 3_600_000)}h ago`
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(d)
}

function fmtDuration(ms?: number) {
  if (!ms) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60_000)}m ${Math.floor((ms % 60_000) / 1000)}s`
}

function progressPct(tables: SyncTableResult[]) {
  if (!tables.length) return 0
  const done = tables.filter(t => t.status === "success" || t.status === "failed").length
  return Math.round((done / tables.length) * 100)
}

// ── Error Detail (collapsible for long errors) ────────────────────────────────

function ErrorDetail({ error }: { error: string }) {
  const [expanded, setExpanded] = useState(false)
  // Extract the human-readable part before query_id if present
  const shortMsg = error.replace(/,\s*query_id=\S+/g, "").replace(/TrinoUserError\([^)]+\):\s*/g, "").replace(/TrinoExternalError\([^)]+\):\s*/g, "").trim()
  const isLong = shortMsg.length > 120

  return (
    <div className="px-2 pb-2 ml-5 space-y-1">
      <div className={`text-destructive text-xs leading-snug ${!expanded && isLong ? "line-clamp-2" : "break-all"}`}>
        {shortMsg}
      </div>
      {isLong && (
        <button
          onClick={() => setExpanded(v => !v)}
          className="text-[10px] text-muted-foreground hover:text-foreground underline underline-offset-2"
        >
          {expanded ? "Show less" : "Show full error"}
        </button>
      )}
    </div>
  )
}

// ── Session Row ────────────────────────────────────────────────────────────────

function SessionRow({ session, defaultOpen }: { session: SyncSession; defaultOpen?: boolean }) {
  // Failed sessions auto-expand so errors are immediately visible
  const [open, setOpen] = useState(defaultOpen ?? session.status === "failed")
  const pct = progressPct(session.tables)
  const successTables = session.tables.filter(t => t.status === "success").length
  const failedTables  = session.tables.filter(t => t.status === "failed").length
  const duration = fmtDuration(session.duration_ms)

  const headerColor =
    session.isLive         ? "border-l-primary"
    : session.status === "failed"  ? "border-l-destructive"
    : "border-l-green-600"

  const statusIcon =
    session.isLive
      ? <Loader2 className="h-4 w-4 text-primary animate-spin shrink-0" />
      : session.status === "failed"
        ? <XCircle className="h-4 w-4 text-red-500 shrink-0" />
        : <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0" />

  return (
    <div className={`border-l-2 pl-3 ${headerColor}`}>
      {/* Session header */}
      <button
        className="w-full flex items-center gap-2 py-2 text-left hover:bg-muted/30 rounded px-1 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        {statusIcon}

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">
              {session.isLive ? "Syncing…" : fmtDate(session.started_at)}
            </span>
            {session.sync_mode && (
              <Badge variant="outline" className="text-[10px] h-4 px-1">{session.sync_mode}</Badge>
            )}
          </div>

          {/* Progress bar (live) or summary (done) */}
          {session.isLive ? (
            <div className="mt-1 flex items-center gap-2">
              <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-300"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-[10px] text-muted-foreground font-mono shrink-0">{pct}%</span>
            </div>
          ) : (
            <div className="flex items-center gap-3 mt-0.5 text-[11px] text-muted-foreground">
              <span className="flex items-center gap-1">
                <Rows3 className="h-3 w-3" />
                {session.rows_processed.toLocaleString()} rows
              </span>
              <span className="flex items-center gap-1">
                <Database className="h-3 w-3" />
                {successTables}/{session.tables.length} tables
              </span>
              {duration && (
                <span className="flex items-center gap-1">
                  <Timer className="h-3 w-3" />
                  {duration}
                </span>
              )}
              {failedTables > 0 && (
                <span className="text-destructive font-medium">{failedTables} failed — click to see errors</span>
              )}
            </div>
          )}
        </div>

        <span className="text-muted-foreground shrink-0">
          {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </span>
      </button>

      {/* Table details (expanded) */}
      {open && session.tables.length > 0 && (
        <div className="pb-2 ml-1 space-y-px">
          {session.tables.map(t => (
            <div key={t.table} className={`rounded text-xs ${
              t.status === "running" ? "bg-primary/5"
              : t.status === "failed" ? "bg-destructive/5"
              : ""
            }`}>
              {/* Row 1: icon + table name + right-side info */}
              <div className="flex items-center gap-2 px-2 py-1">
                {t.status === "pending" && <span className="text-muted-foreground w-3.5 shrink-0">○</span>}
                {t.status === "running" && <Loader2 className="h-3.5 w-3.5 text-primary animate-spin shrink-0" />}
                {t.status === "success" && <CheckCircle2 className="h-3.5 w-3.5 text-green-600 shrink-0" />}
                {t.status === "failed"  && <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />}

                <span className={`font-mono flex-1 truncate ${
                  t.status === "pending" ? "text-muted-foreground"
                  : t.status === "running" ? "text-primary font-medium"
                  : t.status === "failed"  ? "text-destructive font-medium"
                  : "text-foreground"
                }`}>{t.table}</span>

                {t.status === "success" && t.rows != null && (
                  <span className="text-muted-foreground font-mono shrink-0">
                    {t.rows.toLocaleString()} rows
                  </span>
                )}
                {t.status === "running" && (
                  <span className="text-primary text-[10px] shrink-0">processing…</span>
                )}
              </div>

              {/* Row 2: live sub-steps (running table only) */}
              {t.status === "running" && t.steps && t.steps.length > 0 && (
                <div className="ml-5 pb-1.5 space-y-0.5">
                  {t.steps.map((s, si) => {
                    const isInsert = s.step === "insert"
                    const isDrop   = s.step === "drop"
                    return (
                      <div key={si} className="flex items-center gap-2 text-[10px]">
                        <span className={`shrink-0 w-16 font-medium ${
                          isDrop ? "text-amber-500"
                          : isInsert ? "text-primary"
                          : "text-muted-foreground"
                        }`}>{s.step}</span>

                        {isInsert && s.pct !== undefined ? (
                          <div className="flex-1 flex items-center gap-1.5">
                            <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
                              <div className="h-full bg-primary transition-all duration-200"
                                style={{ width: `${s.pct}%` }} />
                            </div>
                            <span className="text-muted-foreground font-mono shrink-0">
                              {s.rows_done?.toLocaleString()}/{s.rows_total?.toLocaleString()} ({s.pct}%)
                            </span>
                          </div>
                        ) : (
                          <span className="text-muted-foreground truncate">{s.message}</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Row 3: error message — collapsible for long Trino errors */}
              {t.status === "failed" && t.error && (
                <ErrorDetail error={t.error} />
              )}

              {/* Row 4: completed steps summary (success, expanded) */}
              {t.status === "success" && t.steps && t.steps.length > 0 && (
                <div className="ml-5 pb-1 flex flex-wrap gap-x-3 gap-y-0.5">
                  {t.steps
                    .filter(s => s.step !== "skip" && s.step !== "schema_check" || s.action === "drop")
                    .map((s, si) => (
                      <span key={si} className="text-[10px] text-muted-foreground/60">
                        {s.step === "insert" ? `inserted ${s.rows_done?.toLocaleString()} rows`
                          : s.step === "drop" ? "schema updated"
                          : s.step === "done" ? ""
                          : s.step}
                      </span>
                    ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main Component ─────────────────────────────────────────────────────────────

export function SyncHistory({ sessions, onDismissLive }: SyncHistoryProps) {
  const liveSession  = sessions.find(s => s.isLive)
  const pastSessions = sessions.filter(s => !s.isLive)

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Sync History</CardTitle>
          {liveSession && onDismissLive && !liveSession.isLive && (
            <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={onDismissLive}>
              Dismiss
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-1">
        {sessions.length === 0 && (
          <div className="text-center py-8 text-sm text-muted-foreground">
            No sync history yet. Click <strong>Sync Now</strong> to start ingestion.
          </div>
        )}

        {/* Live session always on top */}
        {liveSession && (
          <SessionRow key="live" session={liveSession} defaultOpen={true} />
        )}

        {/* Past sessions */}
        {pastSessions.map(s => (
          <SessionRow key={s.id} session={s} />
        ))}
      </CardContent>
    </Card>
  )
}
