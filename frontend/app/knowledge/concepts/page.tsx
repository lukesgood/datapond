"use client"

import Link from "next/link"
import { ArrowLeft } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { PageHeader } from "@/components/ui/page-header"
import { ConceptsPanel } from "@/components/knowledge/concepts-panel"
import { CapabilityGate } from "@/lib/capabilities"

/** The deployment-wide vocabulary. It sat in a tab inside one collection's workspace,
 *  though every concept applies to every collection. */
export default function ConceptsPage() {
  return (
    <CapabilityGate capability="ontology">
      <div className="mx-auto max-w-4xl space-y-5 px-6 py-6">
        <Link href="/knowledge" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-3.5 w-3.5" />Knowledge
        </Link>
        <PageHeader
          title="Vocabulary"
          description="Concepts and the terms that mean the same thing. With Concepts on in a search, a question using one term also finds the others — in every collection."
        />
        <Card><CardContent className="pt-5"><ConceptsPanel /></CardContent></Card>
      </div>
    </CapabilityGate>
  )
}
