"use client"

import { useRouter } from "next/navigation"
import { Boxes, Cloud, DollarSign, ScrollText, Server } from "lucide-react"
import { useCapabilityStrict } from "@/lib/capabilities"

// Shared tab switcher for the Infrastructure workspace, rendered in each panel's top
// bar so the halves read as one surface. Tab state lives in the URL (?tab=…) so it is
// linkable. AWS and Cost exist only on the AWS reference (capability aws_infra).
export type InfraTab = "services" | "system" | "aws" | "cost" | "events"

const TABS: { key: InfraTab; label: string; icon: typeof Boxes; href: string; aws?: boolean }[] = [
  { key: "services", label: "Services", icon: Boxes, href: "/services" },
  { key: "system", label: "Node", icon: Server, href: "/services?tab=system" },
  { key: "aws", label: "AWS", icon: Cloud, href: "/services?tab=aws", aws: true },
  { key: "cost", label: "Cost", icon: DollarSign, href: "/services?tab=cost", aws: true },
  { key: "events", label: "Events", icon: ScrollText, href: "/services?tab=events" },
]

export function InfraTabs({ active }: { active: InfraTab }) {
  const router = useRouter()
  const aws = useCapabilityStrict("aws_infra")
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="text-sm font-semibold text-foreground hidden sm:block">Infrastructure</span>
      <div className="flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5">
        {TABS.filter(t => !t.aws || aws).map((t) => {
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
