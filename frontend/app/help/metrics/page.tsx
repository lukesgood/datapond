"use client"

import { Sigma } from "lucide-react"
import { AiOpsGuide } from "@/components/help/ai-ops-guide"
import { METRICS } from "@/lib/help-ai-ops"

/** Approved metrics: what they are for, how one is defined and approved, and how an
 *  agent or a person uses it. */
export default function MetricsHelpPage() {
  return <AiOpsGuide guide={METRICS} Icon={Sigma} iconBox="bg-primary/10" iconColor="text-primary" />
}
