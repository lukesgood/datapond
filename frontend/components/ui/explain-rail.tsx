import type { ReactNode } from "react"
import { AlertTriangle } from "lucide-react"

/** The right-hand column of a settings page: what the current settings do, what is
 *  wrong, and what to do next — kept out of the form so the form is only controls.
 *  Sticky on wide screens; stacks under the form on narrow ones. */
export function ExplainRail({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return (
    <aside aria-label={label}
           className={`min-w-0 flex-[2_1_300px] space-y-4 rounded-xl border bg-muted/40 p-5 text-sm lg:sticky lg:top-6 ${className}`}>
      {children}
    </aside>
  )
}

export function RailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5 border-t pt-3 first:border-t-0 first:pt-0">
      <h4 className="text-sm font-semibold">{title}</h4>
      <div className="text-sm text-muted-foreground">{children}</div>
    </section>
  )
}

export function RailAttention({ title, children, tone = "warn" }: { title: string; children?: ReactNode; tone?: "warn" | "bad" }) {
  const cls = tone === "bad"
    ? "border-destructive/40 bg-destructive/5 text-destructive"
    : "border-[var(--dp-warn)]/40 bg-[var(--dp-warn)]/5 text-[var(--dp-warn-text)]"
  return (
    <div role={tone === "bad" ? "alert" : undefined} className={`rounded-lg border p-3 ${cls}`}>
      <p className="flex items-center gap-1.5 text-xs font-semibold"><AlertTriangle aria-hidden className="h-3.5 w-3.5" />{title}</p>
      {children && <div className="mt-1 text-xs text-foreground">{children}</div>}
    </div>
  )
}
