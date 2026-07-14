"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { serviceUrls } from "@/lib/urls"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import {
  Database,
  FolderOpen,
  Table,
  GitBranch,
  Search,
  AlertCircle,
  CheckCircle2,
  Lightbulb,
  BookOpen,
  FileText,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import Link from "next/link"

export default function CatalogHelpPage() {
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
            <BreadcrumbLink href="/help">Help & Guides</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Data Catalog</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-start gap-4">
        <div className="inline-flex p-3 rounded-lg bg-green-500/10">
          <Database className="h-8 w-8 text-green-500" />
        </div>
        <div>
          <h1 className="text-4xl font-bold tracking-tight">Data Catalog Guide</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Browse, search, and explore Iceberg tables across all namespaces
          </p>
        </div>
      </div>

      {/* Quick Start */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Quick Start
          </CardTitle>
          <CardDescription>Explore your data catalog in 3 steps</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold">
              1
            </div>
            <div>
              <h3 className="font-semibold">Navigate to Data Catalog</h3>
              <p className="text-sm text-muted-foreground">
                Click "Data Catalog" in the sidebar or visit{" "}
                <Link href="/catalog" className="text-primary hover:underline">
                  /catalog
                </Link>
              </p>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold">
              2
            </div>
            <div>
              <h3 className="font-semibold">Browse or search tables</h3>
              <p className="text-sm text-muted-foreground">
                Use the search bar to find tables by name, or filter by namespace using the badge filters at the top.
              </p>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold">
              3
            </div>
            <div>
              <h3 className="font-semibold">View table details</h3>
              <p className="text-sm text-muted-foreground">
                Click any table card to see schema, metadata, statistics, and lineage information.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Key Concepts */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FolderOpen className="h-5 w-5" />
            Understanding the Catalog Structure
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge variant="outline">Catalog</Badge>
              <span className="text-sm text-muted-foreground">Top-level container (e.g., "polaris")</span>
            </div>
            <p className="text-sm text-muted-foreground ml-20">
              A catalog is the root namespace that contains all your data. DataPond uses Apache Polaris as the Iceberg REST catalog, which manages metadata and access control.
            </p>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge variant="outline">Namespace</Badge>
              <span className="text-sm text-muted-foreground">Logical grouping (e.g., "sales", "analytics")</span>
            </div>
            <p className="text-sm text-muted-foreground ml-20">
              Namespaces are like schemas or databases - they organize tables by domain, team, or use case. You can nest namespaces for hierarchical organization.
            </p>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge variant="outline">Table</Badge>
              <span className="text-sm text-muted-foreground">Iceberg table (e.g., "orders", "customers")</span>
            </div>
            <p className="text-sm text-muted-foreground ml-20">
              Tables are Apache Iceberg tables stored in SeaweedFS. They support ACID transactions, time travel, schema evolution, and hidden partitioning.
            </p>
          </div>

          <Alert className="mt-4">
            <FileText className="h-4 w-4" />
            <AlertTitle>Full Table Path</AlertTitle>
            <AlertDescription>
              Tables are referenced by their full path: <code className="bg-muted px-1 py-0.5 rounded">catalog.namespace.table</code><br/>
              Example: <code className="bg-muted px-1 py-0.5 rounded">polaris.sales.orders</code>
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>

      {/* Features Overview */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Table className="h-5 w-5" />
            Catalog Features
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Search className="h-4 w-4 text-muted-foreground" />
                <h3 className="font-semibold">Search & Filter</h3>
              </div>
              <p className="text-sm text-muted-foreground">
                Search tables by name or namespace. Filter by namespace badges to narrow results. Search is case-insensitive and matches partial strings.
              </p>
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-muted-foreground" />
                <h3 className="font-semibold">Table Metadata</h3>
              </div>
              <p className="text-sm text-muted-foreground">
                View schema (columns, types), table properties, partition specs, sort orders, and statistics. All metadata is managed by Apache Iceberg.
              </p>
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <GitBranch className="h-4 w-4 text-muted-foreground" />
                <h3 className="font-semibold">Lineage Tracking</h3>
              </div>
              <p className="text-sm text-muted-foreground">
                See upstream sources and downstream consumers for each table. Lineage is automatically collected by OpenMetadata from query logs.
              </p>
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
                <h3 className="font-semibold">Data Quality</h3>
              </div>
              <p className="text-sm text-muted-foreground">
                View data quality checks, freshness indicators, and completeness metrics. Configure alerts for data quality issues.
              </p>
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
            <h3 className="font-semibold">Data Discovery</h3>
            <p className="text-sm text-muted-foreground">
              New team members can quickly find relevant tables by browsing namespaces or searching by keywords. View table descriptions and owners to understand purpose.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Impact Analysis</h3>
            <p className="text-sm text-muted-foreground">
              Before modifying a table, check lineage to see which downstream dashboards, reports, or pipelines depend on it. Prevents breaking changes.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Data Quality Monitoring</h3>
            <p className="text-sm text-muted-foreground">
              Monitor table statistics (row counts, null percentages, unique values) over time. Set up alerts for anomalies like sudden drops in row counts.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Schema Evolution Tracking</h3>
            <p className="text-sm text-muted-foreground">
              View schema history to see when columns were added, renamed, or removed. Iceberg's schema evolution is backward-compatible and tracked in metadata.
            </p>
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
            <h3 className="font-semibold">How do I create a new table?</h3>
            <p className="text-sm text-muted-foreground">
              Tables are created by connectors (ingestion → Glue/Iceberg) or via SQL (Athena/Trino, Spark). Use <code className="bg-muted px-1 py-0.5 rounded">CREATE TABLE</code> statements.
              Example: <code className="bg-muted px-1 py-0.5 rounded">CREATE TABLE polaris.sales.orders (id INT, amount DOUBLE)</code>
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Can I delete tables from the catalog?</h3>
            <p className="text-sm text-muted-foreground">
              Yes, but only if you have admin permissions. Use <code className="bg-muted px-1 py-0.5 rounded">DROP TABLE</code> in SQL Lab.
              Dropped tables are moved to trash and can be recovered within 7 days.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">What table types are supported?</h3>
            <p className="text-sm text-muted-foreground">
              DataPond supports standard Iceberg tables and materialized views. External tables (pointing to data outside SeaweedFS) are supported via Trino connectors.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">How is lineage captured?</h3>
            <p className="text-sm text-muted-foreground">
              OpenMetadata automatically captures lineage by parsing SQL queries from Trino, Spark, and RisingWave. Manual lineage can be added via the OpenMetadata API.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Can I see historical table versions?</h3>
            <p className="text-sm text-muted-foreground">
              Yes! Iceberg supports time travel. In SQL Lab, use <code className="bg-muted px-1 py-0.5 rounded">FOR SYSTEM_TIME AS OF</code> to query past snapshots.
              Example: <code className="bg-muted px-1 py-0.5 rounded">SELECT * FROM orders FOR SYSTEM_TIME AS OF TIMESTAMP '2024-01-01 00:00:00'</code>
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
            <AlertTitle>No tables showing</AlertTitle>
            <AlertDescription>
              Check that Polaris catalog is healthy (Dashboard → Services → polaris). Ensure you have access permissions to the namespaces.
              Try refreshing the page or clearing browser cache.
            </AlertDescription>
          </Alert>

          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Table details won't load</AlertTitle>
            <AlertDescription>
              The table may have corrupted metadata. Check Polaris logs for errors. Try re-registering the table with <code className="bg-muted px-1 py-0.5 rounded">CALL system.register_table()</code>.
            </AlertDescription>
          </Alert>

          <Alert>
            <CheckCircle2 className="h-4 w-4" />
            <AlertTitle>Lineage not showing</AlertTitle>
            <AlertDescription>
              Lineage collection may be delayed (up to 15 minutes). Ensure OpenMetadata ingestion is running. Check OpenMetadata UI at <code className="bg-muted px-1 py-0.5 rounded">{serviceUrls.openmetadata()}</code>.
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
            Ready to work with your tables? Check out these related guides:
          </p>
          <div className="flex gap-2 flex-wrap">
            <Link href="/help/sql-lab">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                SQL Lab Guide
              </Badge>
            </Link>
            <Link href="/docs/polaris">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                Iceberg REST Catalog
              </Badge>
            </Link>
            <Link href="/docs/lineage">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                Data Lineage
              </Badge>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
