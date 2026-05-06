"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Database, Table } from "lucide-react"
import Link from "next/link"

interface TableCardProps {
  name: string
  namespace: string
  tableType: string
  lastUpdated?: string
}

export function TableCard({
  name,
  namespace,
  tableType,
  lastUpdated,
}: TableCardProps) {
  const formatLastUpdated = (timestamp?: string) => {
    if (!timestamp) return "Unknown"

    const date = new Date(timestamp)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 60) {
      return `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`
    } else if (diffHours < 24) {
      return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`
    } else if (diffDays < 30) {
      return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`
    } else {
      return date.toLocaleDateString()
    }
  }

  return (
    <Link href={`/catalog/${namespace}/${name}`}>
      <Card className="cursor-pointer hover:shadow-md transition-shadow">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium truncate">{name}</CardTitle>
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted">
              <Table className="h-4 w-4 text-muted-foreground" />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex gap-2">
              <Badge variant="secondary">{namespace}</Badge>
              <Badge variant="outline">{tableType}</Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              Updated {formatLastUpdated(lastUpdated)}
            </p>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
