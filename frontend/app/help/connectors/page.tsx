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
                Configure sync schedule (real-time, hourly, daily). Select tables to sync. Monitor sync status in the dashboard.
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
                  Connect to relational databases: PostgreSQL, MySQL, Oracle, SQL Server, Snowflake.
                  Supports CDC (Change Data Capture) for real-time sync.
                </p>
                <div className="flex gap-2 mt-2">
                  <Badge variant="secondary">CDC</Badge>
                  <Badge variant="secondary">Batch Sync</Badge>
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
                  Connect to object storage: S3, Azure Blob, GCS, HDFS, MinIO.
                  Read files in formats: Parquet, ORC, Avro, JSON, CSV.
                </p>
                <div className="flex gap-2 mt-2">
                  <Badge variant="secondary">S3 Compatible</Badge>
                  <Badge variant="secondary">Multi-format</Badge>
                  <Badge variant="secondary">Partitioning</Badge>
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
                  Connect to streaming platforms: Kafka, Kinesis, Pulsar, RabbitMQ.
                  Process events in real-time with RisingWave streaming SQL.
                </p>
                <div className="flex gap-2 mt-2">
                  <Badge variant="secondary">Real-time</Badge>
                  <Badge variant="secondary">Schema Registry</Badge>
                  <Badge variant="secondary">Exactly-Once</Badge>
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
              <li>Store credentials in secrets manager (Vault/AWS Secrets Manager)</li>
              <li>Enable SSL/TLS for database connections</li>
              <li>Use IAM roles instead of access keys for cloud storage</li>
              <li>Rotate credentials regularly and update connector configs</li>
            </ul>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-muted-foreground" />
              <h3 className="font-semibold">Performance</h3>
            </div>
            <ul className="text-sm text-muted-foreground space-y-1 ml-6 list-disc">
              <li>Use incremental sync mode for large tables (timestamp/ID column)</li>
              <li>Schedule heavy syncs during off-peak hours</li>
              <li>Enable parallel sync for multi-table connectors</li>
              <li>Use CDC (Change Data Capture) for real-time databases</li>
              <li>Set appropriate batch sizes (default: 10,000 rows)</li>
            </ul>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4 text-muted-foreground" />
              <h3 className="font-semibold">Data Quality</h3>
            </div>
            <ul className="text-sm text-muted-foreground space-y-1 ml-6 list-disc">
              <li>Enable schema validation to catch type mismatches</li>
              <li>Configure error handling (skip vs. fail on errors)</li>
              <li>Set up data quality checks in destination tables</li>
              <li>Monitor null percentages and cardinality changes</li>
              <li>Test with a subset of data before full sync</li>
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
            <h3 className="font-semibold">Database Replication</h3>
            <p className="text-sm text-muted-foreground">
              Replicate production databases (PostgreSQL, MySQL) to DataPond for analytics without impacting transactional workloads.
              Use CDC for real-time replication with minimal lag.
            </p>
            <pre className="bg-muted p-3 rounded-lg text-xs">
              <code>PostgreSQL → CDC Connector → RisingWave → Iceberg Table</code>
            </pre>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Cloud Storage Ingestion</h3>
            <p className="text-sm text-muted-foreground">
              Ingest files from S3/GCS/Azure Blob Storage into Iceberg tables. Supports automatic schema detection for JSON/CSV.
              Ideal for batch data from data vendors or logs.
            </p>
            <pre className="bg-muted p-3 rounded-lg text-xs">
              <code>S3 Bucket → File Connector → Spark Job → Iceberg Table</code>
            </pre>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Streaming Analytics</h3>
            <p className="text-sm text-muted-foreground">
              Process events from Kafka/Kinesis in real-time using RisingWave streaming SQL.
              Write results to Iceberg for historical analysis and dashboards.
            </p>
            <pre className="bg-muted p-3 rounded-lg text-xs">
              <code>Kafka Topic → RisingWave Source → Streaming SQL → Iceberg Sink</code>
            </pre>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Data Migration</h3>
            <p className="text-sm text-muted-foreground">
              Migrate from legacy data warehouses (Oracle, Teradata) to DataPond.
              Use full sync for initial load, then switch to incremental sync.
            </p>
            <pre className="bg-muted p-3 rounded-lg text-xs">
              <code>Oracle DB → Full Sync → Iceberg Table → Validate → Switch to CDC</code>
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
              Use the "Test Connection" button in the setup wizard. For data sync, create a test connection with filters (e.g., <code className="bg-muted px-1 py-0.5 rounded">LIMIT 1000</code>)
              to verify schema and data quality before full sync.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Can I pause or stop a running sync?</h3>
            <p className="text-sm text-muted-foreground">
              Yes! Go to Connectors → Active Connections → click the connector → click "Pause Sync". Resume anytime without losing progress.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">How do I monitor connector health?</h3>
            <p className="text-sm text-muted-foreground">
              Check the status badge on the connector card (Healthy / Warning / Error). Click the connector to see detailed metrics:
              sync latency, error rate, rows synced, last successful sync.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">What happens if a sync fails?</h3>
            <p className="text-sm text-muted-foreground">
              Connectors auto-retry with exponential backoff (3 retries). If all retries fail, sync pauses and sends an alert.
              Check logs for error details. Fix the issue (e.g., credentials, network) and resume.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">Can I sync only specific tables?</h3>
            <p className="text-sm text-muted-foreground">
              Yes! In the connector setup, you can select specific tables/schemas to sync. Use regex patterns for bulk selection.
              Example: <code className="bg-muted px-1 py-0.5 rounded">sales_.*</code> syncs all tables starting with "sales_".
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold">How do I handle schema changes?</h3>
            <p className="text-sm text-muted-foreground">
              Enable "Auto-detect schema changes" in connector settings. Iceberg supports schema evolution (add/rename columns).
              Breaking changes (delete column, change type) require manual migration.
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
              Enable schema validation to catch type issues early. Check for NULL values in non-nullable columns.
              For JSON/CSV files, review auto-detected schema and adjust mappings manually if needed.
            </AlertDescription>
          </Alert>

          <Alert>
            <CheckCircle2 className="h-4 w-4" />
            <AlertTitle>CDC connector not capturing changes</AlertTitle>
            <AlertDescription>
              Ensure database has CDC/replication enabled (PostgreSQL: logical replication, MySQL: binlog).
              Check that the connector user has REPLICATION permissions. Review CDC slot lag in database.
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
