import { AlertCircle } from "lucide-react"
import Link from "next/link"
import { ReactNode } from "react"

// AI gateway/embedding errors almost always mean no model is configured — point the
// user at where to fix it instead of just showing a raw error string.
function looksLikeNoModel(msg: string) {
  const m = (msg || "").toLowerCase()
  return m.includes("gateway") || m.includes("embedding") || m.includes("litellm") ||
         m.includes("502") || m.includes("503") || m.includes("not configured")
}

/** Consistent inline error surface (replaces ad-hoc amber/red error divs). */
export function ErrorBox({ msg, action, className = "" }: {
  msg?: string | null
  action?: ReactNode          // optional retry button etc., rendered under the message
  className?: string
}) {
  if (!msg) return null
  return (
    <div className={`rounded-md border border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/10 px-3 py-2 text-xs text-[var(--dp-warn)] space-y-1 ${className}`}>
      <div className="flex items-start gap-2">
        <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" /><span>{msg}</span>
      </div>
      {action && <div className="pl-6 pt-1">{action}</div>}
      {looksLikeNoModel(msg) && (
        <div className="pl-6">
          An embedding or LLM model may not be configured — register one under{" "}
          <Link href="/settings" className="underline font-medium">Settings → AI</Link>.
        </div>
      )}
    </div>
  )
}

/** Consistent empty-state surface (icon + title + hint + optional action). */
export function EmptyState({ icon: Icon, title, hint, action, className = "" }: {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  hint?: string
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={`flex flex-col items-center justify-center py-12 text-center gap-2 text-muted-foreground ${className}`}>
      {Icon && <Icon className="h-8 w-8 opacity-30" />}
      <p className="text-sm font-medium">{title}</p>
      {hint && <p className="text-xs opacity-70 max-w-sm">{hint}</p>}
      {action}
    </div>
  )
}
