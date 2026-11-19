"use client"

import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { ServicesPanel } from "@/components/infra/services-panel"
import { SystemPanel } from "@/components/infra/system-panel"
import { EventsPanel } from "@/components/infra/events-panel"
import { AwsPanel } from "@/components/infra/aws-panel"
import { CostPanel } from "@/components/infra/cost-panel"
import { useCapabilityStrict } from "@/lib/capabilities"

// Infrastructure workspace — one entry, tabs in the URL. ?tab=system is the
// node / cluster panel, ?tab=aws and ?tab=cost the AWS reference's resources and
// cost (capability aws_infra), ?tab=events the event log; anything else is Services. Deep
// links to /services/[id] for logs and events are kept.
function InfraWorkspace() {
  const tab = useSearchParams().get("tab")
  const aws = useCapabilityStrict("aws_infra")
  if (tab === "system") return <SystemPanel />
  if (tab === "aws" && aws) return <AwsPanel />
  if (tab === "cost" && aws) return <CostPanel />
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
