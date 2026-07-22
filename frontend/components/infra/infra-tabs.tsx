"use client"

import { useRouter } from "next/navigation"
import { Boxes, Server } from "lucide-react"

// Shared tab switcher for the Infrastructure workspace. Rendered in both the
// Services grid toolbar and the System page top bar so the two halves read as
// one surface. Tab state lives in the URL (?tab=system) so it is linkable and
// the legacy /system route can redirect straight to the right tab.
const TABS = [
  { key: "services", label: "Services", icon: Boxes,  href: "/services" },
  { key: "system",   label: "System",   icon: Server, href: "/services?tab=system" },
] as const

export function InfraTabs({ active }: { active: "services" | "system" }) {
  const router = useRouter()
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="text-sm font-semibold text-foreground hidden sm:block">Infrastructure</span>
      <div className="flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5">
        {TABS.map((t) => {
          const on = t.key === active
          const Icon = t.icon
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => { if (!on) router.push(t.href) }}
              aria-current={on ? "page" : undefined}
              className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                on ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">{t.label}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
