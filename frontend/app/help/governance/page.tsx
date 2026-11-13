"use client"

import { ShieldCheck } from "lucide-react"
import { AiOpsGuide } from "@/components/help/ai-ops-guide"
import { GOVERNANCE } from "@/lib/help-ai-ops"

export default function GovernanceHelpPage() {
  return <AiOpsGuide guide={GOVERNANCE} Icon={ShieldCheck} iconBox="bg-[var(--dp-good)]/10" iconColor="text-[var(--dp-good-text)]" />
}
