"use client"

import Link from "next/link"
import type { LucideIcon } from "lucide-react"
import { ArrowDownToLine, ArrowRight, BookOpen, Bot, Code2, Database, HardDrive, Layers, ShieldCheck, Sparkles } from "lucide-react"
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
import { useCapabilities } from "@/lib/capabilities"
import { getProductProfile } from "@/lib/product-profile"

type Guide = {
  title: string
  description: string
  icon: LucideIcon
  href: string
  capability?: string
  topics: string[]
}

const guides: Guide[] = [
  {
    title: "Knowledge & RAG",
    description: "Build collections, test retrieval, and get cited answers",
    icon: Sparkles,
    href: "/knowledge",
    topics: ["Collections", "Ingestion", "Semantic search", "Citations"],
  },
  {
    title: "AI Gateway",
    description: "Route models and inspect usage through one provider boundary",
    icon: Bot,
    href: "/ai",
    topics: ["Models", "Routing", "Usage", "Spend"],
  },
  {
    title: "Governance",
    description: "Control collection access, protect PII, and review audit and cost",
    icon: ShieldCheck,
    href: "/governance",
    topics: ["Access", "PII", "Audit", "Cost"],
  },
  {
    title: "Sources",
    description: "Sync databases and table sources through the active catalog adapter",
    icon: ArrowDownToLine,
    href: "/help/connectors",
    capability: "connectors",
    topics: ["Setup", "Credentials", "Sync", "Freshness"],
  },
  {
    title: "Catalog",
    description: "Browse tables and send selected content to Knowledge",
    icon: Database,
    href: "/help/catalog",
    capability: "catalog",
    topics: ["Namespaces", "Schema", "Preview", "Send to Knowledge"],
  },
  {
    title: "SQL Lab",
    description: "Query through the configured Athena or Trino adapter",
    icon: Code2,
    href: "/help/sql-lab",
    capability: "query",
    topics: ["Editor", "Schema", "History", "Results"],
  },
]

const quickHelp = [
  {
    question: "What should I do first?",
    answer: "Create a Knowledge collection, ingest a small representative source, test semantic search, and only then test cited RAG answers.",
    href: "/docs/quickstart",
  },
  {
    question: "Why is a menu missing?",
    answer: "Optional menus appear only when the current profile explicitly enables their adapter or add-on. Disabled OSS is not automatically replaced by a cloud service.",
    href: "/docs/profiles",
  },
  {
    question: "How portable is my deployment?",
    answer: "The core uses S3-compatible objects, PostgreSQL/pgvector, LiteLLM, REST APIs, and Kubernetes. Review the documented migration limits before an exit drill.",
    href: "/docs/exit-strategy",
  },
  {
    question: "How is Knowledge access controlled?",
    answer: "Collections use owner, administrator, and explicit sharing checks. Table policy enforcement is a separate optional data-plane capability.",
    href: "/docs/governance",
  },
  {
    question: "Where do I check an incident?",
    answer: "Start with the active profile, then inspect Services and System before troubleshooting the configured storage, database, catalog, query, or model adapter.",
    href: "/docs/troubleshooting",
  },
]

export default function HelpPage() {
  const caps = useCapabilities()
  const profile = getProductProfile(caps)
  // Guides explain setup and troubleshooting even when their optional product
  // capability is disabled; direct product routes remain capability-gated.
  const visibleGuides = guides

  return (
    <div className="flex-1 space-y-6 p-8 pt-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/dashboard">Home</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>Guides</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">{profile.label}</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">Guides</h1>
        <p className="mt-2 text-muted-foreground">Follow the core AI workflow first; add data-plane modules only when the use case requires them.</p>
      </div>

      <Card className="border-primary/20 bg-primary/5">
        <CardContent className="flex flex-wrap items-start justify-between gap-4 py-4">
          <div className="flex gap-3">
            <Layers className="mt-0.5 h-5 w-5 text-primary" />
            <div>
              <p className="text-sm font-semibold">Current profile: {profile.label}</p>
              <p className="text-xs text-muted-foreground">{profile.description}</p>
            </div>
          </div>
          <Link href="/docs/profiles" className="text-sm font-medium text-primary hover:underline">Compare profiles →</Link>
        </CardContent>
      </Card>

      <section className="space-y-3">
        <h2 className="text-xl font-bold">Available workflows</h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visibleGuides.map((guide) => {
            const Icon = guide.icon
            return (
              <Link key={guide.href} href={guide.href}>
                <Card className="group h-full transition-all hover:-translate-y-0.5 hover:shadow-md">
                  <CardHeader>
                    <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                      <Icon className="h-5 w-5 text-primary" />
                    </div>
                    <CardTitle className="flex items-center justify-between text-base">
                      {guide.title}<ArrowRight className="h-4 w-4 opacity-0 transition-opacity group-hover:opacity-100" />
                    </CardTitle>
                    <CardDescription>{guide.description}</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-wrap gap-1.5">
                    {guide.topics.map((topic) => <Badge key={topic} variant="secondary" className="text-xs">{topic}</Badge>)}
                  </CardContent>
                </Card>
              </Link>
            )
          })}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-bold">Quick help</h2>
        <Card>
          <CardContent className="divide-y p-0">
            {quickHelp.map((item) => (
              <Link key={item.question} href={item.href} className="group flex items-start justify-between gap-4 p-4 hover:bg-muted/50">
                <div>
                  <h3 className="font-medium group-hover:text-primary">{item.question}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{item.answer}</p>
                </div>
                <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
              </Link>
            ))}
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <Link href="/docs"><Resource icon={BookOpen} title="Documentation" description="Concepts, profiles, portability, and operations" /></Link>
        <Link href="/storage"><Resource icon={HardDrive} title="Storage" description="Inspect configured objects and usage" /></Link>
        <Link href="/services"><Resource icon={Layers} title="Services" description="Check workloads and external dependencies" /></Link>
      </section>
    </div>
  )
}

function Resource({ icon: Icon, title, description }: { icon: LucideIcon; title: string; description: string }) {
  return (
    <Card className="group h-full transition-all hover:-translate-y-0.5 hover:shadow-md">
      <CardHeader>
        <Icon className="mb-2 h-5 w-5 text-muted-foreground transition-colors group-hover:text-primary" />
        <CardTitle className="flex items-center justify-between text-base">
          {title}<ArrowRight className="h-4 w-4 opacity-0 transition-opacity group-hover:opacity-100" />
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
    </Card>
  )
}
