"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Database, Table } from "lucide-react"
import Link from "next/link"

interface TableCardProps {
  name: string
  namespace: string
  catalog?: string
  catalogType?: string
  tableType: string
  lastUpdated?: string
}

const CATALOG_TYPE_STYLES: Record<string, { label: string; cls: string }> = {
  managed:  { label: "Managed",  cls: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  external: { label: "External", cls: "bg-amber-100 text-amber-700 border-amber-200" },
  foreign:  { label: "Foreign",  cls: "bg-blue-100 text-blue-700 border-blue-200" },
}

export function TableCard({
  name,
  namespace,
  catalog,
  catalogType,
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

  const catStyle = CATALOG_TYPE_STYLES[catalogType || "managed"] || CATALOG_TYPE_STYLES.managed

  return (
    <Link href={`/catalog/${namespace}/${name}${catalog ? `?catalog=${catalog}` : ""}`}>
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
            <div className="flex gap-2 flex-wrap">
              <Badge variant="secondary">{catalog ? `${catalog}.${namespace}` : namespace}</Badge>
              <Badge variant="outline" className={catStyle.cls}>{catStyle.label}</Badge>
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
