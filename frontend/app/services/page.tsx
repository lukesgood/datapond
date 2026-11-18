"use client"

import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { ServicesPanel } from "@/components/infra/services-panel"
import { SystemPanel } from "@/components/infra/system-panel"
import { EventsPanel } from "@/components/infra/events-panel"

// Infrastructure workspace — one entry, three tabs in the URL. ?tab=system is the
// node / cluster panel, ?tab=events the event log; anything else is Services. Deep
// links to /services/[id] for logs and events are kept.
function InfraWorkspace() {
  const tab = useSearchParams().get("tab")
  if (tab === "system") return <SystemPanel />
  if (tab === "events") return <EventsPanel />
  return <ServicesPanel />
}

export default function ServicesPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <InfraWorkspace />
    </Suspense>
  )
}
