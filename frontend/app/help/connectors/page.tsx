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
  Plug,
  Database,
  HardDrive,
  Radio,
  Shield,
  AlertCircle,
  CheckCircle2,
  Lightbulb,
  BookOpen,
  Settings,
  Activity,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import Link from "next/link"

export default function ConnectorsHelpPage() {
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
            <BreadcrumbPage>Connectors</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-start gap-4">
        <div className="inline-flex p-3 rounded-lg bg-purple-500/10">
          <Plug className="h-8 w-8 text-purple-500" />
        </div>
        <div>
          <h1 className="text-4xl font-bold tracking-tight">Connectors Guide</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Connect to databases, storage, and streaming sources
          </p>
        </div>
      </div>

      {/* Quick Start */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plug className="h-5 w-5" />
            Quick Start
          </CardTitle>
          <CardDescription>Set up your first connector in 4 steps</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold">
              1
            </div>
            <div>
              <h3 className="font-semibold">Browse connector marketplace</h3>
              <p className="text-sm text-muted-foreground">
                Navigate to{" "}
                <Link href="/connectors" className="text-primary hover:underline">
                  Connectors
                </Link>{" "}
                and browse by category (Databases, Storage, Streaming)
              </p>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold">
              2
            </div>
            <div>
              <h3 className="font-semibold">Select your connector</h3>
              <p className="text-sm text-muted-foreground">
                Click on the connector card (e.g., PostgreSQL, MySQL, S3). Review supported features and prerequisites.
              </p>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold">
              3
            </div>
            <div>
              <h3 className="font-semibold">Configure connection</h3>
              <p className="text-sm text-muted-foreground">
                Fill in connection details (host, port, credentials). Test the connection before saving. Use secrets manager for passwords.
              </p>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold">
              4
            </div>
            <div>
              <h3 className="font-semibold">Start syncing data</h3>
              <p className="text-sm text-muted-foreground">
                Choose full or incremental batch mode, select the source tables, and run the initial sync. Scheduling controls appear only when the required pipeline capability is enabled.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Connector Categories */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Connector Categories
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-3">
            <div className="flex items-start gap-3">
              <div className="inline-flex p-2 rounded-lg bg-blue-500/10 flex-shrink-0">
                <Database className="h-5 w-5 text-blue-500" />
              </div>
              <div>
                <h3 className="font-semibold">Database Connectors</h3>
                <p className="text-sm text-muted-foreground">
                  Shipped source paths include PostgreSQL, MySQL, REST APIs, custom Python, and SQLAlchemy URLs for installed database drivers.
                  Table ingestion supports full and incremental batch sync; real-time PostgreSQL CDC belongs to the optional RisingWave Streaming path.
                </p>
                <div className="flex gap-2 mt-2">
                  <Badge variant="secondary">Batch Sync</Badge>
                  <Badge variant="secondary">Incremental</Badge>
                  <Badge variant="secondary">Schema Detection</Badge>
                </div>
              </div>
            </div>

            <div className="flex items-start gap-3">
              <div className="inline-flex p-2 rounded-lg bg-green-500/10 flex-shrink-0">
                <HardDrive className="h-5 w-5 text-green-500" />
              </div>
              <div>
                <h3 className="font-semibold">Storage Connectors</h3>
                <p className="text-sm text-muted-foreground">
                  Connect to Amazon S3 or an S3-compatible endpoint such as MinIO.
                  The current structured-file path reads CSV, JSON/JSONL, and Parquet objects.
                </p>
                <div className="flex gap-2 mt-2">
                  <Badge variant="secondary">S3 API</Badge>
                  <Badge variant="secondary">CSV / JSON / Parquet</Badge>
                  <Badge variant="secondary">Prefix Discovery</Badge>
                </div>
              </div>
            </div>

            <div className="flex items-start gap-3">
              <div className="inline-flex p-2 rounded-lg bg-orange-500/10 flex-shrink-0">
                <Radio className="h-5 w-5 text-orange-500" />
              </div>
              <div>
                <h3 className="font-semibold">Streaming Connectors</h3>
                <p className="text-sm text-muted-foreground">
                  Connect to Kafka and supported CDC sources when the Streaming add-on is enabled. RisingWave provides the current self-hosted streaming SQL path.
                </p>
                <div className="flex gap-2 mt-2">
                  <Badge variant="secondary">Optional add-on</Badge>
                  <Badge variant="secondary">PostgreSQL CDC</Badge>
                  <Badge variant="secondary">Kafka sources</Badge>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Configuration Best Practices */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings className="h-5 w-5" />
            Configuration Best Practices
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-muted-foreground" />
              <h3 className="font-semibold">Security</h3>
            </div>
            <ul className="text-sm text-muted-foreground space-y-1 ml-6 list-disc">
              <li>Use read-only database users for connectors when possible</li>
              <li>Keep credentials out of exported configs; DataPond encrypts persisted connector secrets</li>
              <li>Enable SSL/TLS for database connections</li>
              <li>Prefer the runtime credential chain for S3, or use narrowly scoped keys</li>
              <li>Rotate credentials regularly and update connector configs</li>
            </ul>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-muted-foreground" />
              <h3 className="font-semibold">Performance</h3>
            </div>
            <ul className="text-sm text-muted-foreground space-y-1 ml-6 list-disc">
              <li>Use incremental batch mode for large tables with a stable timestamp or ID column</li>
              <li>Run heavy manual syncs during off-peak source-database hours</li>
              <li>Select only the tables needed at the destination</li>
              <li>Index the source column used as the incremental watermark</li>
              <li>Use the optional PostgreSQL CDC path only when batch freshness is insufficient</li>
            </ul>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4 text-muted-foreground" />
              <h3 className="font-semibold">Data Quality</h3>
            </div>
            <ul className="text-sm text-muted-foreground space-y-1 ml-6 list-disc">
              <li>Review the detected source schema before the first full sync</li>
              <li>Normalize ambiguous types and required-column NULL values at the source</li>
              <li>Compare source and destination row counts after the initial load</li>
              <li>Inspect run errors before retrying a failed table</li>
              <li>Validate a small, non-production source first when possible</li>
            </ul>
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
            <h3 className="font-semibold">Database Analytics Copy</h3>
            <p className="text-sm text-muted-foreground">
              Copy PostgreSQL or MySQL tables for analytics without running queries against transactional workloads.
              Use full or incremental batch sync here; enable the separate RisingWave Streaming add-on when real-time CDC is required.
            </p>
            <pre className="bg-muted p-3 rounded-lg text-xs">
              <code>PostgreSQL / MySQL → Batch Connector → Iceberg Table</code>
            </pre>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Object Storage Ingestion</h3>
            <p className="text-sm text-muted-foreground">
              Ingest CSV, JSON/JSONL, or Parquet files from Amazon S3 or an S3-compatible endpoint into Iceberg tables.
              This path supports prefix discovery and structured-file schema inference.
            </p>
            <pre className="bg-muted p-3 rounded-lg text-xs">
              <code>S3-compatible bucket → Storage Connector → Iceberg Table</code>
            </pre>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Streaming Analytics</h3>
            <p className="text-sm text-muted-foreground">
              Process supported Kafka/CDC events with the optional RisingWave streaming add-on, then write selected results to Iceberg.
            </p>
            <pre className="bg-muted p-3 rounded-lg text-xs">
              <code>Kafka / CDC → RisingWave add-on → Streaming SQL → Iceberg Sink</code>
            </pre>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Backfill and Incremental Refresh</h3>
            <p className="text-sm text-muted-foreground">
              Start a supported database source with a full load, validate the Iceberg destination, then configure an incremental column for recurring batch refreshes.
              Additional SQLAlchemy databases depend on the required dialect and driver being installed.
            </p>
            <pre className="bg-muted p-3 rounded-lg text-xs">
              <code>Supported DB → Full Sync → Validate → Incremental Batch Sync</code>
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
            <h3 className="font-semibold">How do I test a connector before full sync?</h3>
            <p className="text-sm text-muted-foreground">
              Use the &quot;Test Connection&quot; button in the setup wizard. For data sync, create a test connection with filters (e.g., <code className="bg-muted px-1 py-0.5 rounded">LIMIT 1000</code>)
              to verify schema and data quality before full sync.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Can I pause or resume a running sync?</h3>
            <p className="text-sm text-muted-foreground">
              Not currently. The connector UI does not expose pause/resume for an in-flight run. Inspect the run result, change its configuration if needed, and trigger the next sync manually.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">How do I monitor connector health?</h3>
            <p className="text-sm text-muted-foreground">
              Check the connection status and last-sync time in Active Connections. Open a connection to inspect recent runs, rows processed, and any returned error details.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">What happens if a sync fails?</h3>
            <p className="text-sm text-muted-foreground">
              A failed run remains visible with its error status. Inspect the error and backend logs, correct credentials, networking, mapping, or source data, then trigger Sync now again. Automatic pause/resume and alert delivery are not part of the current connector workflow.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Can I sync only specific tables?</h3>
            <p className="text-sm text-muted-foreground">
              Yes. Use the setup wizard table picker to enable only the tables that should be copied, and review the selected-table count before saving the connection.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">How do I handle schema changes?</h3>
            <p className="text-sm text-muted-foreground">
              Compare the detected source schema with the destination before syncing a changed table. Additive Iceberg changes may be compatible, but destructive or type-changing migrations should be planned and validated explicitly; there is no universal auto-migrate switch.
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
            <AlertTitle>Connection test fails</AlertTitle>
            <AlertDescription>
              Check network connectivity (firewall, security groups). Verify credentials are correct.
              For databases, ensure the user has SELECT permissions. For cloud storage, check IAM roles/policies.
            </AlertDescription>
          </Alert>

          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Sync is very slow</AlertTitle>
            <AlertDescription>
              Check source database load (high CPU/memory). Reduce batch size if the source is constrained.
              For large tables, switch to incremental sync. Consider adding indexes on timestamp/ID columns.
            </AlertDescription>
          </Alert>

          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Data type mismatch errors</AlertTitle>
            <AlertDescription>
              Compare detected source types with the destination schema and check for NULL values in required columns.
              For CSV or JSON files, inspect the inferred schema and normalize ambiguous values before retrying.
            </AlertDescription>
          </Alert>

          <Alert>
            <CheckCircle2 className="h-4 w-4" />
            <AlertTitle>CDC connector not capturing changes</AlertTitle>
            <AlertDescription>
              For the optional PostgreSQL CDC path, enable logical replication and grant the connector user the required replication permissions. Then inspect the PostgreSQL replication slot and the RisingWave workload logs.
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
            Ready to work with your synced data? Check out these related guides:
          </p>
          <div className="flex gap-2 flex-wrap">
            <Link href="/help/catalog">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                Data Catalog Guide
              </Badge>
            </Link>
            <Link href="/help/sql-lab">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                SQL Lab Guide
              </Badge>
            </Link>
            <Link href="/docs/pipelines">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                Pipeline Development
              </Badge>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
