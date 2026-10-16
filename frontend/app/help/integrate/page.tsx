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
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { EndpointsCard, GatewayCard, McpCard } from "@/components/connect/agent-reference"
import { CollectionSnippets } from "@/components/connect/collection-snippets"

// What a key needs, by what the agent does. Tables also follow the account's role and
// any row filters or masks; a catalog with grants also needs one for the account.
const SCOPES: { use: string; scopes: string[] }[] = [
  { use: "Search and cited answers", scopes: ["knowledge:read", "ai:generate"] },
  { use: "Approved metrics", scopes: ["catalog:read", "query:run"] },
  { use: "Governed SQL", scopes: ["catalog:read", "query:run"] },
  { use: "SQL written by the model (generate_sql)", scopes: ["catalog:read", "ai:generate"] },
]

const link = "text-primary hover:underline"

/** The one place that says how an application or agent connects: the steps, then the
 *  reference (MCP, the gateway document, the REST surface) read from the running
 *  server. It used to be split between this guide and an "API & MCP" menu page that
 *  was the same reference plus a second copy of the service-account manager. */
export default function IntegrateHelpPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <IntegrateGuide />
    </Suspense>
  )
}

function IntegrateGuide() {
  // Opened from a collection's Members tab: its calls, with its name filled in.
  const collection = useSearchParams().get("collection")
  return (
    <div className="flex-1 space-y-6 p-8 pt-6 max-w-5xl">
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

      <div className="flex items-start gap-4">
        <div className="inline-flex p-3 rounded-lg bg-purple-500/10">
          <Plug className="h-8 w-8 text-purple-500" />
        </div>
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-primary">Guide</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">Connect an application or agent</h1>
          <p className="mt-2 text-muted-foreground">
            One identity per agent, a scoped key, then MCP, REST or an agent gateway. Every
            call is governed and audited as that agent.
          </p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>1. Create an agent</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            <Link href="/agents" className={link}>Agents → New agent</Link>
            {" "}(administrators). One account per agent or application, so access, audit and
            spend stay per agent.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>2. Issue a scoped, expiring key</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Issue key → tick the scopes for what the agent does → choose an expiry (90 days
            by default). The key is shown once; store it as DATAPOND_KEY.
          </p>
          <div className="divide-y rounded-md border text-sm">
            {SCOPES.map(s => (
              <div key={s.use} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <span>{s.use}</span>
                <span className="flex gap-1.5">
                  {s.scopes.map(scope => (
                    <code key={scope} className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{scope}</code>
                  ))}
                </span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>3. Grant what it may read</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            <li>
              Collections and catalogs: the agent&apos;s page, under{" "}
              <Link href="/agents" className={link}>Agents</Link> → Data access. Collections can also be
              shared from <Link href="/knowledge" className={link}>Knowledge</Link> → the collection → Members.
            </li>
            <li>
              A catalog with grants needs one for the agent (or its role) —{" "}
              <Link href="/settings?tab=catalogs" className={link}>Settings → Data catalogs</Link> lists them all.
            </li>
            <li>
              Rows and columns: row filters and masks under{" "}
              <Link href="/governance" className={link}>Governance</Link> apply to its SQL and
              metrics.
            </li>
          </ul>
        </CardContent>
      </Card>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold tracking-tight">4. Call it</h2>
        {collection && (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              Calls for the collection <code className="rounded bg-muted px-1 font-mono text-xs">{collection}</code>:
            </p>
            <CollectionSnippets name={collection} />
          </div>
        )}
        <McpCard />
        <GatewayCard />
        <EndpointsCard />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>5. See what it did</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Every call is logged against the account — what it read, cited and masked, and
            what was refused — under{" "}
            <Link href="/governance" className={link}>Governance → Audit Log</Link>; its model
            spend is under <Link href="/ai" className={link}>AI Gateway</Link>.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
