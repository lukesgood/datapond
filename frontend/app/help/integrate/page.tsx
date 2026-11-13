"use client"

import { Plug } from "lucide-react"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { EndpointsCard, GatewayCard, McpCard } from "@/components/connect/agent-reference"
import { CollectionSnippets } from "@/components/connect/collection-snippets"
import { GuideHeader, Rich, SectionCard } from "@/components/help/ai-ops-guide"
import { useHelpLocale } from "@/components/help/locale"
import {
  INTEGRATE, INTEGRATE_AUDIT, INTEGRATE_CALL, INTEGRATE_SCOPES,
} from "@/lib/help-ai-ops"

/** The one place that says how an application or agent connects: the steps, then the
 *  reference (MCP, the gateway document, the REST surface) read from the running server. */
export default function IntegrateHelpPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <IntegrateGuide />
    </Suspense>
  )
}

function IntegrateGuide() {
  const { t } = useHelpLocale()
  // Opened from a collection's Members tab: its calls, with its name filled in.
  const collection = useSearchParams().get("collection")
  const [create, key, grant] = INTEGRATE.sections
  return (
    <div className="flex-1 space-y-6 p-8 pt-6 max-w-5xl">
      <GuideHeader crumb={INTEGRATE.crumb} title={INTEGRATE.title} subtitle={t(INTEGRATE.subtitle)}
        Icon={Plug} iconBox="bg-purple-500/10" iconColor="text-purple-500" />

      <SectionCard s={create} />

      <SectionCard s={key}>
        <div className="divide-y rounded-md border text-sm">
          {INTEGRATE_SCOPES.map((s) => (
            <div key={s.use.en} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <span>{t(s.use)}</span>
              <span className="flex gap-1.5">
                {s.scopes.map((scope) => (
                  <code key={scope} className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{scope}</code>
                ))}
              </span>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard s={grant} />

      <div className="space-y-3">
        <h2 className="text-lg font-semibold tracking-tight">{t(INTEGRATE_CALL.title)}</h2>
        <p className="text-sm text-muted-foreground"><Rich text={t(INTEGRATE_CALL.intro)} /></p>
        <p className="text-sm text-muted-foreground"><Rich text={t(INTEGRATE_CALL.oauth)} /></p>
        {collection && (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              {t(INTEGRATE_CALL.collection)} <code className="rounded bg-muted px-1 font-mono text-xs">{collection}</code>:
            </p>
            <CollectionSnippets name={collection} />
          </div>
        )}
        <McpCard />
        <GatewayCard />
        <EndpointsCard />
      </div>

      <SectionCard s={INTEGRATE_AUDIT} />
    </div>
  )
}
