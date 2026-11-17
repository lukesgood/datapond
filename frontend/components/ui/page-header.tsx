import type { ReactNode } from "react"

/** One header for every page: the menu's name, one sentence on what the page is for,
 *  and the page's actions on the right. Menus used five different header styles. */
export function PageHeader({ title, description, actions, children }: {
  title: string; description?: ReactNode; actions?: ReactNode; children?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-2xl font-bold tracking-tight">{title}</h2>
        {description && <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
