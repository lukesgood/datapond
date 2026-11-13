"use client"

import { Sparkles } from "lucide-react"
import { AiOpsGuide } from "@/components/help/ai-ops-guide"
import { KNOWLEDGE } from "@/lib/help-ai-ops"

export default function KnowledgeHelpPage() {
  return <AiOpsGuide guide={KNOWLEDGE} Icon={Sparkles} iconBox="bg-primary/10" iconColor="text-primary" />
}
