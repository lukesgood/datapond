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
import { HelpTabs } from "@/components/help/help-tabs"
import { useHelpLocale } from "@/components/help/locale"
import type { L } from "@/lib/help-locale"

type DocLink = {
  title: L
  description: L
  href: string
  badge?: "Shipped" | "Optional" | "Reference" | "Roadmap"
}

type DocCategory = {
  title: L
  description: L
  icon: LucideIcon
  docs: DocLink[]
}

const BADGE_LABEL: Record<NonNullable<DocLink["badge"]>, L> = {
  Shipped: { en: "Shipped", ko: "제공 중" },
  Optional: { en: "Optional", ko: "선택 사항" },
  Reference: { en: "Reference", ko: "참조" },
  Roadmap: { en: "Roadmap", ko: "로드맵" },
}

// Encode lifecycle status as color so readers can scan shipped vs. optional vs. roadmap at a glance.
const STATUS_STYLES: Record<NonNullable<DocLink["badge"]>, string> = {
  Shipped: "bg-[var(--dp-good)]/10 text-[var(--dp-good-text)] border-[var(--dp-good)]/25",
  Optional: "bg-[var(--dp-warn)]/10 text-[var(--dp-warn-text)] border-[var(--dp-warn)]/25",
  Reference: "bg-primary/10 text-primary border-primary/25",
  Roadmap: "bg-muted text-muted-foreground border-border",
}

const docCategories: DocCategory[] = [
  {
    title: { en: "Start Here", ko: "시작하기" },
    description: { en: "Understand the lakehouse and run the first path: connect, sync, query", ko: "레이크하우스를 이해하고 첫 경로(연결, 동기화, 조회)를 따라 해봅니다" },
    icon: Rocket,
    docs: [
      { title: { en: "Platform Overview", ko: "플랫폼 개요" }, description: { en: "A lightweight open lakehouse with a governed AI layer", ko: "거버넌스가 적용된 AI 계층을 갖춘 가벼운 오픈 레이크하우스" }, href: "/docs/overview", badge: "Shipped" },
      { title: { en: "Quick Start", ko: "빠른 시작" }, description: { en: "Connect a source, sync it, query it; Knowledge first on AI-only profiles", ko: "소스 연결, 동기화, 조회. AI 전용 프로파일은 Knowledge부터" }, href: "/docs/quickstart" },
      { title: { en: "Core Workflow", ko: "핵심 워크플로" }, description: { en: "Connect → Organize → Query → Govern → Add AI", ko: "Connect → Organize → Query → Govern → Add AI" }, href: "/docs/core-workflow" },
      { title: { en: "Architecture", ko: "아키텍처" }, description: { en: "S3, Iceberg, catalogs, Trino, and the application layer", ko: "S3, Iceberg, 카탈로그, Trino, 애플리케이션 계층" }, href: "/docs/architecture" },
    ],
  },
  {
    title: { en: "Deployment Profiles", ko: "배포 프로파일" },
    description: { en: "Choose an operating model without confusing profile intent with installed services", ko: "프로파일의 의도와 실제 설치된 서비스를 혼동하지 않고 운영 모델을 고릅니다" },
    icon: Boxes,
    docs: [
      { title: { en: "Profile Matrix", ko: "프로파일 비교" }, description: { en: "Compare lakehouse profiles and AI-only Core profiles", ko: "레이크하우스 프로파일과 AI 전용 Core 프로파일 비교" }, href: "/docs/profiles", badge: "Shipped" },
      { title: { en: "Portable Core · AWS", ko: "Portable Core · AWS" }, description: { en: "Lean AI starter with S3 and Bedrock, no catalog or engine", ko: "S3와 Bedrock을 쓰는 가벼운 AI 스타터 (카탈로그·엔진 없음)" }, href: "/docs/portable-core" },
      { title: { en: "AWS Single-Node Reference", ko: "AWS Single-Node Reference" }, description: { en: "EC2/K3s with Aurora, S3, Glue, Bedrock, Trino and Polaris", ko: "EC2/K3s에 Aurora, S3, Glue, Bedrock, Trino, Polaris" }, href: "/docs/aws-reference", badge: "Reference" },
      { title: { en: "Sovereign OSS Extended", ko: "Sovereign OSS Extended" }, description: { en: "Self-hosted MinIO, Polaris and Trino plus selected add-ons", ko: "자체 호스팅 MinIO, Polaris, Trino와 선택형 애드온" }, href: "/docs/sovereign", badge: "Optional" },
    ],
  },
  {
    title: { en: "Portability & Exit", ko: "이식성과 이전" },
    description: { en: "Keep data, catalogs, engine and models replaceable", ko: "데이터, 카탈로그, 엔진, 모델을 언제든 교체할 수 있게 유지합니다" },
    icon: Plug,
    docs: [
      { title: { en: "Open Contracts", ko: "개방형 계약" }, description: { en: "S3 API, Iceberg, Glue/REST catalogs, Trino, PostgreSQL, LiteLLM", ko: "S3 API, Iceberg, Glue/REST 카탈로그, Trino, PostgreSQL, LiteLLM" }, href: "/docs/open-contracts", badge: "Shipped" },
      { title: { en: "Exit Strategy", ko: "이전 전략" }, description: { en: "What moves today, and which automation is still roadmap", ko: "지금 옮길 수 있는 것과 아직 로드맵인 자동화" }, href: "/docs/exit-strategy" },
      { title: { en: "Optional Add-ons", ko: "선택형 애드온" }, description: { en: "Polaris, RisingWave, OpenMetadata, Airflow, Spark, Jupyter, MLflow", ko: "Polaris, RisingWave, OpenMetadata, Airflow, Spark, Jupyter, MLflow" }, href: "/docs/addons", badge: "Optional" },
      { title: { en: "Backup & Restore", ko: "백업과 복구" }, description: { en: "Protect the lake, PostgreSQL, catalog metadata and encryption keys", ko: "레이크, PostgreSQL, 카탈로그 메타데이터, 암호화 키 보호" }, href: "/docs/backup-restore" },
    ],
  },
  {
    title: { en: "Build & Govern", ko: "구축과 거버넌스" },
    description: { en: "The lakehouse workspace first, then the AI layer on the same data", ko: "레이크하우스 작업 공간을 먼저, 그 위에 같은 데이터를 쓰는 AI 계층" },
    icon: Database,
    docs: [
      { title: { en: "Sources", ko: "Sources" }, description: { en: "Trino source catalogs, sync modes, target catalog, PII masking", ko: "Trino 소스 카탈로그, 동기화 방식, 대상 카탈로그, PII 마스킹" }, href: "/docs/sources", badge: "Optional" },
      { title: { en: "Catalog, Analytics & Metrics", ko: "Catalog, Analytics, Metrics" }, description: { en: "Browse tables, run Trino SQL, query approved metrics", ko: "테이블 탐색, Trino SQL 실행, 승인된 지표 조회" }, href: "/docs/catalog-query", badge: "Optional" },
      { title: { en: "Two catalogs and the catalog export", ko: "두 개의 카탈로그와 카탈로그 내보내기" }, description: { en: "Owner and mirror, export plan and apply, catalog:write", ko: "소유자와 미러, 내보내기 계획·적용, catalog:write" }, href: "/docs/catalogs", badge: "Shipped" },
      { title: { en: "Governance", ko: "거버넌스" }, description: { en: "Catalog grants, row and column policy, Korean PII masking, audit", ko: "카탈로그 권한, 행·컬럼 정책, 한국형 PII 마스킹, 감사" }, href: "/docs/governance", badge: "Shipped" },
      { title: { en: "Knowledge & RAG", ko: "Knowledge & RAG" }, description: { en: "Collections, ingestion, retrieval, reranking and citations", ko: "컬렉션, 수집, 검색, 재순위화, 인용" }, href: "/docs/knowledge-rag", badge: "Shipped" },
      { title: { en: "AI Gateway", ko: "AI Gateway" }, description: { en: "Model routing, MCP, service-account keys, per-caller spend", ko: "모델 라우팅, MCP, 서비스 계정 키, 호출자별 비용" }, href: "/docs/ai-gateway", badge: "Shipped" },
    ],
  },
  {
    title: { en: "Operate", ko: "운영" },
    description: { en: "Configure, secure, observe, and troubleshoot a deployment", ko: "배포를 설정하고, 보호하고, 관찰하고, 문제를 해결합니다" },
    icon: Settings,
    docs: [
      { title: { en: "Configuration", ko: "설정" }, description: { en: "Helm values, data catalogs, Trino workers, feature flags", ko: "Helm 값, 데이터 카탈로그, Trino 워커, 기능 플래그" }, href: "/docs/configuration" },
      { title: { en: "Monitoring", ko: "모니터링" }, description: { en: "Workload health, query log, tool-call audit and spend", ko: "워크로드 상태, 쿼리 로그, 도구 호출 감사, 비용" }, href: "/docs/monitoring" },
      { title: { en: "Authentication", ko: "인증" }, description: { en: "Local JWT, passkeys, LDAP, Enterprise OIDC, service-account keys", ko: "로컬 JWT, 패스키, LDAP, Enterprise OIDC, 서비스 계정 키" }, href: "/docs/authentication" },
      { title: { en: "Troubleshooting", ko: "문제 해결" }, description: { en: "Names, mirrors, engine restarts, budgets and adapters", ko: "테이블 이름, 미러, 엔진 재시작, 예산, 어댑터 점검" }, href: "/docs/troubleshooting" },
      { title: { en: "REST API", ko: "REST API" }, description: { en: "OpenAPI, read-only MCP, and capability discovery", ko: "OpenAPI, 읽기 전용 MCP, capability 조회" }, href: "/docs/api" },
    ],
  },
]

// The Documentation half of the Help workspace — the concept/profile/operations
// index. Rendered in the ?tab=docs panel; article deep links (/docs/[slug]) are
// preserved and reached from the cards below.
export function DocsIndex() {
  const { t } = useHelpLocale()
  const [searchQuery, setSearchQuery] = useState("")
  const needle = searchQuery.trim().toLowerCase()
  const filteredCategories = docCategories
    .map((category) => ({
      ...category,
      docs: category.docs.filter((doc) =>
        !needle || `${t(doc.title)} ${t(doc.description)} ${doc.badge ? t(BADGE_LABEL[doc.badge]) : ""}`.toLowerCase().includes(needle),
      ),
    }))
    .filter((category) => category.docs.length > 0)

  const totalDocs = docCategories.reduce((sum, category) => sum + category.docs.length, 0)
  const shownDocs = filteredCategories.reduce((sum, category) => sum + category.docs.length, 0)

  return (
    <div className="flex flex-col">
      {/* Workspace top bar — same height as the Guides hub bar so switching tabs
          keeps the chrome steady. */}
      <div className="flex items-center gap-1.5 border-b px-3 h-11 shrink-0 bg-background">
        <HelpTabs active="docs" />
      </div>

      <div className="flex-1 space-y-6 p-8 pt-6">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem><BreadcrumbLink href="/dashboard">{t({ en: "Home", ko: "홈" })}</BreadcrumbLink></BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem><BreadcrumbPage>{t({ en: "Documentation", ko: "문서" })}</BreadcrumbPage></BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-primary">{t({ en: "Product truth", ko: "제품 기준 문서" })}</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">{t({ en: "Documentation", ko: "문서" })}</h1>
          <p className="mt-2 max-w-2xl text-muted-foreground">
            {t({
              en: "A lightweight open lakehouse on S3 and Iceberg with a governed AI layer. See what is shipped, what is optional, and what is still roadmap.",
              ko: "S3와 Iceberg 위의 가벼운 오픈 레이크하우스와 거버넌스가 적용된 AI 계층입니다. 제공 중인 기능, 선택 기능, 로드맵을 구분해서 안내합니다.",
            })}
          </p>
        </div>

        <Card className="border-primary/20 bg-primary/5">
          <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-5 w-5 text-primary" />
              <div>
                <p className="text-sm font-semibold">{t({ en: "Open standards, explicit adapters", ko: "개방형 표준, 명시적인 어댑터" })}</p>
                <p className="text-xs text-muted-foreground">
                  {t({
                    en: "Disabled components are not silently replaced by cloud services. The active profile and capabilities are shown in the app shell.",
                    ko: "꺼 둔 구성 요소를 클라우드 서비스가 몰래 대체하지 않습니다. 활성 프로파일과 capability는 앱 상단에 표시됩니다.",
                  })}
                </p>
              </div>
            </div>
            <Link className="text-sm font-medium text-primary hover:underline" href="/docs/profiles">{t({ en: "Choose a profile", ko: "프로파일 선택" })} →</Link>
          </CardContent>
        </Card>

        <div className="space-y-1.5">
          <div className="relative max-w-xl">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder={t({ en: "Search concepts, profiles, or capabilities…", ko: "개념, 프로파일, 기능을 검색하세요…" })}
              className="pl-9"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              aria-label={t({ en: "Search documentation", ko: "문서 검색" })}
            />
          </div>
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {needle
              ? t({ en: `${shownDocs} of ${totalDocs} article${totalDocs === 1 ? "" : "s"} match`, ko: `${totalDocs}개 중 ${shownDocs}개 문서가 일치합니다` })
              : t({ en: `${totalDocs} articles across ${docCategories.length} sections`, ko: `${docCategories.length}개 섹션, ${totalDocs}개 문서` })}
          </p>
        </div>

        <div className="space-y-7">
          {filteredCategories.length === 0 ? (
            <Card><CardContent className="py-12 text-center text-muted-foreground">{t({ en: "No documentation found for", ko: "검색 결과가 없습니다:" })} “{searchQuery}”</CardContent></Card>
          ) : filteredCategories.map((category) => {
            const Icon = category.icon
            return (
              <section key={category.title.en} className="space-y-3">
                <div className="flex items-center gap-2">
                  <Icon className="h-5 w-5 text-primary" />
                  <h2 className="text-xl font-bold">{t(category.title)}</h2>
                </div>
                <p className="text-sm text-muted-foreground">{t(category.description)}</p>
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {category.docs.map((doc) => (
                    <Link key={doc.href} href={doc.href}>
                      <Card className="group h-full transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
                        <CardHeader>
                          <div className="flex items-start justify-between gap-2">
                            <CardTitle className="flex items-center gap-1.5 text-base">
                              {t(doc.title)}
                              {/* Arrow morphs in on hover to signal the card is navigable */}
                              <ArrowRight className="h-4 w-4 shrink-0 -translate-x-1 text-muted-foreground opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100" />
                            </CardTitle>
                            {doc.badge && (
                              <Badge variant="outline" className={`shrink-0 text-2xs ${STATUS_STYLES[doc.badge]}`}>{t(BADGE_LABEL[doc.badge])}</Badge>
                            )}
                          </div>
                          <CardDescription>{t(doc.description)}</CardDescription>
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
            <CardTitle className="flex items-center gap-2"><FileText className="h-5 w-5" />{t({ en: "Need implementation detail?", ko: "구현 세부 내용이 필요하신가요?" })}</CardTitle>
            <CardDescription>{t({ en: "The repository docs are the canonical operator reference; historical plans are not current product truth.", ko: "저장소의 docs가 운영자용 기준 문서입니다. 과거 계획 문서는 현재 제품 기준이 아닙니다." })}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            <Link className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline" href="/help">
              <BookOpen className="h-4 w-4" /> {t({ en: "Open guides", ko: "가이드 열기" })}
            </Link>
            <a className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline" href="mailto:support@datapond.ai">
              <ExternalLink className="h-4 w-4" /> {t({ en: "Contact support", ko: "지원 문의" })}
            </a>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
