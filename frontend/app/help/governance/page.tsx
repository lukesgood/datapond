"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { ShieldCheck, Info } from "lucide-react"
import Link from "next/link"

export default function GovernanceHelpPage() {
  return (
    <div className="flex-1 space-y-6 p-8 pt-6 max-w-5xl">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/dashboard">Home</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbLink href="/help">Guides</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>Governance</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-start gap-4">
        <div className="inline-flex p-3 rounded-lg bg-[var(--dp-good)]/10">
          <ShieldCheck className="h-8 w-8 text-[var(--dp-good-text)]" />
        </div>
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-primary">Guide</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">Governance</h1>
          <p className="mt-2 text-muted-foreground">
            Decide who reads what, what never leaves in the clear, and what the record shows afterwards
          </p>
        </div>
      </div>

      <Alert>
        <Info className="h-4 w-4" />
        <AlertTitle>Governed at the data layer</AlertTitle>
        <AlertDescription>
          These controls apply wherever the data is reached from — the console, the REST API, an agent over
          MCP. A caller cannot route around them by changing client.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader><CardTitle>1. Who can read a collection</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            A collection has an owner. Administrators see everything. Anyone else needs an explicit grant:{" "}
            <Link href="/knowledge" className="text-primary hover:underline">Knowledge</Link> → the collection
            → Members → add a username as <span className="font-mono text-foreground">reader</span> or{" "}
            <span className="font-mono text-foreground">editor</span>.
          </p>
          <p className="text-sm text-muted-foreground">
            Service accounts are granted the same way, by their <span className="font-mono text-foreground">svc-…</span>{" "}
            username. An agent holding a valid key still sees nothing until a collection is shared with it.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>2. Personal data, and who decides how hard it is masked</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Three modes: <span className="font-mono text-foreground">off</span>,{" "}
            <span className="font-mono text-foreground">mask</span> (findings replaced with a tag), and{" "}
            <span className="font-mono text-foreground">block</span> (the request is refused rather than answered).
          </p>
          <p className="text-sm text-muted-foreground">
            The deployment sets a default; a collection or a caller can be held to something stricter. The
            effective mode is always the <span className="font-medium text-foreground">strictest</span> of the
            three — which means a per-collection setting can tighten masking but can never loosen what the
            deployment asked for. A value nobody recognises is ignored rather than read as{" "}
            <span className="font-mono text-foreground">off</span>, so a typo in a policy cannot quietly
            disable protection.
          </p>
          <p className="text-sm text-muted-foreground">
            Korean identifiers are checksum-verified where the format allows it — 주민등록번호 and 신용카드 —
            so ordinary numbers are not swept up.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>3. Credentials are treated as personal data</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            The same guardrail detects structured secrets: AWS access keys, PEM private keys, GitHub and Slack
            tokens, JWTs, and the password inside a database URL. They travel the same masking and blocking
            rules as personal data, on the same paths.
          </p>
          <p className="text-sm text-muted-foreground">
            Detection is deliberately precise rather than broad. Every pattern is either structurally
            unmistakable or anchored to the assignment that gives it meaning, and placeholders like{" "}
            <span className="font-mono text-foreground">changeme</span> or{" "}
            <span className="font-mono text-foreground">{"${DB_PASSWORD}"}</span> are filtered out — a guardrail
            that fires on ordinary config gets switched off, and then it protects nothing.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>4. What the record shows</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Every tool call — search, cited answer, governed SQL — is recorded with the caller, what was asked
            (masked, never raw), how many results came back, which sources were cited, how much was masked,
            and what came back. Refusals are recorded too: a key asking for something it may not have is the
            row an auditor most wants.
          </p>
          <p className="text-sm text-muted-foreground">
            Permission decisions land in a separate security log with the permission that was required and
            whether it was allowed or denied. Sign-ins and account changes land in the auth log.
          </p>
          <p className="text-sm text-muted-foreground">
            Read them under{" "}
            <Link href="/governance" className="text-primary hover:underline">Governance</Link> → Audit, or
            export for a SIEM from <span className="font-mono text-foreground">/api/audit/export</span> and{" "}
            <span className="font-mono text-foreground">/api/audit/tool-calls/export</span>.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>5. Make the audit trail unrewritable</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Append-only by convention is not the same as append-only by permission. The backend can be pointed
            at a runtime role that holds INSERT on the audit tables and has UPDATE, DELETE and TRUNCATE
            revoked, so nothing reachable through the application can rewrite history — the migration job
            keeps the owning credential, because it has to change schema.
          </p>
          <p className="text-sm text-muted-foreground">
            This is an operator cutover, not a toggle: it needs a password for that role and two values in the
            release. The procedure, and how to verify it took effect, is in{" "}
            <span className="font-mono text-foreground">docs/DEPLOY_SINGLE_NODE.md</span>. Until it is done,
            say &ldquo;append-only&rdquo; rather than &ldquo;WORM&rdquo;.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>6. Cap what a caller can spend</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Model spend is attributed per caller, so an agent that loops is visible as itself rather than as
            &ldquo;the platform&rdquo;. A caller can be given a budget; once it is reached its calls are
            refused with a clear reason rather than silently continuing to bill.
          </p>
          <p className="text-sm text-muted-foreground">
            Usage and spend are under{" "}
            <Link href="/ai" className="text-primary hover:underline">AI Gateway</Link>. Remember that a
            scheduled re-embed spends on every tick — a collection refreshing hourly costs whether or not its
            source changed.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>7. Rows and columns, when the RLS engine is configured</CardTitle></CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Table-level policies — row filters and column masking — are a separate, profile-dependent
            capability from collection access. Where it is configured, the policies apply to governed SQL and
            are managed under{" "}
            <Link href="/governance" className="text-primary hover:underline">Governance</Link> → Policies.
            Collection access is application-level ownership and sharing; the two are not the same mechanism
            and neither implies the other.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Known limits worth saying out loud</CardTitle></CardHeader>
        <CardContent>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground marker:text-primary/60">
            <li><span className="font-medium text-foreground">Sensitivity labels are not editable from the console yet.</span> A collection can carry a label that raises its masking floor and forbids sending its content to an external model, but there is no screen or API to set it — today it is a database value.</li>
            <li><span className="font-medium text-foreground">Egress control is application-level.</span> Under a local-only policy the product refuses external providers, and fails closed when it cannot verify one is local. That is not a network control, and it is not a substitute for one where network separation is required.</li>
            <li><span className="font-medium text-foreground">Unstructured content is guarded, not understood.</span> Retrieved passages are masked and marked as data rather than instructions, and instruction-shaped text is counted for an operator to see — nothing is rewritten, because legitimate documents quote those phrases too.</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
