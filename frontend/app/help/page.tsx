"use client"

import Link from "next/link"
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
  Database,
  Plug,
  BookOpen,
  Sparkles,
  ShieldCheck,
  HardDrive,
  ArrowRight,
  ExternalLink
} from "lucide-react"

// Guides for the foundation-live features. The first three have written
// walkthroughs under /help/*; the rest link straight to the feature page.
const guides = [
  {
    title: "SQL Lab",
    description: "Write and run SQL against your data — Athena on AWS, Trino on the full profile",
    icon: Code2,
    href: "/help/sql-lab",
    color: "text-[var(--chart-1)]",
    bgColor: "bg-[var(--chart-1)]/10",
    topics: ["Query editor", "Schema browser", "Query history", "Keyboard shortcuts"],
  },
  {
    title: "Data Catalog",
    description: "Browse, search, and preview Iceberg tables in the Glue catalog",
    icon: Database,
    href: "/help/catalog",
    color: "text-[var(--chart-2)]",
    bgColor: "bg-[var(--chart-2)]/10",
    topics: ["Table browser", "Schema explorer", "Column stats", "Send to Knowledge"],
  },
  {
    title: "Connectors",
    description: "Bring data in from databases, storage, and streaming sources",
    icon: Plug,
    href: "/help/connectors",
    color: "text-[var(--chart-3)]",
    bgColor: "bg-[var(--chart-3)]/10",
    topics: ["Connector setup", "Authentication", "Data sync", "Health monitoring"],
  },
  {
    title: "Knowledge & RAG",
    description: "Build vector collections and get cited answers from your documents",
    icon: Sparkles,
    href: "/knowledge",
    color: "text-[var(--chart-4)]",
    bgColor: "bg-[var(--chart-4)]/10",
    topics: ["Collections", "Ingest documents", "Semantic search", "Cited RAG answers"],
  },
  {
    title: "Governance",
    description: "Control access, mask PII, and keep an audit trail across your data",
    icon: ShieldCheck,
    href: "/governance",
    color: "text-[var(--chart-5)]",
    bgColor: "bg-[var(--chart-5)]/10",
    topics: ["Row-level security", "PII masking", "Audit log", "Cost attribution"],
  },
  {
    title: "Storage",
    description: "Inspect the S3 buckets and objects backing your data foundation",
    icon: HardDrive,
    href: "/storage",
    color: "text-primary",
    bgColor: "bg-primary/10",
    topics: ["Buckets", "Objects", "Usage", "Lifecycle"],
  },
]

const quickHelp = [
  {
    question: "How do I execute a SQL query?",
    answer: "Open SQL Lab, write your query, and press Ctrl+Enter or click Execute.",
    href: "/help/sql-lab#execute-query",
  },
  {
    question: "Where can I see all my tables?",
    answer: "Open Data Catalog to browse every Iceberg table across namespaces, with column stats and previews.",
    href: "/help/catalog",
  },
  {
    question: "How do I connect a new data source?",
    answer: "Go to Connectors, choose your source type, and follow the setup wizard.",
    href: "/help/connectors#setup",
  },
  {
    question: "How do I build a RAG knowledge base?",
    answer: "In Knowledge, create a collection, ingest text, tables, or S3 objects to embed them, then search or ask with RAG.",
    href: "/knowledge",
  },
  {
    question: "How is data access controlled?",
    answer: "Governance lets you define row-level security and PII masking per collection; every query is recorded in the audit log.",
    href: "/governance",
  },
  {
    question: "Can I revisit a past query?",
    answer: "Every query you run is saved to Query History in your browser — open the History panel in SQL Lab to re-run or copy it.",
    href: "/query",
  },
  {
    question: "What SQL dialect does DataPond use?",
    answer: "Presto/Trino-family SQL (ANSI-compatible) for OLAP — Amazon Athena on the AWS profile, self-hosted Trino on the full profile.",
    href: "/docs/trino-sql",
  },
]

const resources = [
  {
    title: "Sample Queries",
    description: "Common SQL patterns and examples",
    icon: Sparkles,
    href: "/help/sql-lab#examples",
  },
  {
    title: "SQL Reference",
    description: "Presto/Trino-family SQL, used by Athena",
    icon: Code2,
    href: "/docs/trino-sql",
  },
  {
    title: "API Reference",
    description: "Complete REST API documentation",
    icon: BookOpen,
    href: "/api/docs",
  },
]

export default function HelpPage() {
  return (
    <div className="flex-1 space-y-6 p-8 pt-6">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="/dashboard">Home</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Help & Guides</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div>
        <h1 className="text-4xl font-bold tracking-tight">Help & Guides</h1>
        <p className="text-lg text-muted-foreground mt-2">
          Learn how to make the most of DataPond
        </p>
      </div>

      {/* Feature Guides */}
      <div className="space-y-3">
        <h2 className="text-2xl font-bold">Feature Guides</h2>
        <div className="grid gap-4 md:grid-cols-3">
          {guides.map((guide, idx) => {
            const Icon = guide.icon
            return (
              <Link key={idx} href={guide.href}>
                <Card className="h-full hover:shadow-lg transition-all cursor-pointer group">
                  <CardHeader>
                    <div className={`inline-flex p-3 rounded-lg ${guide.bgColor} w-fit mb-2`}>
                      <Icon className={`h-6 w-6 ${guide.color}`} />
                    </div>
                    <CardTitle className="flex items-center justify-between">
                      {guide.title}
                      <ArrowRight className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                    </CardTitle>
                    <CardDescription>{guide.description}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap gap-1.5">
                      {guide.topics.map((topic, topicIdx) => (
                        <Badge key={topicIdx} variant="secondary" className="text-xs">
                          {topic}
                        </Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </Link>
            )
          })}
        </div>
      </div>

      {/* Quick Help - FAQ */}
      <div className="space-y-3">
        <h2 className="text-2xl font-bold">Quick Help</h2>
        <Card>
          <CardContent className="p-0">
            <div className="divide-y">
              {quickHelp.map((item, idx) => (
                <Link key={idx} href={item.href}>
                  <div className="p-4 hover:bg-muted/50 transition-colors cursor-pointer group">
                    <div className="flex items-start justify-between gap-4">
                      <div className="space-y-1 flex-1">
                        <h3 className="font-medium group-hover:text-primary transition-colors">
                          {item.question}
                        </h3>
                        <p className="text-sm text-muted-foreground">{item.answer}</p>
                      </div>
                      <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity mt-1" />
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Additional Resources */}
      <div className="space-y-3">
        <h2 className="text-2xl font-bold">Additional Resources</h2>
        <div className="grid gap-4 md:grid-cols-3">
          {resources.map((resource, idx) => {
            const Icon = resource.icon
            return (
              <Link key={idx} href={resource.href}>
                <Card className="h-full hover:shadow-md transition-shadow cursor-pointer">
                  <CardHeader>
                    <Icon className="h-5 w-5 text-muted-foreground mb-2" />
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base">{resource.title}</CardTitle>
                    </div>
                    <CardDescription className="text-sm">
                      {resource.description}
                    </CardDescription>
                  </CardHeader>
                </Card>
              </Link>
            )
          })}
        </div>
      </div>

      {/* Contact Support */}
      <Card className="bg-gradient-to-r from-primary/10 to-primary/5 border-primary/20">
        <CardHeader>
          <CardTitle>Need More Help?</CardTitle>
          <CardDescription>
            Our support team is here to assist you
          </CardDescription>
        </CardHeader>
        <CardContent className="flex gap-3">
          <Link href="/docs">
            <Badge variant="outline" className="gap-1 px-3 py-2 cursor-pointer hover:bg-background">
              <BookOpen className="h-4 w-4" />
              Full Documentation
            </Badge>
          </Link>
          <a href="mailto:support@datapond.ai" target="_blank" rel="noopener noreferrer">
            <Badge variant="outline" className="gap-1 px-3 py-2 cursor-pointer hover:bg-background">
              <ExternalLink className="h-4 w-4" />
              Contact Support
            </Badge>
          </a>
        </CardContent>
      </Card>
    </div>
  )
}
