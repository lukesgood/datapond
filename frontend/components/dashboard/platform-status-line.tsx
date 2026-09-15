"use client"

import Link from "next/link"
import type { PlatformStatus } from "@/lib/dashboard-activity"

/** Infrastructure in one line. Healthy workloads were a grid of eight cards that said
 *  "Operational · Running" to each other; only a problem earns more room than this. */
export function PlatformStatusLine({ platform, collections, chunks, storedHuman, canManage }: {
  platform: PlatformStatus | null
  collections: number | null
  chunks: number | null
  storedHuman: string | null
  canManage: boolean
}) {
  const facts: string[] = []
  if (platform) facts.push(`${platform.configured} adapter${platform.configured === 1 ? "" : "s"} configured`)
  if (collections != null) facts.push(`${collections} collection${collections === 1 ? "" : "s"} · ${(chunks ?? 0).toLocaleString("en-US")} chunks`)
  if (storedHuman) facts.push(`${storedHuman} stored`)

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
      {platform === null ? (
        <span>Service status unavailable</span>
      ) : platform.observed === 0 ? (
        <span>No workloads observed</span>
      ) : (
        <span className="inline-flex items-center gap-2">
          <span className="h-2 w-2 rounded-full"
                style={{ background: platform.attention.length ? "var(--dp-warn)" : "var(--dp-good)" }} />
          <span><span className="font-medium text-foreground">{platform.healthy} of {platform.observed}</span> workloads healthy</span>
        </span>
      )}
      {platform && platform.attention.length > 0 && (
        <span className="font-medium text-[var(--dp-warn)]">Needs attention: {platform.attention.join(", ")}</span>
      )}
      {facts.map((f) => <span key={f}>{f}</span>)}
      {canManage && (
        <Link href="/services" className="ml-auto text-primary hover:underline">Infrastructure →</Link>
      )}
    </div>
  )
}
