"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { TableCard } from "@/components/catalog/table-card"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Search, Database, FolderOpen } from "lucide-react"

interface Table {
  name: string
  namespace: string
  table_type: string
  last_updated?: string
}

interface NamespaceInfo {
  name: string
  properties?: Record<string, string>
}

interface CatalogData {
  tables: Table[]
  namespaces: NamespaceInfo[]
}

export default function CatalogPage() {
  const [data, setData] = useState<CatalogData | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")
  const [selectedNamespace, setSelectedNamespace] = useState<string>("all")

  const fetchData = async () => {
    try {
      setLoading(true)

      // Fetch tables
      const tablesRes = await fetch("/api/catalog/tables")
      const tablesData = await tablesRes.json()

      // Fetch namespaces
      const namespacesRes = await fetch("/api/catalog/namespaces")
      const namespacesData = await namespacesRes.json()

      setData({
        tables: tablesData.tables || [],
        namespaces: namespacesData.namespaces || [],
      })
    } catch (error) {
      console.error("Failed to fetch catalog data:", error)
      setData({ tables: [], namespaces: [] })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  // Filter tables based on search and namespace
  const filteredTables = data?.tables.filter((table) => {
    const matchesSearch =
      searchQuery === "" ||
      table.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      table.namespace.toLowerCase().includes(searchQuery.toLowerCase())

    const matchesNamespace =
      selectedNamespace === "all" || table.namespace === selectedNamespace

    return matchesSearch && matchesNamespace
  })

  // Count tables per namespace
  const namespaceCounts = data?.tables.reduce((acc, table) => {
    acc[table.namespace] = (acc[table.namespace] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        {/* Breadcrumb skeleton */}
        <Skeleton className="h-5 w-[200px]" />

        {/* Header skeleton */}
        <div className="space-y-2">
          <Skeleton className="h-8 w-[150px]" />
          <Skeleton className="h-4 w-[300px]" />
        </div>

        {/* Search and filters skeleton */}
        <div className="flex gap-4">
          <Skeleton className="h-8 w-[300px]" />
          <Skeleton className="h-8 w-[150px]" />
        </div>

        {/* Stats skeleton */}
        <div className="grid gap-4 md:grid-cols-3">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-[120px]" />
          ))}
        </div>

        {/* Tables grid skeleton */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {[...Array(8)].map((_, i) => (
            <Skeleton key={i} className="h-[140px]" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="/dashboard">Home</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Catalog</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Data Catalog</h2>
        <p className="text-muted-foreground">
          Browse and explore Iceberg tables across all namespaces
        </p>
      </div>

      {/* Search and Filters */}
      <div className="flex flex-col gap-4 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search tables..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
          />
        </div>
        <div className="flex gap-2 flex-wrap">
          <Badge
            variant={selectedNamespace === "all" ? "default" : "outline"}
            className="cursor-pointer px-3 py-1"
            onClick={() => setSelectedNamespace("all")}
          >
            All ({data?.tables.length || 0})
          </Badge>
          {data?.namespaces.map((namespace) => (
            <Badge
              key={namespace.name}
              variant={selectedNamespace === namespace.name ? "default" : "outline"}
              className="cursor-pointer px-3 py-1"
              onClick={() => setSelectedNamespace(namespace.name)}
            >
              {namespace.name} ({namespaceCounts?.[namespace.name] || 0})
            </Badge>
          ))}
        </div>
      </div>

      {/* Statistics Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Total Tables</CardTitle>
              <Database className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.tables.length || 0}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Namespaces</CardTitle>
              <FolderOpen className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.namespaces.length || 0}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Filtered Results</CardTitle>
              <Search className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{filteredTables?.length || 0}</div>
          </CardContent>
        </Card>
      </div>

      {/* Tables Grid */}
      <div>
        <h3 className="text-xl font-semibold mb-4">
          {selectedNamespace === "all" ? "All Tables" : `Tables in ${selectedNamespace}`}
        </h3>
        {filteredTables && filteredTables.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filteredTables.map((table) => (
              <TableCard
                key={`${table.namespace}.${table.name}`}
                name={table.name}
                namespace={table.namespace}
                tableType={table.table_type}
                lastUpdated={table.last_updated}
              />
            ))}
          </div>
        ) : (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground">
              No tables found matching your search criteria
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
