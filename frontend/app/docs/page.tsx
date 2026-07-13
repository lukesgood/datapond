"use client"

import Link from "next/link"
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
import {
  Book,
  Rocket,
  Database,
  Plug,
  Code2,
  Settings,
  Shield,
  Zap,
  Search,
  ExternalLink,
  FileText,
  GitBranch,
  HelpCircle
} from "lucide-react"
import { useState } from "react"

interface DocCategory {
  title: string
  description: string
  icon: any
  docs: Array<{
    title: string
    description: string
    href: string
    badge?: string
  }>
}

const docCategories: DocCategory[] = [
  {
    title: "Getting Started",
    description: "Quick start guides and introductions",
    icon: Rocket,
    docs: [
      {
        title: "Platform Overview",
        description: "Introduction to DataPond architecture and components",
        href: "/docs/overview",
        badge: "Start Here"
      },
      {
        title: "Quick Start Guide",
        description: "Get up and running in 5 minutes",
        href: "/docs/quickstart",
      },
      {
        title: "Architecture Guide",
        description: "Understanding the AWS-native foundation architecture",
        href: "/docs/architecture",
      },
      {
        title: "Key Concepts",
        description: "Iceberg tables, catalogs, and namespaces",
        href: "/docs/concepts",
      },
    ]
  },
  {
    title: "Data Engineering",
    description: "Guides for data engineers",
    icon: Database,
    docs: [
      {
        title: "SQL Lab Guide",
        description: "Interactive query interface and SQL workflows",
        href: "/help/sql-lab",
      },
      {
        title: "Data Catalog",
        description: "Browse and manage Iceberg tables",
        href: "/help/catalog",
      },
      {
        title: "Connectors Setup",
        description: "Connect to databases and data sources",
        href: "/help/connectors",
      },
      {
        title: "Pipeline Development",
        description: "Build and orchestrate data pipelines with Airflow",
        href: "/docs/pipelines",
      },
    ]
  },
  {
    title: "Query & Analytics",
    description: "Running queries and analyzing data",
    icon: Code2,
    docs: [
      {
        title: "Trino SQL Reference",
        description: "SQL syntax and functions for OLAP queries",
        href: "/docs/trino-sql",
      },
      {
        title: "RisingWave Streaming",
        description: "Real-time SQL on streaming data",
        href: "/docs/streaming",
      },
      {
        title: "DuckDB in Notebooks",
        description: "Fast analytics in JupyterLab",
        href: "/docs/duckdb",
      },
      {
        title: "Query Optimization",
        description: "Performance tuning and best practices",
        href: "/docs/optimization",
      },
    ]
  },
  {
    title: "Integration & APIs",
    description: "Connect external tools and services",
    icon: Plug,
    docs: [
      {
        title: "REST API Reference",
        description: "Complete API documentation for DataPond services",
        href: "/docs/api",
      },
      {
        title: "Iceberg REST Catalog",
        description: "Connect Spark/Trino to Polaris catalog",
        href: "/docs/polaris",
      },
      {
        title: "Object Storage (AWS S3)",
        description: "Native S3 via the node instance profile / IRSA",
        href: "/docs/storage",
      },
      {
        title: "Python SDK",
        description: "Programmatic access to DataPond",
        href: "/docs/python-sdk",
        badge: "Beta"
      },
    ]
  },
  {
    title: "Operations",
    description: "Deployment, monitoring, and maintenance",
    icon: Settings,
    docs: [
      {
        title: "Installation Guide",
        description: "Deploy DataPond on Kubernetes",
        href: "/docs/installation",
      },
      {
        title: "Configuration",
        description: "Helm values and environment variables",
        href: "/docs/configuration",
      },
      {
        title: "Monitoring & Observability",
        description: "Logs, metrics, and health checks",
        href: "/docs/monitoring",
      },
      {
        title: "Troubleshooting",
        description: "Common issues and solutions",
        href: "/docs/troubleshooting",
      },
    ]
  },
  {
    title: "Security & Governance",
    description: "Access control and compliance",
    icon: Shield,
    docs: [
      {
        title: "Authentication & SSO",
        description: "Configure OIDC and SAML integration",
        href: "/docs/authentication",
        badge: "Enterprise"
      },
      {
        title: "Role-Based Access Control",
        description: "Manage permissions at catalog and table level",
        href: "/docs/rbac",
      },
      {
        title: "Data Lineage",
        description: "Track data flow with OpenMetadata",
        href: "/docs/lineage",
      },
      {
        title: "Audit Logging",
        description: "Compliance and audit trail",
        href: "/docs/audit",
      },
    ]
  },
]

export default function DocsPage() {
  const [searchQuery, setSearchQuery] = useState("")

  // Filter docs based on search
  const filteredCategories = docCategories.map(category => ({
    ...category,
    docs: category.docs.filter(doc =>
      doc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      doc.description.toLowerCase().includes(searchQuery.toLowerCase())
    )
  })).filter(category => category.docs.length > 0)

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
            <BreadcrumbPage>Documentation</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Page Header */}
      <div className="space-y-4">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-4xl font-bold tracking-tight">Documentation</h1>
            <p className="text-lg text-muted-foreground mt-2">
              Everything you need to build with DataPond
            </p>
          </div>
          <Link href="/help">
            <Badge variant="outline" className="gap-1 px-3 py-1.5 cursor-pointer hover:bg-muted">
              <HelpCircle className="h-3 w-3" />
              Help & Guides
            </Badge>
          </Link>
        </div>

        {/* Search */}
        <div className="relative max-w-xl">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search documentation..."
            className="pl-9"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <Book className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm font-medium">Documentation Pages</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {docCategories.reduce((acc, cat) => acc + cat.docs.length, 0)}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm font-medium">Categories</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{docCategories.length}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm font-medium">Quick Links</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2 flex-wrap">
              <Link href="/help/sql-lab">
                <Badge variant="secondary" className="cursor-pointer hover:bg-secondary/80">
                  SQL Lab
                </Badge>
              </Link>
              <Link href="/help/catalog">
                <Badge variant="secondary" className="cursor-pointer hover:bg-secondary/80">
                  Catalog
                </Badge>
              </Link>
              <Link href="/help/connectors">
                <Badge variant="secondary" className="cursor-pointer hover:bg-secondary/80">
                  Connectors
                </Badge>
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Documentation Categories */}
      <div className="space-y-6">
        {filteredCategories.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center">
              <p className="text-muted-foreground">
                No documentation found for "{searchQuery}"
              </p>
            </CardContent>
          </Card>
        ) : (
          filteredCategories.map((category, idx) => {
            const Icon = category.icon
            return (
              <div key={idx} className="space-y-3">
                <div className="flex items-center gap-2">
                  <Icon className="h-5 w-5 text-primary" />
                  <h2 className="text-2xl font-bold">{category.title}</h2>
                </div>
                <p className="text-muted-foreground">{category.description}</p>

                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {category.docs.map((doc, docIdx) => (
                    <Link key={docIdx} href={doc.href}>
                      <Card className="h-full hover:shadow-md transition-shadow cursor-pointer">
                        <CardHeader>
                          <div className="flex items-start justify-between">
                            <CardTitle className="text-base">{doc.title}</CardTitle>
                            {doc.badge && (
                              <Badge variant="secondary" className="ml-2">
                                {doc.badge}
                              </Badge>
                            )}
                          </div>
                          <CardDescription className="text-sm">
                            {doc.description}
                          </CardDescription>
                        </CardHeader>
                      </Card>
                    </Link>
                  ))}
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Footer CTA */}
      <Card className="bg-muted/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            Can't find what you're looking for?
          </CardTitle>
          <CardDescription>
            Visit our comprehensive help center or reach out to support
          </CardDescription>
        </CardHeader>
        <CardContent className="flex gap-3">
          <Link href="/help">
            <Badge variant="outline" className="gap-1 px-3 py-2 cursor-pointer hover:bg-background">
              <HelpCircle className="h-4 w-4" />
              Help Center
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
