"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import {
  Code2,
  Play,
  History,
  Keyboard,
  Database,
  AlertCircle,
  CheckCircle2,
  Lightbulb,
  BookOpen,
  Share2,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import Link from "next/link"

export default function SqlLabHelpPage() {
  return (
    <div className="flex-1 space-y-6 p-8 pt-6 max-w-5xl">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="/dashboard">Home</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink href="/help">Guides</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>SQL Lab</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-start gap-4">
        <div className="inline-flex p-3 rounded-lg bg-blue-500/10">
          <Code2 className="h-8 w-8 text-blue-500" />
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">Guide</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">SQL Lab</h1>
          <p className="mt-2 text-muted-foreground">
            Interactive query interface for your data
          </p>
        </div>
      </div>

      {/* Quick Start */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Play className="h-5 w-5" />
            Quick Start
          </CardTitle>
          <CardDescription>Get started with SQL Lab in 3 steps</CardDescription>
        </CardHeader>
        <CardContent className="pt-1">
          <div className="relative flex gap-3 pb-6">
            {/* connector line links steps into a visible progression */}
            <span aria-hidden className="absolute left-4 top-10 bottom-0 w-px -translate-x-1/2 bg-border" />
            <div className="relative z-10 flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold">
              1
            </div>
            <div>
              <h3 className="font-semibold">Navigate to SQL Lab</h3>
              <p className="text-sm text-muted-foreground">
                Click &quot;Query Lab&quot; in the sidebar or visit{" "}
                <Link href="/query" className="text-primary hover:underline">
                  /query
                </Link>
              </p>
            </div>
          </div>

          <div className="relative flex gap-3 pb-6">
            <span aria-hidden className="absolute left-4 top-10 bottom-0 w-px -translate-x-1/2 bg-border" />
            <div className="relative z-10 flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold">
              2
            </div>
            <div>
              <h3 className="font-semibold">Browse your tables</h3>
              <p className="text-sm text-muted-foreground">
                Use the schema tree on the left to explore catalogs, namespaces, and tables. Click any table to auto-generate a SELECT query.
              </p>
            </div>
          </div>

          <div className="relative flex gap-3">
            <div className="relative z-10 flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold">
              3
            </div>
            <div>
              <h3 className="font-semibold">Execute your query</h3>
              <p className="text-sm text-muted-foreground">
                Write your SQL query in the editor and press <Badge variant="secondary">Ctrl+Enter</Badge> or click the Execute button
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Interface Overview */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Interface Overview
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Badge variant="outline">Schema Tree (Left)</Badge>
              <p className="text-sm text-muted-foreground">
                Browse all available catalogs, namespaces, and tables. Click on a table to insert its full path into the editor. Expand nodes to see columns and data types.
              </p>
            </div>

            <div className="space-y-2">
              <Badge variant="outline">SQL Editor (Center Left)</Badge>
              <p className="text-sm text-muted-foreground">
                Write and edit your SQL queries with syntax highlighting. Supports multi-statement queries (separated by semicolons). Auto-saves drafts locally.
              </p>
            </div>

            <div className="space-y-2">
              <Badge variant="outline">Results Panel (Center Right)</Badge>
              <p className="text-sm text-muted-foreground">
                View query results in a tabular format. Shows column names, data types, and execution time. Export results as CSV or JSON.
              </p>
            </div>

            <div className="space-y-2">
              <Badge variant="outline">Query History (Right)</Badge>
              <p className="text-sm text-muted-foreground">
                Access your recently executed queries. Click any query to load it back into the editor. Filter by date or search by keyword.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Keyboard Shortcuts */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Keyboard className="h-5 w-5" />
            Keyboard Shortcuts
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="flex justify-between items-center p-3 bg-muted/50 rounded-lg">
              <span className="text-sm">Execute query</span>
              <Badge variant="secondary">Ctrl+Enter</Badge>
            </div>
            <div className="flex justify-between items-center p-3 bg-muted/50 rounded-lg">
              <span className="text-sm">Format SQL</span>
              <Badge variant="secondary">Ctrl+Shift+F</Badge>
            </div>
            <div className="flex justify-between items-center p-3 bg-muted/50 rounded-lg">
              <span className="text-sm">Comment line</span>
              <Badge variant="secondary">Ctrl+/</Badge>
            </div>
            <div className="flex justify-between items-center p-3 bg-muted/50 rounded-lg">
              <span className="text-sm">Find in editor</span>
              <Badge variant="secondary">Ctrl+F</Badge>
            </div>
            <div className="flex justify-between items-center p-3 bg-muted/50 rounded-lg">
              <span className="text-sm">Select all</span>
              <Badge variant="secondary">Ctrl+A</Badge>
            </div>
            <div className="flex justify-between items-center p-3 bg-muted/50 rounded-lg">
              <span className="text-sm">Undo/Redo</span>
              <Badge variant="secondary">Ctrl+Z / Ctrl+Y</Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Use Cases */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lightbulb className="h-5 w-5" />
            Common Use Cases
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <h3 className="font-semibold">Exploratory Data Analysis</h3>
            <p className="text-sm text-muted-foreground">
              Quickly sample tables, check data quality, and understand schema without writing complex queries. Use <code className="bg-muted px-1 py-0.5 rounded">LIMIT</code> for fast previews.
            </p>
            <pre className="bg-muted p-3 rounded-lg text-xs overflow-x-auto">
              <code>{`SELECT * FROM catalog.sales.orders
WHERE order_date >= CURRENT_DATE - INTERVAL '7' DAY
LIMIT 100;`}</code>
            </pre>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Ad-hoc Reporting</h3>
            <p className="text-sm text-muted-foreground">
              Generate custom reports with aggregations, joins, and window functions. Export results directly to CSV for sharing.
            </p>
            <pre className="bg-muted p-3 rounded-lg text-xs overflow-x-auto">
              <code>{`SELECT
  DATE_TRUNC('day', order_date) AS day,
  COUNT(*) AS total_orders,
  SUM(order_amount) AS revenue
FROM catalog.sales.orders
GROUP BY 1
ORDER BY 1 DESC;`}</code>
            </pre>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Data Validation</h3>
            <p className="text-sm text-muted-foreground">
              Check for null values, duplicates, or data quality issues before running pipelines.
            </p>
            <pre className="bg-muted p-3 rounded-lg text-xs overflow-x-auto">
              <code>{`SELECT
  COUNT(*) AS total_rows,
  COUNT(DISTINCT user_id) AS unique_users,
  SUM(CASE WHEN email IS NULL THEN 1 ELSE 0 END) AS missing_emails
FROM catalog.users.profiles;`}</code>
            </pre>
          </div>
        </CardContent>
      </Card>

      {/* FAQ */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5" />
            Frequently Asked Questions
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <h3 className="font-semibold">What SQL dialect does DataPond use?</h3>
            <p className="text-sm text-muted-foreground">
              DataPond uses Presto/Trino-family SQL (ANSI SQL compatible) for OLAP queries — Amazon Athena (AWS) or self-hosted Trino. It supports standard SQL-92/99/2003 syntax plus analytics extensions.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">How long are query results cached?</h3>
            <p className="text-sm text-muted-foreground">
              Query results are cached for 24 hours. Re-running the same query will use cached results unless data has been updated.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Can I share queries with my team?</h3>
            <p className="text-sm text-muted-foreground">
              Yes! Click the <Share2 className="inline h-3 w-3" /> share button to generate a shareable link. The link includes the query text and results (if available).
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">What&rsquo;s the maximum query timeout?</h3>
            <p className="text-sm text-muted-foreground">
              Queries timeout after 5 minutes by default. For long-running work, use the Transforms/Airflow add-on when it is enabled for your profile.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">How do I access query history?</h3>
            <p className="text-sm text-muted-foreground">
              Query history is shown in the right sidebar. It&rsquo;s stored locally in your browser and persists across sessions. Click <History className="inline h-3 w-3" /> to expand full details.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Troubleshooting */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5" />
            Troubleshooting
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Query fails with &quot;Table not found&quot;</AlertTitle>
            <AlertDescription>
              Ensure you&rsquo;re using the full path: <code className="bg-muted px-1 py-0.5 rounded">catalog.namespace.table</code>.
              Check the schema tree to verify the table exists and you have access.
            </AlertDescription>
          </Alert>

          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Query takes too long</AlertTitle>
            <AlertDescription>
              Try adding a <code className="bg-muted px-1 py-0.5 rounded">LIMIT</code> clause to reduce result size.
              For large scans, use filters on partitioned columns (e.g., date ranges).
            </AlertDescription>
          </Alert>

          <Alert>
            <CheckCircle2 className="h-4 w-4" />
            <AlertTitle>Results not showing</AlertTitle>
            <AlertDescription>
              Check the browser console for errors. Clear your browser cache and reload. If the issue persists, check backend logs for query-engine errors.
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>

      {/* Next Steps */}
      <Card className="bg-gradient-to-r from-primary/10 to-primary/5 border-primary/20">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpen className="h-5 w-5" />
            Next Steps
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-sm text-muted-foreground">
            Ready to explore more? Check out these related guides:
          </p>
          <div className="flex gap-2 flex-wrap">
            <Link href="/help/catalog">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                Data Catalog Guide
              </Badge>
            </Link>
            <Link href="/docs/trino-sql">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                SQL Reference
              </Badge>
            </Link>
            <Link href="/docs/optimization">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                Query Optimization
              </Badge>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
