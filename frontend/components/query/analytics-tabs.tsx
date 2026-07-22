"use client"

import { useRouter } from "next/navigation"
import { Code2, BarChart3 } from "lucide-react"

// Shared tab switcher for the Analytics workspace. Rendered in both the SQL
// Editor toolbar and the Dashboards gallery top bar so the two halves read as
// one surface. Tab state lives in the URL (?tab=dashboards) so it is linkable
// and the legacy /dashboards route can redirect straight to the right tab.
const TABS = [
  { key: "editor",     label: "SQL Editor", icon: Code2,     href: "/query" },
  { key: "dashboards", label: "Dashboards", icon: BarChart3, href: "/query?tab=dashboards" },
] as const

export function AnalyticsTabs({ active }: { active: "editor" | "dashboards" }) {
  const router = useRouter()
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="text-sm font-semibold text-foreground hidden sm:block">Analytics</span>
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
