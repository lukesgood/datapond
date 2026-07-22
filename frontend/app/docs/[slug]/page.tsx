"use client"

import { useParams } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, ArrowRight, BookOpen, ExternalLink } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useCapabilities } from "@/lib/capabilities"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"

type Status = "Shipped" | "Optional" | "Reference" | "Roadmap"
type Related = { label: string; href: string; capability?: string }
type Doc = { title: string; status: Status; summary: string; points: string[]; related?: Related[] }

const ARTICLES: Record<string, Doc> = {
  overview: {
    title: "Platform Overview",
    status: "Shipped",
    summary: "DataPond is a Portable AI Data Foundation for governed RAG and agent applications. The application core stays stable while storage, vector, model, catalog, and query providers are selected by deployment profile.",
    points: [
      "Shipped core: collections, ingestion, chunk replacement, embeddings, pgvector retrieval, optional reranking, cited RAG answers, PII controls, access controls, and spend attribution.",
      "Portable contracts: S3 API, PostgreSQL + pgvector, LiteLLM/OpenAI-compatible model access, REST APIs, OIDC, Helm, and Kubernetes.",
      "Trino, Polaris, RisingWave, OpenMetadata, Airflow, Jupyter, and MLflow are optional add-ons—not required core services.",
    ],
    related: [{ label: "Core workflow", href: "/docs/core-workflow" }, { label: "Profile matrix", href: "/docs/profiles" }],
  },
  quickstart: {
    title: "Quick Start",
    status: "Shipped",
    summary: "Start with the workflow that exists in every profile: create a Knowledge collection, ingest content, test retrieval, ask a cited question, and inspect governance and spend.",
    points: [
      "Open Knowledge, create a collection, and ingest text or configured S3 objects.",
      "Run semantic search before RAG to verify chunk quality and retrieval relevance.",
      "Ask a question, check citations, then review collection access, PII behavior, and AI usage.",
      "Sources, Catalog, SQL Lab, and other add-ons appear only when their backing capability is explicitly enabled.",
    ],
    related: [{ label: "Open Knowledge", href: "/knowledge" }, { label: "Open Governance", href: "/governance" }],
  },
  "core-workflow": {
    title: "Core Workflow",
    status: "Shipped",
    summary: "The product journey is Connect → Organize → Ground → Serve → Govern. Portable Core covers the full AI path even when analytics add-ons are absent.",
    points: [
      "Connect: ingest files, text, S3 objects, or—when enabled—database and table sources.",
      "Organize: use Knowledge collections by default; add an Iceberg catalog when table workflows are required.",
      "Ground: chunk, mask PII, embed, replace stale source groups, retrieve, rerank, and cite.",
      "Serve and govern: route models through LiteLLM and apply collection access, audit, and spend controls.",
    ],
    related: [{ label: "Knowledge", href: "/knowledge" }, { label: "AI Gateway", href: "/ai" }],
  },
  architecture: {
    title: "Architecture",
    status: "Shipped",
    summary: "The architecture separates the Apache-2.0 application core from infrastructure adapters and optional OSS add-ons.",
    points: [
      "Core workloads: FastAPI backend, Next.js frontend, PostgreSQL + pgvector or external Aurora, LiteLLM, and Valkey.",
      "Adapter boundaries: S3/native or S3-compatible object access; PostgreSQL-compatible vector storage; model providers through LiteLLM; optional Glue/Athena or Polaris/Trino data plane.",
      "A disabled add-on is absent. Helm does not automatically provision an AWS service to replace it.",
      "The current Terraform reference creates EC2/K3s, Aurora, S3, ECR, IAM, Route53, Secrets Manager, and monitoring resources—not EKS.",
    ],
    related: [{ label: "Open contracts", href: "/docs/open-contracts" }, { label: "Active services", href: "/services" }],
  },
  profiles: {
    title: "Deployment Profile Matrix",
    status: "Shipped",
    summary: "Profiles describe operating intent and enabled adapters. Runtime capability flags—not profile names—control which product modules appear.",
    points: [
      "Portable Core · AWS (`values-foundation.yaml`): lean starter with native S3, Bedrock, in-cluster pgvector, LiteLLM, and Valkey; no catalog/query service is provisioned.",
      "AWS Single-Node Reference (`values-prod-single.yaml`): EC2/K3s with Aurora, S3, Glue/Athena, Bedrock, ECR, TLS, and CloudWatch metrics; intentionally non-HA at the application-node layer.",
      "AWS Hybrid Extended (`values-aws.yaml`): compatibility overlay for an existing Kubernetes cluster; it inherits heavy OSS defaults and is not an EKS installer.",
      "Sovereign OSS Extended (`values-onprem.yaml`): self-hosted core plus selected OSS services; greater control with greater operational responsibility.",
    ],
    related: [{ label: "Portable Core", href: "/docs/portable-core" }, { label: "AWS reference", href: "/docs/aws-reference" }, { label: "Sovereign", href: "/docs/sovereign" }],
  },
  "portable-core": {
    title: "Portable Core · AWS Starter",
    status: "Shipped",
    summary: "`values-foundation.yaml` is the smallest maintained product profile. Its historical filename remains for compatibility, while its product role is Portable Core on AWS.",
    points: [
      "Runs backend, frontend, PostgreSQL + pgvector, LiteLLM, and Valkey; uses external native S3 and Bedrock.",
      "Catalog, SQL, transforms, streaming, notebooks, experiments, and external lineage are disabled and hidden.",
      "Athena, Glue, EMR, MWAA, DataZone, and SageMaker are not automatically created as replacements.",
    ],
    related: [{ label: "Knowledge", href: "/knowledge" }, { label: "Profile matrix", href: "/docs/profiles" }],
  },
  "aws-reference": {
    title: "AWS Single-Node Reference",
    status: "Reference",
    summary: "The current AWS infrastructure reference is a single EC2/K3s application node connected to managed Aurora, S3, Glue/Athena, and Bedrock services.",
    points: [
      "Terraform also creates ECR, IAM/instance profile, Route53, Secrets Manager, CloudWatch/SNS, and start/stop scheduling.",
      "The profile is production-oriented but not application-node HA; recovery procedures are part of the operating model.",
      "EKS, EMR Serverless, S3 Tables, Lake Formation, AOSS, DataZone, CDK, and Marketplace packaging remain roadmap until implemented and accepted live.",
    ],
    related: [{ label: "System", href: "/system" }, { label: "Backup & restore", href: "/docs/backup-restore" }],
  },
  sovereign: {
    title: "Sovereign OSS Extended",
    status: "Optional",
    summary: "Use the self-hosted profile when infrastructure control, local models, or disconnected operation matters more than the smallest footprint.",
    points: [
      "The profile can run S3-compatible storage, PostgreSQL/pgvector, LiteLLM, Ollama, and optional data services inside your Kubernetes environment.",
      "Disable every add-on that is not required; open source does not automatically mean low operations.",
      "Review THIRD_PARTY_NOTICES.md because some optional images use AGPL or source-available licenses.",
    ],
    related: [{ label: "Optional add-ons", href: "/docs/addons" }, { label: "Exit strategy", href: "/docs/exit-strategy" }],
  },
  "open-contracts": {
    title: "Open Contracts",
    status: "Shipped",
    summary: "Portability comes from stable data formats and protocols, not from running every open-source service at once.",
    points: [
      "Objects: S3 API; metadata and vectors: PostgreSQL + pgvector; tables when enabled: Parquet + Apache Iceberg.",
      "Models: logical model names routed through LiteLLM; identity: JWT, LDAP, passkeys, and optional OIDC; deployment: containers, Helm, and Kubernetes.",
      "Keep provider IDs, ARNs, bucket paths, model IDs, and credentials in adapter configuration rather than product-domain records whenever possible.",
    ],
    related: [{ label: "Architecture", href: "/docs/architecture" }, { label: "Exit strategy", href: "/docs/exit-strategy" }],
  },
  "exit-strategy": {
    title: "Exit Strategy",
    status: "Reference",
    summary: "The underlying objects, PostgreSQL data, vectors, and model configuration are portable today. A single automated export/import command and recurring cross-provider exit drill are planned, not yet shipped.",
    points: [
      "Current path: copy S3 objects, use PostgreSQL backup/restore, preserve encryption keys, rebind provider configuration, and re-embed if the embedding model or dimension changes.",
      "Iceberg table moves may require warehouse-path rewriting or table re-registration because metadata contains object URIs.",
      "Planned acceptance: Glue → Iceberg REST registration, Aurora → PostgreSQL restore, Bedrock → local/provider model switch, and deterministic RAG evaluation.",
    ],
    related: [{ label: "Backup & restore", href: "/docs/backup-restore" }, { label: "Open contracts", href: "/docs/open-contracts" }],
  },
  addons: {
    title: "Optional OSS Add-ons",
    status: "Optional",
    summary: "Add-ons extend the data plane without becoming dependencies of the RAG core.",
    points: [
      "Polaris + Trino: portable Iceberg catalog and distributed SQL; RisingWave: streaming SQL/CDC; Airflow + Spark: orchestration and batch.",
      "OpenMetadata: external catalog and lineage UI; Jupyter + DuckDB: exploration; MLflow: experiments and model registry.",
      "Enable add-ons per use case and resource budget. Their navigation remains hidden until the corresponding capability is active.",
    ],
    related: [{ label: "Services", href: "/services" }, { label: "Profile matrix", href: "/docs/profiles" }],
  },
  "backup-restore": {
    title: "Backup & Restore",
    status: "Reference",
    summary: "A recoverable deployment protects object data, PostgreSQL/pgvector state, and the encryption keys needed to decrypt stored credentials.",
    points: [
      "AWS reference: Aurora PITR/snapshots, S3 versioning, and Secrets Manager for durable critical-secret recovery.",
      "Restore `ENCRYPTION_KEY` before the backend connects to restored PostgreSQL data; a new key cannot decrypt existing credentials.",
      "Test restore procedures regularly and record observed RPO/RTO. The single-node AWS reference relies on fast restore rather than application-node HA.",
    ],
  },
  "knowledge-rag": {
    title: "Knowledge & RAG",
    status: "Shipped",
    summary: "Knowledge is the primary workspace in every profile and does not require the optional lakehouse stack.",
    points: [
      "Create collections; ingest text, configured S3 objects, or catalog sources when available; replace chunks by source group.",
      "Search with pgvector HNSW, optionally rerank through LiteLLM, and fall back to vector order when reranking fails.",
      "Generate answers with citations and apply PII masking during ingestion and retrieval.",
    ],
    related: [{ label: "Open Knowledge", href: "/knowledge" }, { label: "Governance", href: "/governance" }],
  },
  sources: {
    title: "Sources",
    status: "Optional",
    summary: "Database/table connector workflows are shown when a compatible catalog adapter is active. Direct text and S3 Knowledge ingestion remain part of core.",
    points: [
      "Connector sync can write Iceberg through Glue or Polaris-backed paths and mark linked Knowledge collections stale for re-embedding.",
      "Scheduling and transformation features depend on their own capabilities; a connector being visible does not imply Airflow is installed.",
    ],
    related: [{ label: "Sources", href: "/connectors", capability: "connectors" }, { label: "Knowledge", href: "/knowledge" }],
  },
  "catalog-query": {
    title: "Catalog & Query",
    status: "Optional",
    summary: "Catalog and SQL are adapter-backed modules: Glue + Athena in the AWS single-node reference or Polaris + Trino in an OSS extended profile.",
    points: [
      "The UI reads runtime query-engine and catalog hints; it does not assume AWS services from the product name.",
      "When no supported adapter is enabled, Catalog, Sources, SQL Lab, and Dashboards are hidden and direct routes explain the missing capability.",
      "Catalog → Send to Knowledge bridges selected table content into the governed RAG workflow.",
    ],
    related: [
      { label: "Catalog", href: "/catalog", capability: "catalog" },
      { label: "SQL Lab", href: "/query", capability: "query" },
    ],
  },
  "ai-gateway": {
    title: "AI Gateway",
    status: "Shipped",
    summary: "LiteLLM provides one model boundary for Bedrock and configurable cloud or local providers.",
    points: [
      "Use logical model names for embedding, chat, and reranking so provider-specific IDs stay in adapter configuration.",
      "User identity and application metadata are attached to calls for spend attribution and usage reporting.",
      "Provider management, virtual keys, and global spend administration should be restricted to administrators in production deployments.",
    ],
    related: [{ label: "AI Gateway", href: "/ai" }, { label: "Settings", href: "/settings" }],
  },
  governance: {
    title: "Governance",
    status: "Shipped",
    summary: "Core governance covers collection ownership/sharing, PII controls, audit events, and AI spend. Table RLS and external lineage are profile-dependent extensions.",
    points: [
      "Knowledge collections use owner, administrator, and explicit sharing checks at the application layer.",
      "PII masking protects ingestion and retrieval; policy-backed table filtering is available when the RLS engine is configured.",
      "OpenMetadata lineage is optional and best-effort; it is not silently replaced by DataZone when disabled.",
    ],
    related: [{ label: "Governance", href: "/governance" }, { label: "AI Gateway", href: "/ai" }],
  },
  configuration: {
    title: "Configuration",
    status: "Shipped",
    summary: "Helm component flags determine capabilities; product profile metadata only explains the rendered operating model.",
    points: [
      "Use profile files as overlays and keep account-specific domains, bucket paths, database endpoints, image repositories, and secrets outside version control.",
      "The app shell displays profile ID, maturity, topology, and active adapter hints from `/api/capabilities`.",
      "Changing a profile label never enables a feature; the underlying component/adapter settings remain authoritative.",
    ],
    related: [{ label: "Settings", href: "/settings" }, { label: "Profile matrix", href: "/docs/profiles" }],
  },
  monitoring: {
    title: "Monitoring & Observability",
    status: "Shipped",
    summary: "Use Services and System for runtime health, and AI Gateway/Governance for model usage and spend.",
    points: [
      "Workload health is separate from capability status: enabled means configured, not necessarily healthy.",
      "The AWS single-node reference can emit CloudWatch metrics; OSS observability stacks are not required by Portable Core.",
    ],
    related: [{ label: "Services", href: "/services" }, { label: "System", href: "/system" }],
  },
  authentication: {
    title: "Authentication",
    status: "Shipped",
    summary: "Community supports local JWT accounts, passkeys/WebAuthn, and LDAP. Enterprise adds OIDC SSO.",
    points: [
      "The local administrator remains available for recovery; secure origins are required for passkeys.",
      "OIDC uses Authorization Code + PKCE and JWKS verification in the Enterprise backend. SAML remains roadmap.",
    ],
    related: [{ label: "Settings", href: "/settings" }],
  },
  troubleshooting: {
    title: "Troubleshooting",
    status: "Shipped",
    summary: "Start with profile and capability identity, then check workload health and the active adapter boundary.",
    points: [
      "If a module is absent, compare the active profile and capability flag before debugging a service that is intentionally not installed.",
      "For RAG failures, check PostgreSQL/pgvector, object access, LiteLLM, model access, egress policy, and embedding dimensions.",
      "For catalog/query failures, verify the active Glue/Athena or Polaris/Trino adapter and its credentials independently.",
    ],
    related: [{ label: "Services", href: "/services" }, { label: "Profile matrix", href: "/docs/profiles" }],
  },
  api: {
    title: "REST API",
    status: "Shipped",
    summary: "The FastAPI backend exposes authentication, Knowledge/RAG, AI gateway, governance, storage, and optional data-plane APIs.",
    points: [
      "Interactive OpenAPI documentation is served at `/api/docs`.",
      "Capability discovery is available at `/api/capabilities`; it reports configuration, not live health.",
    ],
    related: [{ label: "Open Swagger", href: "/api/docs" }],
  },
}

const DOCS: Record<string, Doc> = {
  ...ARTICLES,
  concepts: ARTICLES.overview,
  installation: ARTICLES.profiles,
  "trino-sql": ARTICLES["catalog-query"],
  polaris: ARTICLES["catalog-query"],
  duckdb: ARTICLES.addons,
  pipelines: ARTICLES.addons,
  streaming: ARTICLES.addons,
  storage: ARTICLES["open-contracts"],
  optimization: ARTICLES["catalog-query"],
  lineage: ARTICLES.governance,
  rbac: ARTICLES.governance,
  audit: ARTICLES.governance,
  "python-sdk": ARTICLES.api,
}

// Canonical reading order, mirroring the section grouping on the docs index.
const ORDER = [
  "overview", "quickstart", "core-workflow", "architecture",
  "profiles", "portable-core", "aws-reference", "sovereign",
  "open-contracts", "exit-strategy", "addons", "backup-restore",
  "knowledge-rag", "sources", "catalog-query", "ai-gateway", "governance",
  "configuration", "monitoring", "authentication", "troubleshooting", "api",
]

// Match lifecycle status to color, consistent with the docs index badges.
const STATUS_STYLES: Record<Status, string> = {
  Shipped: "bg-[var(--dp-good)]/10 text-[var(--dp-good)] border-[var(--dp-good)]/25",
  Optional: "bg-[var(--dp-warn)]/10 text-[var(--dp-warn)] border-[var(--dp-warn)]/25",
  Reference: "bg-primary/10 text-primary border-primary/25",
  Roadmap: "bg-muted text-muted-foreground border-border",
}

function humanize(slug: string) {
  return slug.replace(/-/g, " ").replace(/\b\w/g, (character) => character.toUpperCase())
}

export default function DocArticlePage() {
  const params = useParams()
  const slug = String(params?.slug || "")
  const doc = DOCS[slug]
  const caps = useCapabilities()
  const related = doc?.related?.filter((item) => !item.capability || caps[item.capability] === true)

  // Resolve the canonical slug (aliases share a Doc object) to place prev/next in the reading order.
  const canonicalSlug = ORDER.includes(slug)
    ? slug
    : Object.keys(ARTICLES).find((key) => ARTICLES[key] === doc)
  const orderIndex = canonicalSlug ? ORDER.indexOf(canonicalSlug) : -1
  const prevSlug = orderIndex > 0 ? ORDER[orderIndex - 1] : undefined
  const nextSlug = orderIndex >= 0 && orderIndex < ORDER.length - 1 ? ORDER[orderIndex + 1] : undefined

  return (
    <div className="flex-1 space-y-5 p-8 pt-6 max-w-3xl">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/docs">Docs</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>{doc?.title || humanize(slug)}</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {doc ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <BookOpen className="h-5 w-5 text-primary" />
            <h1 className="text-2xl font-semibold">{doc.title}</h1>
            <Badge variant="outline" className={STATUS_STYLES[doc.status]}>{doc.status}</Badge>
          </div>
          <Card>
            <CardContent className="space-y-4 py-5">
              {/* Lead paragraph reads at body weight/foreground; bullets carry the detail. */}
              <p className="text-[15px] leading-relaxed text-foreground">{doc.summary}</p>
              <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed text-muted-foreground marker:text-primary/60">
                {doc.points.map((point) => <li key={point}>{point}</li>)}
              </ul>
              {related && related.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-2">
                  {related.map((item) => (
                    <Link key={item.href} href={item.href} className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-muted">
                      {item.label}<ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  ))}
                </div>
              )}
              <p className="flex items-center gap-1 pt-2 text-[11px] text-muted-foreground">
                <ExternalLink className="h-3 w-3" /> Canonical operator guides live in the repository <span className="font-mono">docs/</span> directory.
              </p>
            </CardContent>
          </Card>

          {(prevSlug || nextSlug) && (
            <nav aria-label="Article navigation" className="flex flex-col gap-2 sm:flex-row sm:gap-3">
              {prevSlug ? (
                <Link
                  href={`/docs/${prevSlug}`}
                  className="group flex flex-1 items-center gap-2 rounded-md border px-3 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-muted"
                >
                  <ArrowLeft className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:-translate-x-0.5" />
                  <span className="min-w-0">
                    <span className="block text-[11px] uppercase tracking-wide text-muted-foreground">Previous</span>
                    <span className="block truncate text-sm font-medium">{ARTICLES[prevSlug].title}</span>
                  </span>
                </Link>
              ) : <span className="hidden flex-1 sm:block" />}
              {nextSlug ? (
                <Link
                  href={`/docs/${nextSlug}`}
                  className="group flex flex-1 items-center justify-end gap-2 rounded-md border px-3 py-2.5 text-right transition-colors hover:border-primary/40 hover:bg-muted"
                >
                  <span className="min-w-0">
                    <span className="block text-[11px] uppercase tracking-wide text-muted-foreground">Next</span>
                    <span className="block truncate text-sm font-medium">{ARTICLES[nextSlug].title}</span>
                  </span>
                  <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </Link>
              ) : <span className="hidden flex-1 sm:block" />}
            </nav>
          )}
        </>
      ) : (
        <Card>
          <CardContent className="space-y-3 py-8 text-center">
            <p className="text-sm text-muted-foreground">The article <span className="font-mono">{slug}</span> is not part of the active documentation set.</p>
            <Link href="/docs" className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-muted">
              <ArrowLeft className="h-3.5 w-3.5" /> Documentation home
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
