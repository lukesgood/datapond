"use client"

import Link from "next/link"
import { Sigma } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"

const link = "text-primary hover:underline"
const code = "rounded bg-muted px-1 font-mono text-xs"

/** Approved metrics: what they are for, how one is defined and approved, and how an
 *  agent or a person uses it. */
export default function MetricsHelpPage() {
  return (
    <div className="flex-1 space-y-6 p-8 pt-6 max-w-5xl">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/dashboard">Home</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbLink href="/help">Guides</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>Metrics</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-start gap-4">
        <div className="inline-flex p-3 rounded-lg bg-primary/10">
          <Sigma className="h-8 w-8 text-primary" />
        </div>
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-primary">Guide</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">Approved metrics</h1>
          <p className="mt-2 text-muted-foreground">
            A number an agent can cite: defined once, approved, versioned, and computed from
            the approved definition every time — not from SQL a model wrote for the occasion.
          </p>
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle>1. Define it</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>
            <Link href="/metrics" className={link}>Metrics</Link> → New metric. A definition
            names a base table and a measure — an aggregate such as{" "}
            <code className={code}>SUM(total_amount)</code>, or a ratio of aggregates such as{" "}
            <code className={code}>SUM(CASE WHEN status = &apos;cancelled&apos; THEN 1 ELSE 0 END) / COUNT(*)</code>.
          </p>
          <p>
            Optional: filters, a time column with its grains and the longest period one query
            may cover, and dimensions to break the number down by. Synonyms are the words
            people use for it (매출, sales), which is how a question finds the metric.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>2. Approve the joins a dimension needs</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          A dimension on another table (a product&apos;s category for an order line) goes
          through an approved join: Metrics → Joins lists candidates from query history and
          column names. Only many-to-one joins are accepted, so a join cannot multiply rows.
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>3. Approve the version</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Agents only see approved versions. A change is a new version, approved again; the
          previous one keeps answering until then, and results already given keep citing the
          version that produced them.
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>4. Use it</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>
            An agent, over MCP: <code className={code}>metric_list</code> to find it,{" "}
            <code className={code}>metric_values</code> to see which values a dimension
            takes before filtering, then <code className={code}>metric_query</code> with
            dimensions, a period, and optionally a sort and limit for a top-N. Its key needs{" "}
            <code className={code}>catalog:read</code> and <code className={code}>query:run</code>{" "}
            — see <Link href="/help/integrate" className={link}>Connect an agent</Link>.
          </p>
          <p>
            A person: <Link href="/query" className={link}>Analytics</Link> → Ask AI. When the
            question matches a metric, &quot;Query as metric&quot; offers it, with the period
            and dimensions read from the question for you to confirm.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>5. Trace any number back</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Every result carries its citation: metric, version, approver and the exact SQL
          that ran, after row filters and masks. The call is in{" "}
          <Link href="/governance" className={link}>Governance → Tool calls</Link> as{" "}
          <code className={code}>metric.query</code>, citing{" "}
          <code className={code}>metric:&lt;name&gt;@v&lt;N&gt;</code>.
        </CardContent>
      </Card>
    </div>
  )
}
