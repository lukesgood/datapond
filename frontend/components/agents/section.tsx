import type { ReactNode } from "react"
import { AlertCircle, Loader2 } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

/** A titled card for one section of the agent page. */
export function Section({ id, title, icon, description, children }: {
  id?: string; title: string; icon?: ReactNode; description?: ReactNode; children: ReactNode
}) {
  return (
    // scroll-mt: the section shortcuts at the top of the page land on the heading.
    <Card id={id} className="scroll-mt-6">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">{icon}{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-3">{children}</CardContent>
    </Card>
  )
}

export function Loading({ what }: { what: string }) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />Loading {what}…
    </div>
  )
}

/** A section's own failure, with its retry. */
export function SectionError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
      <AlertCircle className="h-3.5 w-3.5 shrink-0" />
      <span className="flex-1">{message}</span>
      {onRetry && <button className="underline" onClick={onRetry}>Retry</button>}
    </div>
  )
}

/** The error text of a failed mutation response. */
export async function errorText(res: Response, fallback: string): Promise<string> {
  const d = await res.json().catch(() => ({}))
  return typeof d.detail === "string" ? d.detail : `${fallback} (HTTP ${res.status})`
}
