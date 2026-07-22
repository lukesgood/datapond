"use client"

import Link from "next/link"
import { useState } from "react"
import type { LucideIcon } from "lucide-react"
import {
  ArrowRight,
  BookOpen,
  Boxes,
  Database,
  ExternalLink,
  FileText,
  HelpCircle,
  Plug,
  Rocket,
  Search,
  Settings,
  ShieldCheck,
} from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"

type DocLink = {
  title: string
  description: string
  href: string
  badge?: "Shipped" | "Optional" | "Reference" | "Roadmap"
}

type DocCategory = {
  title: string
  description: string
  icon: LucideIcon
  docs: DocLink[]
}

// Encode lifecycle status as color so readers can scan shipped vs. optional vs. roadmap at a glance.
const STATUS_STYLES: Record<NonNullable<DocLink["badge"]>, string> = {
  Shipped: "bg-[var(--dp-good)]/10 text-[var(--dp-good)] border-[var(--dp-good)]/25",
  Optional: "bg-[var(--dp-warn)]/10 text-[var(--dp-warn)] border-[var(--dp-warn)]/25",
  Reference: "bg-primary/10 text-primary border-primary/25",
  Roadmap: "bg-muted text-muted-foreground border-border",
}

const docCategories: DocCategory[] = [
  {
    title: "Start Here",
    description: "Understand the product and complete the governed RAG path",
    icon: Rocket,
    docs: [
      { title: "Platform Overview", description: "What Portable Core ships and where adapters fit", href: "/docs/overview", badge: "Shipped" },
      { title: "Quick Start", description: "Create a collection, ingest content, and ask a cited question", href: "/docs/quickstart" },
      { title: "Core Workflow", description: "Connect → organize → ground → serve → govern", href: "/docs/core-workflow" },
      { title: "Architecture", description: "Portable application layer, adapter contracts, and add-ons", href: "/docs/architecture" },
    ],
  },
  {
    title: "Deployment Profiles",
    description: "Choose an operating model without confusing profile intent with installed services",
    icon: Boxes,
    docs: [
      { title: "Profile Matrix", description: "Compare supported, reference, community, and development profiles", href: "/docs/profiles", badge: "Shipped" },
      { title: "Portable Core · AWS", description: "Lean five-workload starter using S3 and Bedrock", href: "/docs/portable-core" },
      { title: "AWS Single-Node Reference", description: "EC2/K3s with Aurora, S3, Glue/Athena, and Bedrock", href: "/docs/aws-reference", badge: "Reference" },
      { title: "Sovereign OSS Extended", description: "Self-hosted core plus selected open-source add-ons", href: "/docs/sovereign", badge: "Optional" },
    ],
  },
  {
    title: "Portability & Exit",
    description: "Keep data, models, and deployment choices replaceable",
    icon: Plug,
    docs: [
      { title: "Open Contracts", description: "S3 API, PostgreSQL/pgvector, LiteLLM, Iceberg, OIDC", href: "/docs/open-contracts", badge: "Shipped" },
      { title: "Exit Strategy", description: "What can move today and which migration automation remains roadmap", href: "/docs/exit-strategy" },
      { title: "Optional Add-ons", description: "Trino, Polaris, RisingWave, OpenMetadata, Airflow, Jupyter, MLflow", href: "/docs/addons", badge: "Optional" },
      { title: "Backup & Restore", description: "Protect PostgreSQL, objects, and encryption keys", href: "/docs/backup-restore" },
    ],
  },
  {
    title: "Build & Govern",
    description: "Use the shipped AI core and capability-gated data modules",
    icon: Database,
    docs: [
      { title: "Knowledge & RAG", description: "Collections, ingestion, embeddings, retrieval, reranking, and citations", href: "/docs/knowledge-rag", badge: "Shipped" },
      { title: "Sources", description: "Database and object ingestion when a catalog adapter is enabled", href: "/docs/sources", badge: "Optional" },
      { title: "Catalog & Query", description: "Glue/Athena or Polaris/Trino, selected by deployment profile", href: "/docs/catalog-query", badge: "Optional" },
      { title: "AI Gateway", description: "Provider routing, virtual keys, usage, and spend attribution", href: "/docs/ai-gateway", badge: "Shipped" },
      { title: "Governance", description: "Collection access, PII controls, audit, lineage, and cost governance", href: "/docs/governance", badge: "Shipped" },
    ],
  },
  {
    title: "Operate",
    description: "Configure, secure, observe, and troubleshoot a deployment",
    icon: Settings,
    docs: [
      { title: "Configuration", description: "Helm values, runtime profile metadata, and feature flags", href: "/docs/configuration" },
      { title: "Monitoring", description: "Workload health, external services, metrics, and spend", href: "/docs/monitoring" },
      { title: "Authentication", description: "Local JWT, passkeys, LDAP, and Enterprise OIDC", href: "/docs/authentication" },
      { title: "Troubleshooting", description: "Diagnose adapters, storage, models, and profile-gated modules", href: "/docs/troubleshooting" },
      { title: "REST API", description: "FastAPI endpoints for knowledge, AI, governance, and optional data modules", href: "/docs/api" },
    ],
  },
]

export default function DocsPage() {
  const [searchQuery, setSearchQuery] = useState("")
  const needle = searchQuery.trim().toLowerCase()
  const filteredCategories = docCategories
    .map((category) => ({
      ...category,
      docs: category.docs.filter((doc) =>
        !needle || `${doc.title} ${doc.description} ${doc.badge ?? ""}`.toLowerCase().includes(needle),
      ),
    }))
    .filter((category) => category.docs.length > 0)

  const totalDocs = docCategories.reduce((sum, category) => sum + category.docs.length, 0)
  const shownDocs = filteredCategories.reduce((sum, category) => sum + category.docs.length, 0)

  return (
    <div className="flex-1 space-y-6 p-8 pt-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/dashboard">Home</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>Documentation</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">Product truth</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">Documentation</h1>
          <p className="mt-2 max-w-2xl text-muted-foreground">
            Build on the Portable Core, choose adapters deliberately, and know which capabilities are shipped, optional, or roadmap.
          </p>
        </div>
        <Link href="/help">
          <Badge variant="outline" className="gap-1 px-3 py-1.5 cursor-pointer hover:bg-muted">
            <HelpCircle className="h-3 w-3" /> Guides
          </Badge>
        </Link>
      </div>

      <Card className="border-primary/20 bg-primary/5">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 text-primary" />
            <div>
              <p className="text-sm font-semibold">One core, explicit adapters</p>
              <p className="text-xs text-muted-foreground">
                Disabled components are not silently replaced by cloud services. The active profile and capabilities are shown in the app shell.
              </p>
            </div>
          </div>
          <Link className="text-sm font-medium text-primary hover:underline" href="/docs/profiles">Choose a profile →</Link>
        </CardContent>
      </Card>

      <div className="space-y-1.5">
        <div className="relative max-w-xl">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search concepts, profiles, or capabilities…"
            className="pl-9"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            aria-label="Search documentation"
          />
        </div>
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {needle
            ? `${shownDocs} of ${totalDocs} article${totalDocs === 1 ? "" : "s"} match`
            : `${totalDocs} articles across ${docCategories.length} sections`}
        </p>
      </div>

      <div className="space-y-7">
        {filteredCategories.length === 0 ? (
          <Card><CardContent className="py-12 text-center text-muted-foreground">No documentation found for “{searchQuery}”.</CardContent></Card>
        ) : filteredCategories.map((category) => {
          const Icon = category.icon
          return (
            <section key={category.title} className="space-y-3">
              <div className="flex items-center gap-2">
                <Icon className="h-5 w-5 text-primary" />
                <h2 className="text-xl font-bold">{category.title}</h2>
              </div>
              <p className="text-sm text-muted-foreground">{category.description}</p>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {category.docs.map((doc) => (
                  <Link key={doc.href} href={doc.href}>
                    <Card className="group h-full transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
                      <CardHeader>
                        <div className="flex items-start justify-between gap-2">
                          <CardTitle className="flex items-center gap-1.5 text-base">
                            {doc.title}
                            {/* Arrow morphs in on hover to signal the card is navigable */}
                            <ArrowRight className="h-4 w-4 shrink-0 -translate-x-1 text-muted-foreground opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100" />
                          </CardTitle>
                          {doc.badge && (
                            <Badge variant="outline" className={`shrink-0 text-[10px] ${STATUS_STYLES[doc.badge]}`}>{doc.badge}</Badge>
                          )}
                        </div>
                        <CardDescription>{doc.description}</CardDescription>
                      </CardHeader>
                    </Card>
                  </Link>
                ))}
              </div>
            </section>
          )
        })}
      </div>

      <Card className="bg-muted/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><FileText className="h-5 w-5" />Need implementation detail?</CardTitle>
          <CardDescription>The repository docs are the canonical operator reference; historical plans are not current product truth.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <Link className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline" href="/help">
            <BookOpen className="h-4 w-4" /> Open guides
          </Link>
          <a className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline" href="mailto:support@datapond.ai">
            <ExternalLink className="h-4 w-4" /> Contact support
          </a>
        </CardContent>
      </Card>
    </div>
  )
}
