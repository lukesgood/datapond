"use client"

import Link from "next/link"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import type { LucideIcon } from "lucide-react"
import { ArrowDownToLine, ArrowRight, BookOpen, Code2, Database, HardDrive, Layers, Plug, Settings2, ShieldCheck, Sigma, Sparkles } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { PageHeader } from "@/components/ui/page-header"
import { Badge } from "@/components/ui/badge"
import { useCapabilities } from "@/lib/capabilities"
import { getProductProfile } from "@/lib/product-profile"
import { HelpTabs } from "@/components/help/help-tabs"
import { DocsIndex } from "@/components/docs/docs-index"
import { useHelpLocale } from "@/components/help/locale"
import type { L } from "@/lib/help-locale"

type Guide = {
  title: L
  description: L
  icon: LucideIcon
  href: string
  capability?: string
  topics: L[]
}

// Lakehouse first (Sources, Catalog, Analytics, Metrics, Governance), then the AI
// layer, then operations.
const guides: Guide[] = [
  {
    title: { en: "Sources", ko: "Sources (데이터 소스)" },
    description: {
      en: "Connect a database, S3 or an API, browse it in SQL, and sync it into Iceberg tables",
      ko: "데이터베이스, S3, API를 연결하고 SQL로 살펴본 뒤 Iceberg 테이블로 동기화합니다",
    },
    icon: ArrowDownToLine,
    href: "/help/connectors",
    topics: [
      { en: "Trino catalogs", ko: "Trino 카탈로그" },
      { en: "Sync modes", ko: "동기화 방식" },
      { en: "Target catalog", ko: "대상 카탈로그" },
      { en: "PII masking", ko: "PII 마스킹" },
      { en: "Sharing", ko: "공유" },
    ],
  },
  {
    title: { en: "Catalog", ko: "Catalog (카탈로그)" },
    description: {
      en: "Browse lake and source catalogs, inspect tables, export or mirror between catalogs",
      ko: "레이크와 소스 카탈로그의 테이블을 둘러보고, 카탈로그 간 내보내기와 미러를 다룹니다",
    },
    icon: Database,
    href: "/help/catalog",
    capability: "catalog",
    topics: [
      { en: "Namespaces", ko: "네임스페이스" },
      { en: "Preview", ko: "미리보기" },
      { en: "Export", ko: "내보내기" },
      { en: "Mirrors", ko: "미러" },
      { en: "Send to Knowledge", ko: "Knowledge로 보내기" },
    ],
  },
  {
    title: { en: "Analytics", ko: "Analytics (분석)" },
    description: {
      en: "Run Trino SQL across every catalog you may use, chart the results, save dashboards",
      ko: "접근 가능한 모든 카탈로그에 Trino SQL을 실행하고, 결과를 차트와 대시보드로 저장합니다",
    },
    icon: Code2,
    href: "/help/sql-lab",
    capability: "query",
    topics: [
      { en: "Editor", ko: "에디터" },
      { en: "Schema tree", ko: "스키마 트리" },
      { en: "History", ko: "기록" },
      { en: "Charts", ko: "차트" },
      { en: "Dashboards", ko: "대시보드" },
    ],
  },
  {
    title: { en: "Approved metrics", ko: "Metrics (승인된 지표)" },
    description: {
      en: "Define a number once, approve it, and let people and agents query it with a citation",
      ko: "지표를 한 번 정의해 승인하면 사람과 에이전트가 출처와 함께 같은 값을 조회합니다",
    },
    icon: Sigma,
    href: "/help/metrics",
    capability: "query",
    topics: [
      { en: "Definitions", ko: "정의" },
      { en: "Joins", ko: "조인" },
      { en: "Approval", ko: "승인" },
      { en: "metric_query", ko: "metric_query" },
      { en: "Citations", ko: "인용" },
    ],
  },
  {
    title: { en: "Governance", ko: "Governance (거버넌스)" },
    description: {
      en: "Catalog grants, row filters, column masks, Korean PII masking, and the audit record",
      ko: "카탈로그 권한, 행 필터, 컬럼 마스크, 한국형 PII 마스킹, 감사 기록을 설정합니다",
    },
    icon: ShieldCheck,
    href: "/help/governance",
    topics: [
      { en: "Grants", ko: "권한" },
      { en: "Row and column policy", ko: "행·컬럼 정책" },
      { en: "PII", ko: "PII" },
      { en: "Audit", ko: "감사" },
      { en: "Spend", ko: "비용" },
    ],
  },
  {
    title: { en: "Knowledge & RAG", ko: "Knowledge & RAG" },
    description: {
      en: "Build a collection, check what it retrieves, and get answers that cite their sources",
      ko: "컬렉션을 만들고 검색 결과를 확인한 뒤, 출처를 인용하는 답변을 받습니다",
    },
    icon: Sparkles,
    href: "/help/knowledge",
    topics: [
      { en: "Collections", ko: "컬렉션" },
      { en: "Ingestion", ko: "수집" },
      { en: "Semantic search", ko: "의미 검색" },
      { en: "Citations", ko: "인용" },
      { en: "Refresh", ko: "갱신" },
    ],
  },
  {
    title: { en: "Connect an application or agent", ko: "애플리케이션·에이전트 연결" },
    description: {
      en: "An identity per agent, a scoped key, then read-only MCP, REST or an agent gateway",
      ko: "에이전트마다 계정을 만들고 범위가 제한된 키를 발급한 뒤, 읽기 전용 MCP나 REST로 연결합니다",
    },
    icon: Plug,
    href: "/help/integrate",
    topics: [
      { en: "Service accounts", ko: "서비스 계정" },
      { en: "Scoped keys", ko: "범위 제한 키" },
      { en: "MCP", ko: "MCP" },
      { en: "REST endpoints", ko: "REST 엔드포인트" },
      { en: "Audit", ko: "감사" },
    ],
  },
  {
    title: { en: "Change the configuration", ko: "설정 변경" },
    description: {
      en: "Helm values and upgrade commands for this deployment's profile",
      ko: "이 배포 프로파일의 Helm 값과 업그레이드 명령을 안내합니다",
    },
    icon: Settings2,
    href: "/help/operate",
    topics: [
      { en: "Helm values", ko: "Helm 값" },
      { en: "Upgrade", ko: "업그레이드" },
      { en: "SMTP alerts", ko: "SMTP 알림" },
    ],
  },
]

type Quick = { question: L; answer: L; href: string }

// "What should I do first?" depends on whether the deployment has a query engine.
const quickHelpEngine: Quick = {
  question: { en: "What should I do first?", ko: "처음에 무엇을 해야 하나요?" },
  answer: {
    en: "Open Sources and connect a database (or add the sample data), run a sync, then query the new table in Analytics. Add grants and AI after that.",
    ko: "Sources에서 데이터베이스를 연결하거나 샘플 데이터를 추가하고, 동기화한 뒤 Analytics에서 새 테이블을 조회합니다. 권한 설정과 AI 기능은 그다음에 붙입니다.",
  },
  href: "/docs/quickstart",
}

const quickHelpCore: Quick = {
  question: { en: "What should I do first?", ko: "처음에 무엇을 해야 하나요?" },
  answer: {
    en: "This profile has no query engine. Create a Knowledge collection, ingest a small representative source, test semantic search, then test cited answers.",
    ko: "이 프로파일에는 쿼리 엔진이 없습니다. Knowledge 컬렉션을 만들고 대표적인 소스를 수집한 뒤, 의미 검색을 확인하고 인용 답변을 시험합니다.",
  },
  href: "/docs/quickstart",
}

const quickHelp: Quick[] = [
  {
    question: { en: "Why is a menu missing?", ko: "메뉴가 보이지 않는 이유는 무엇인가요?" },
    answer: {
      en: "Lakehouse menus (Catalog, Analytics, Sources, Metrics) appear only when this deployment has a catalog and Trino. AI-only profiles show Knowledge and the AI menus.",
      ko: "Lakehouse 메뉴(Catalog, Analytics, Sources, Metrics)는 카탈로그와 Trino가 있는 배포에서만 나타납니다. AI 전용 프로파일에는 Knowledge와 AI 메뉴만 보입니다.",
    },
    href: "/docs/profiles",
  },
  {
    question: { en: "Can I use Glue and Polaris together?", ko: "Glue와 Polaris를 함께 쓸 수 있나요?" },
    answer: {
      en: "Yes. Several catalogs run side by side with per-catalog grants. Each table has one owner; the other catalog sees a read-only mirror.",
      ko: "네. 여러 카탈로그를 나란히 두고 카탈로그별로 권한을 줄 수 있습니다. 테이블마다 소유 카탈로그는 하나이고, 다른 카탈로그에는 읽기 전용 미러가 보입니다.",
    },
    href: "/docs/catalogs",
  },
  {
    question: { en: "How portable is my deployment?", ko: "배포를 다른 환경으로 옮기기 쉬운가요?" },
    answer: {
      en: "Data stays in S3-API storage as Iceberg, and catalog export moves registrations without copying data. Review the documented limits before an exit drill.",
      ko: "데이터는 S3 API 스토리지에 Iceberg로 남고, 카탈로그 내보내기는 데이터 복사 없이 등록 정보만 옮깁니다. 이전 연습 전에 문서의 제약 사항을 확인하세요.",
    },
    href: "/docs/exit-strategy",
  },
  {
    question: { en: "Who can see which data?", ko: "누가 어떤 데이터를 볼 수 있나요?" },
    answer: {
      en: "Catalog grants decide who reads a catalog, row filters and column masks apply on the SQL path, and PII is masked during sync. Knowledge collections use owner, admin and shared access.",
      ko: "카탈로그 권한이 읽기 범위를 정하고, 행 필터와 컬럼 마스크는 SQL 경로에 적용되며, PII는 동기화 중에 마스킹됩니다. Knowledge 컬렉션은 소유자·관리자·공유 대상으로 제어합니다.",
    },
    href: "/docs/governance",
  },
  {
    question: { en: "Where do I check an incident?", ko: "문제가 생기면 어디부터 확인하나요?" },
    answer: {
      en: "Start with the active profile, then Services and System, before checking storage, the catalog, Trino or the model adapter.",
      ko: "활성 프로파일을 확인한 다음 Services와 System을 보고, 그 뒤에 스토리지, 카탈로그, Trino, 모델 어댑터를 차례로 점검합니다.",
    },
    href: "/docs/troubleshooting",
  },
]

// The Guides half of the Help workspace — the task-oriented hub. Rendered in the
// default (?tab omitted) panel; the guide article pages (/help/catalog, etc.)
// remain separate routes reached from the cards below.
function GuidesHub() {
  const caps = useCapabilities()
  const { t } = useHelpLocale()
  const profile = getProductProfile(caps)
  const quick = [caps.query === true ? quickHelpEngine : quickHelpCore, ...quickHelp]
  // Guides explain setup and troubleshooting even when their optional product
  // capability is disabled; direct product routes remain capability-gated.
  const visibleGuides = guides

  return (
    <div className="flex flex-col">
      {/* Workspace top bar — same height as the Documentation index bar so
          switching tabs keeps the chrome steady. */}
      <div className="flex items-center gap-1.5 border-b px-3 h-11 shrink-0 bg-background">
        <HelpTabs active="guides" />
      </div>

      <div className="mx-auto w-full max-w-[1180px] flex-1 space-y-6 px-6 py-6">
        <PageHeader
          title={t({ en: "Help", ko: "도움말" })}
          description={t({
            en: "Guides for what this deployment runs, and the API and MCP reference.",
            ko: "이 배포에서 쓰는 기능별 가이드와 API·MCP 참고 자료입니다.",
          })}
        >
          <p className="mt-2 text-xs text-muted-foreground">
            {t({ en: "Profile", ko: "프로파일" })}: <span className="font-medium text-foreground">{profile.label}</span>
            {" · "}<Link href="/docs/profiles" className="text-primary hover:underline">{t({ en: "Compare profiles", ko: "프로파일 비교" })}</Link>
          </p>
        </PageHeader>

        <section aria-label={t({ en: "Guides", ko: "가이드" })} className="grid gap-2.5 md:grid-cols-2">
          {visibleGuides.map((guide) => {
            const Icon = guide.icon
            const off = guide.capability && caps[guide.capability] !== true
            return (
              <Link key={guide.href} href={guide.href}
                    className="group flex items-start gap-3 rounded-xl border bg-card p-3.5 transition-colors hover:border-primary/40">
                <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-2 text-sm font-semibold group-hover:text-primary">
                    {t(guide.title)}
                    {/* Guides stay listed when a module is off — they explain setup — but say so. */}
                    {off && (
                      <Badge variant="outline" className="border-[var(--dp-warn)]/25 bg-[var(--dp-warn)]/10 text-2xs font-medium text-[var(--dp-warn-text)]">
                        {t({ en: "Not enabled here", ko: "이 배포에서는 꺼져 있음" })}
                      </Badge>
                    )}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">{t(guide.description)}</span>
                  <span className="mt-1 block text-2xs text-muted-foreground">{guide.topics.map(x => t(x)).join(", ")}</span>
                </span>
              </Link>
            )
          })}
        </section>

        <section className="space-y-3">
          <h2 className="text-xl font-bold">{t({ en: "Quick help", ko: "빠른 도움말" })}</h2>
          <Card>
            <CardContent className="divide-y p-0">
              {quick.map((item) => (
                <Link key={item.question.en} href={item.href} className="group flex items-start justify-between gap-4 p-4 hover:bg-muted/50">
                  <div>
                    <h3 className="font-medium group-hover:text-primary">{t(item.question)}</h3>
                    <p className="mt-1 text-sm text-muted-foreground">{t(item.answer)}</p>
                  </div>
                  <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                </Link>
              ))}
            </CardContent>
          </Card>
        </section>

        <section className="grid gap-4 md:grid-cols-3">
          <Link href="/help?tab=docs"><Resource icon={BookOpen} title={t({ en: "Documentation", ko: "문서" })} description={t({ en: "Concepts, profiles, portability, and operations", ko: "개념, 프로파일, 이식성, 운영" })} /></Link>
          <Link href="/storage"><Resource icon={HardDrive} title={t({ en: "Storage", ko: "Storage (스토리지)" })} description={t({ en: "Inspect configured objects and usage", ko: "설정된 객체와 사용량을 확인합니다" })} /></Link>
          <Link href="/services"><Resource icon={Layers} title={t({ en: "Services", ko: "Services (서비스)" })} description={t({ en: "Check workloads and external dependencies", ko: "워크로드와 외부 의존성의 상태를 확인합니다" })} /></Link>
        </section>
      </div>
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

// Help workspace — one entry, two tabs. ?tab=docs selects the Documentation
// index; anything else is the task-oriented Guides hub. Help is not
// capability-gated, so there is no CapabilityGate here.
function HelpWorkspace() {
  const tab = useSearchParams().get("tab")
  return tab === "docs" ? <DocsIndex /> : <GuidesHub />
}

export default function HelpPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <HelpWorkspace />
    </Suspense>
  )
}
