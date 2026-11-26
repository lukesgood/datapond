"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Code2, Database, Globe, HardDrive, type LucideIcon } from "lucide-react"
import Link from "next/link"
import { Connector } from "@/lib/connectors"

// One glyph per kind of source: every card wore the same plug, so a 12-card grid gave
// the eye nothing to scan by. The SVG paths in `connector.icon` were never shipped.
const ICONS: Record<string, LucideIcon> = { s3: HardDrive, rest_api: Globe, custom: Code2 }
const CATEGORY = { database: "Database", storage: "Files", saas: "API / code" } as const

interface ConnectorCardProps {
  connector: Connector
}

export function ConnectorCard({ connector }: ConnectorCardProps) {
  const Icon = ICONS[connector.id] ?? Database
  const body = (
    <Card className={`flex h-full flex-col transition-colors ${connector.supported ? "group-hover:border-primary/50" : "opacity-70"}`}>
      <CardHeader className="pb-2">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Icon className="h-4 w-4" aria-hidden />
          </div>
          <div className="min-w-0">
            <CardTitle className="text-sm font-semibold">{connector.name}</CardTitle>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {CATEGORY[connector.category]}
              {connector.tier === "preview" && (
                <Badge variant="outline" className="ml-1.5 h-4 px-1.5 text-2xs" title="Works, but not yet run against the real service in CI or on the reference deployment">
                  Preview
                </Badge>
              )}
              {!connector.supported && <span> · planned</span>}
            </p>
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-3">
        <CardDescription className="line-clamp-3 text-xs">{connector.description}</CardDescription>
        {connector.features && connector.features.length > 0 && (
          <ul className="mt-auto flex flex-wrap gap-1" aria-label="Features">
            {connector.features.slice(0, 3).map((feature) => (
              <li key={feature}><Badge variant="outline" className="h-5 px-1.5 text-2xs font-normal">{feature}</Badge></li>
            ))}
          </ul>
        )}
        {connector.supported ? (
          <span className="text-xs font-medium text-primary group-hover:underline">Connect</span>
        ) : (
          <Button size="sm" variant="secondary" disabled className="w-full">Not available yet</Button>
        )}
      </CardContent>
    </Card>
  )
  // The whole card is the link (the button was the only target on a large card).
  return connector.supported ? (
    <Link href={`/connectors/${connector.id}/setup`} className="group block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`Connect ${connector.name}`}>
      {body}
    </Link>
  ) : body
}
