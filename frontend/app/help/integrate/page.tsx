"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Plug } from "lucide-react"
import Link from "next/link"

export default function IntegrateHelpPage() {
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
            <BreadcrumbPage>Integrate</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="flex items-start gap-4">
        <div className="inline-flex p-3 rounded-lg bg-purple-500/10">
          <Plug className="h-8 w-8 text-purple-500" />
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">Guide</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">Integrate an application or agent</h1>
          <p className="mt-2 text-muted-foreground">
            Create an agent identity, issue a scoped key, call search and cited answers
          </p>
        </div>
      </div>

      {/* 1. Create a service account */}
      <Card>
        <CardHeader>
          <CardTitle>1. Create a service account</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            <Link href="/settings" className="text-primary hover:underline">
              Settings → Service accounts
            </Link>{" "}
            (or{" "}
            <Link href="/connect" className="text-primary hover:underline">
              API
            </Link>{" "}
            → Service accounts). One account per agent or application. Pick the role
            that holds only what it needs; ai_engineer is the usual choice.
          </p>
        </CardContent>
      </Card>

      {/* 2. Issue a scoped, expiring key */}
      <Card>
        <CardHeader>
          <CardTitle>2. Issue a scoped, expiring key</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Issue key → tick knowledge:read and ai:generate (add query:run for governed
            SQL) → choose an expiry (90 days by default). The key is shown once; store
            it as DATAPOND_KEY.
          </p>
        </CardContent>
      </Card>

      {/* 3. Grant collections */}
      <Card>
        <CardHeader>
          <CardTitle>3. Grant collections</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            <Link href="/knowledge" className="text-primary hover:underline">
              Knowledge
            </Link>{" "}
            → the collection → Members → add the account&apos;s username (svc-…) as
            reader. Tables follow the account&apos;s role and any row filters or masks
            under{" "}
            <Link href="/governance" className="text-primary hover:underline">
              Governance
            </Link>
            .
          </p>
        </CardContent>
      </Card>

      {/* 4. Call it */}
      <Card>
        <CardHeader>
          <CardTitle>4. Call it</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
            <code>{`curl -sX POST https://your-deployment/api/ai/rag \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"collection": "faq", "question": "your question"}'`}</code>
          </pre>
          <p className="text-sm text-muted-foreground">
            Every call is logged against the account and appears in{" "}
            <Link href="/governance" className="text-primary hover:underline">
              Governance → Reports
            </Link>{" "}
            as agent tool calls.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
