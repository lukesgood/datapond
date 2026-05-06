"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import {
  BarChart3,
  Eye,
  Clock,
  Search,
  Globe,
  Lock,
  LineChart,
  PieChart,
  TrendingUp,
  AreaChart,
  Table,
} from "lucide-react"
import { dashboardApi, Dashboard } from "@/lib/api"
import { formatDistanceToNow } from "date-fns"

export default function DashboardsPage() {
  const router = useRouter()
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState("")

  useEffect(() => {
    loadDashboards()
  }, [])

  const loadDashboards = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await dashboardApi.list()
      setDashboards(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboards")
    } finally {
      setLoading(false)
    }
  }

  const filteredDashboards = dashboards.filter((d) =>
    d.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    d.description?.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const getChartIcon = (chartType: string) => {
    switch (chartType) {
      case "line":
        return <LineChart className="h-5 w-5 text-blue-500" />
      case "bar":
        return <BarChart3 className="h-5 w-5 text-green-500" />
      case "area":
        return <AreaChart className="h-5 w-5 text-purple-500" />
      case "pie":
        return <PieChart className="h-5 w-5 text-orange-500" />
      case "table":
        return <Table className="h-5 w-5 text-gray-500" />
      default:
        return <TrendingUp className="h-5 w-5 text-blue-500" />
    }
  }

  const getChartTypeLabel = (chartType: string) => {
    return chartType.charAt(0).toUpperCase() + chartType.slice(1)
  }

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="/">Home</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Dashboards</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Dashboards</h2>
          <p className="text-muted-foreground">
            View and manage your saved dashboards
          </p>
        </div>

        <Button onClick={() => router.push("/query")}>
          <BarChart3 className="mr-2 h-4 w-4" />
          Create in SQL Lab
        </Button>
      </div>

      {/* Search Bar */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search dashboards..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
        </div>
      </div>

      {/* Statistics Cards */}
      {!loading && !error && (
        <div className="grid gap-4 md:grid-cols-4">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium">Total Dashboards</CardTitle>
                <BarChart3 className="h-4 w-4 text-muted-foreground" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{dashboards.length}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium">Public</CardTitle>
                <Globe className="h-4 w-4 text-muted-foreground" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {dashboards.filter((d) => d.is_public).length}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium">Private</CardTitle>
                <Lock className="h-4 w-4 text-muted-foreground" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {dashboards.filter((d) => !d.is_public).length}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium">Chart Types</CardTitle>
                <PieChart className="h-4 w-4 text-muted-foreground" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {new Set(dashboards.map((d) => d.chart_config.chartType)).size}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-6 w-3/4" />
              </CardHeader>
              <CardContent className="space-y-3">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-10 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Error State */}
      {error && (
        <Card className="border-destructive">
          <CardContent className="py-8">
            <div className="text-center space-y-3">
              <p className="text-destructive">{error}</p>
              <Button onClick={loadDashboards} variant="outline">
                Try Again
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty State */}
      {!loading && !error && dashboards.length === 0 && (
        <Card>
          <CardContent className="py-12">
            <div className="text-center space-y-3">
              <BarChart3 className="h-12 w-12 mx-auto text-muted-foreground opacity-50" />
              <div>
                <h3 className="text-lg font-semibold mb-2">No dashboards yet</h3>
                <p className="text-muted-foreground max-w-md mx-auto">
                  Create your first dashboard by running a query in SQL Lab and clicking "Save Dashboard"
                </p>
              </div>
              <Button onClick={() => router.push("/query")}>
                Go to SQL Lab
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Dashboards Grid */}
      {!loading && !error && filteredDashboards.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filteredDashboards.map((dashboard) => (
            <Card
              key={dashboard.id}
              className="hover:shadow-lg transition-all cursor-pointer hover:-translate-y-1"
              onClick={() => router.push(`/dashboards/${dashboard.id}`)}
            >
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    {getChartIcon(dashboard.chart_config.chartType)}
                    <CardTitle className="text-base truncate">
                      {dashboard.name}
                    </CardTitle>
                  </div>
                  {dashboard.is_public ? (
                    <Globe className="h-4 w-4 text-blue-500 flex-shrink-0" />
                  ) : (
                    <Lock className="h-4 w-4 text-gray-400 flex-shrink-0" />
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {dashboard.description && (
                  <p className="text-sm text-muted-foreground line-clamp-2">
                    {dashboard.description}
                  </p>
                )}

                <div className="flex items-center justify-between">
                  <Badge variant="secondary">
                    {getChartTypeLabel(dashboard.chart_config.chartType)}
                  </Badge>
                  <div className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    <span>
                      {formatDistanceToNow(new Date(dashboard.updated_at), {
                        addSuffix: true,
                      })}
                    </span>
                  </div>
                </div>

                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={(e) => {
                    e.stopPropagation()
                    router.push(`/dashboards/${dashboard.id}`)
                  }}
                >
                  <Eye className="mr-2 h-4 w-4" />
                  View Dashboard
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* No Search Results */}
      {!loading && !error && dashboards.length > 0 && filteredDashboards.length === 0 && (
        <Card>
          <CardContent className="py-12">
            <div className="text-center space-y-3">
              <Search className="h-12 w-12 mx-auto text-muted-foreground opacity-50" />
              <div>
                <h3 className="text-lg font-semibold mb-2">No dashboards found</h3>
                <p className="text-muted-foreground">
                  Try adjusting your search query
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
