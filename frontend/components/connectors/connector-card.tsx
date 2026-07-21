"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Plug } from "lucide-react"
import Link from "next/link"
import { Connector } from "@/lib/connectors"

interface ConnectorCardProps {
  connector: Connector
}

export function ConnectorCard({ connector }: ConnectorCardProps) {
  const categoryColors = {
    database: "bg-blue-500/10 text-blue-500",
    storage: "bg-green-500/10 text-green-500",
    streaming: "bg-purple-500/10 text-purple-500",
    saas: "bg-orange-500/10 text-orange-500"
  }

  return (
    <Card className="group hover:shadow-md transition-shadow flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted shrink-0">
            <Plug className="h-4 w-4 text-muted-foreground" />
          </div>
          <div>
            <CardTitle className="text-sm font-semibold">{connector.name}</CardTitle>
            <Badge
              variant="secondary"
              className={`mt-1 text-[10px] h-4 px-1.5 ${categoryColors[connector.category]}`}
            >
              {connector.category}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col flex-1">
        {/* Description — fixed 2-line height */}
        <CardDescription className="text-xs line-clamp-2 min-h-[2.5rem] mb-3">
          {connector.description}
        </CardDescription>

        {/* Features — fixed height slot (always reserves space) */}
        <div className="flex flex-wrap gap-1 min-h-[1.5rem] mb-4">
          {connector.features?.slice(0, 3).map((feature) => (
            <Badge key={feature} variant="outline" className="text-[10px] h-5 px-1.5">
              {feature}
            </Badge>
          ))}
        </div>

        {/* Button — always at bottom */}
        <div className="mt-auto">
          {connector.supported ? (
            <Button className="w-full" size="sm" render={<Link href={`/connectors/${connector.id}/setup`} />}>
              Connect
            </Button>
          ) : (
            <Button className="w-full" size="sm" variant="secondary" disabled>
              Coming Soon
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
