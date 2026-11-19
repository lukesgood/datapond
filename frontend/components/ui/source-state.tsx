"use client"

import type { ReactNode } from "react"
import { Loader2, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { EmptyState, ErrorBox } from "@/components/ui/error-box"
import type { SourceStatus } from "@/lib/source-state"

/** One fetched source in one of its four states: loading, an error with Retry, an
 *  empty state with one action, or the content. A failure never shows as "none". */
export function SourceState({ status, what, error, onRetry, loading, empty, children }: {
  status: SourceStatus
  /** What is being loaded, in words: "the audit log". */
  what: string
  error?: string | null
  onRetry?: () => void
  /** Replaces the default spinner line, e.g. with skeletons shaped like the content. */
  loading?: ReactNode
  /** The empty state: a node, or a title for the default one. */
  empty?: ReactNode | string
  children: ReactNode
}) {
  if (status === "loading") {
    return <>{loading ?? (
      <p className="flex items-center gap-1.5 py-6 text-xs text-muted-foreground" role="status">
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />Loading {what}…
      </p>
    )}</>
  }
  if (status === "error") {
    return (
      <div role="alert">
        <ErrorBox msg={`Could not load ${what}${error ? `: ${error}` : "."}`}
                  action={onRetry && (
                    <Button variant="outline" size="sm" onClick={onRetry}>
                      <RefreshCw className="mr-1.5 h-3.5 w-3.5" />Retry
                    </Button>
                  )} />
      </div>
    )
  }
  if (status === "empty") {
    return <>{typeof empty === "string" || empty === undefined ? <EmptyState title={empty ?? `No ${what} yet.`} /> : empty}</>
  }
  return <>{children}</>
}
