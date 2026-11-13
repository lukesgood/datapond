"use client"

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
  Database,
  FolderOpen,
  Table,
  Search,
  AlertCircle,
  CheckCircle2,
  BookOpen,
  FileText,
  Copy,
  Lock,
  Send,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import Link from "next/link"
import { HelpLocaleToggle, useHelpLocale } from "@/components/help/locale"
import type { L } from "@/lib/help-locale"

const QUICK_START: { title: L; body: L }[] = [
  {
    title: { en: "Open Catalog", ko: "Catalog 열기" },
    body: {
      en: "Go to Lakehouse → Catalog. Every catalog you may read is listed: lake catalogs and source catalogs.",
      ko: "Lakehouse → Catalog로 이동합니다. 읽을 수 있는 모든 카탈로그(레이크 카탈로그와 소스 카탈로그)가 나열됩니다.",
    },
  },
  {
    title: { en: "Pick a catalog and a namespace", ko: "카탈로그와 네임스페이스 선택" },
    body: {
      en: "Choose a catalog, then use the namespace chips to narrow the list. The search box matches table names, ignoring case.",
      ko: "카탈로그를 고른 뒤 네임스페이스 칩으로 목록을 좁힙니다. 검색창은 대소문자를 구분하지 않고 테이블 이름을 찾습니다.",
    },
  },
  {
    title: { en: "Open a table", ko: "테이블 열기" },
    body: {
      en: "The table page shows the schema, a data preview and statistics. The preview runs through the same row filters and column masks as Analytics.",
      ko: "테이블 페이지에서 스키마, 데이터 미리보기, 통계를 볼 수 있습니다. 미리보기는 Analytics와 같은 행 필터와 컬럼 마스킹을 거칩니다.",
    },
  },
]

const CONCEPTS: { badge: string; label: L; body: L }[] = [
  {
    badge: "Lake catalog",
    label: { en: "Iceberg tables DataPond manages", ko: "DataPond가 관리하는 Iceberg 테이블" },
    body: {
      en: "AWS Glue or Apache Polaris (Iceberg REST). You can run several side by side, each with its own grants. One is the default; bare table names resolve only in lake catalogs.",
      ko: "AWS Glue 또는 Apache Polaris(Iceberg REST)입니다. 여러 개를 나란히 운영할 수 있고 카탈로그마다 권한이 따로 있습니다. 하나가 기본값이며, 테이블 이름만 쓰는 방식은 레이크 카탈로그에서만 해석됩니다.",
    },
  },
  {
    badge: "Source catalog",
    label: { en: "src_<slug>, a live database", ko: "src_<slug>, 연결된 데이터베이스" },
    body: {
      en: "Each database source from Sources is a read-only Trino catalog. Browse and query it in place; sync it into a lake catalog when you want a copy.",
      ko: "Sources에 추가한 데이터베이스 소스마다 읽기 전용 Trino 카탈로그가 생깁니다. 그 자리에서 탐색·조회할 수 있고, 복사본이 필요하면 레이크 카탈로그로 동기화합니다.",
    },
  },
  {
    badge: "Namespace",
    label: { en: "Schema inside a catalog", ko: "카탈로그 안의 스키마" },
    body: {
      en: "Namespaces group tables by domain or team, for example sales or analytics. Each catalog has its own set, shown as chips.",
      ko: "네임스페이스는 sales, analytics처럼 도메인이나 팀별로 테이블을 묶습니다. 카탈로그마다 따로 있으며 칩으로 표시됩니다.",
    },
  },
  {
    badge: "Table",
    label: { en: "Apache Iceberg table", ko: "Apache Iceberg 테이블" },
    body: {
      en: "Stored as open files in your S3-compatible bucket, with ACID commits, time travel and schema evolution.",
      ko: "S3 호환 버킷에 열린 형식의 파일로 저장되며 ACID 커밋, time travel, 스키마 진화를 지원합니다.",
    },
  },
]

const EXPORT_STEPS: L[] = [
  { en: "Open Export… on the Catalog page, or in Settings → Data catalogs. Choose the source catalog and the target catalog.", ko: "Catalog 페이지 또는 Settings → Data catalogs에서 Export…를 엽니다. 원본 카탈로그와 대상 카탈로그를 고릅니다." },
  { en: "Plan: DataPond lists which tables would be registered and which locations the target must allow. Nothing changes yet.", ko: "Plan: 등록될 테이블과 대상이 허용해야 하는 위치를 보여 줍니다. 아직 아무것도 바뀌지 않습니다." },
  { en: "Apply: the tables are registered in the target catalog. No data files are copied, and row counts stay equal.", ko: "Apply: 테이블이 대상 카탈로그에 등록됩니다. 데이터 파일은 복사되지 않으며 행 수는 그대로입니다." },
]

const FEATURES: { icon: "search" | "file" | "send" | "db"; title: L; body: L }[] = [
  {
    icon: "search",
    title: { en: "Search and filter", ko: "검색과 필터" },
    body: {
      en: "Search by table name and filter by namespace within the selected catalog.",
      ko: "선택한 카탈로그 안에서 테이블 이름으로 검색하고 네임스페이스로 필터링합니다.",
    },
  },
  {
    icon: "file",
    title: { en: "Table page", ko: "테이블 페이지" },
    body: {
      en: "Schema, properties, partition spec, preview rows and statistics, all read from Iceberg metadata.",
      ko: "스키마, 속성, 파티션 spec, 미리보기 행, 통계를 Iceberg 메타데이터에서 읽어 보여 줍니다.",
    },
  },
  {
    icon: "send",
    title: { en: "Send to Knowledge", ko: "Send to Knowledge" },
    body: {
      en: "Turns a table into a Knowledge source so the AI can answer from it with citations. PII is masked on the way in, and freshness can be rescheduled. Needs the Knowledge module.",
      ko: "테이블을 Knowledge 소스로 보내 AI가 출처를 달아 답할 수 있게 합니다. 수집 시 PII가 마스킹되며 최신성 갱신을 예약할 수 있습니다. Knowledge 모듈이 필요합니다.",
    },
  },
  {
    icon: "db",
    title: { en: "Data catalogs panel", ko: "Data catalogs 패널" },
    body: {
      en: "Admins add, test, edit, set the default and grant access to catalogs in Settings → Data catalogs.",
      ko: "관리자는 Settings → Data catalogs에서 카탈로그를 추가, 테스트, 수정하고 기본값을 지정하며 접근 권한을 부여합니다.",
    },
  },
]

const FAQ: { q: L; a: L }[] = [
  {
    q: { en: "Why can't I see a catalog?", ko: "왜 어떤 카탈로그가 보이지 않나요?" },
    a: {
      en: "Catalogs are shown by grants. Ask an admin to grant your role access in Settings → Data catalogs, or for a source, to add you to its share list.",
      ko: "카탈로그는 권한에 따라 보입니다. 관리자에게 Settings → Data catalogs에서 권한 부여를 요청하세요. 소스라면 공유 목록에 추가해 달라고 요청하세요.",
    },
  },
  {
    q: { en: "Does Export copy my data?", ko: "Export는 데이터를 복사하나요?" },
    a: {
      en: "No. It registers the same Iceberg files in another catalog, for example Glue to Polaris. Both catalogs then point at the same S3 location.",
      ko: "아니요. 같은 Iceberg 파일을 다른 카탈로그(예: Glue에서 Polaris)에 등록할 뿐입니다. 두 카탈로그가 같은 S3 위치를 가리킵니다.",
    },
  },
  {
    q: { en: "Is lineage available?", ko: "lineage도 볼 수 있나요?" },
    a: {
      en: "Lineage and data-quality views come from the optional OpenMetadata add-on and appear only when it is enabled.",
      ko: "lineage와 데이터 품질 화면은 선택 add-on인 OpenMetadata에서 제공되며 켜져 있을 때만 나타납니다.",
    },
  },
]

const TROUBLE: { title: L; body: L }[] = [
  {
    title: { en: "Table is missing from the list", ko: "목록에 테이블이 없습니다" },
    body: {
      en: "Check the catalog and namespace chips, and that you have a grant on the catalog. A just-synced table appears once the sync run finishes.",
      ko: "카탈로그와 네임스페이스 칩, 그리고 해당 카탈로그에 대한 권한이 있는지 확인하세요. 방금 동기화한 테이블은 실행이 끝나야 보입니다.",
    },
  },
  {
    title: { en: "Export plan says locations are needed", ko: "Export plan이 위치를 요구합니다" },
    body: {
      en: "A Polaris target only registers tables under locations it allows. The plan lists each table's parent prefix as allowed_locations_needed; an admin adds these to the Polaris catalog, then run the plan again.",
      ko: "Polaris 대상은 허용된 위치 아래의 테이블만 등록합니다. plan이 테이블별 상위 prefix를 allowed_locations_needed로 알려 주므로, 관리자가 Polaris 카탈로그에 추가한 뒤 plan을 다시 실행하세요.",
    },
  },
  {
    title: { en: "A mirror shows diverged or error", ko: "미러가 diverged 또는 error입니다" },
    body: {
      en: "See Mirrors below. Click Check now first; if it stays diverged, someone committed to the table outside DataPond.",
      ko: "아래 Mirrors 항목을 보세요. 먼저 Check now를 누르고, 계속 diverged라면 DataPond 밖에서 누군가 그 테이블에 커밋한 것입니다.",
    },
  },
]

const FEATURE_ICON = { search: Search, file: FileText, send: Send, db: Database }

export default function CatalogHelpPage() {
  const { t } = useHelpLocale()
  return (
    <div className="flex-1 space-y-6 p-8 pt-6 max-w-5xl">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="/dashboard">{t({ en: "Home", ko: "홈" })}</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink href="/help">{t({ en: "Guides", ko: "가이드" })}</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Catalog</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="inline-flex p-3 rounded-lg bg-[var(--dp-good)]/10">
            <Database className="h-8 w-8 text-[var(--dp-good-text)]" />
          </div>
          <div>
            <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-primary">Guide</p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight">Catalog</h1>
            <p className="mt-2 text-muted-foreground">
              {t({
                en: "Browse lake and source catalogs, send tables to Knowledge, and share tables across catalogs",
                ko: "레이크 카탈로그와 소스 카탈로그를 탐색하고, 테이블을 Knowledge로 보내고, 카탈로그 간에 테이블을 공유합니다",
              })}
            </p>
          </div>
        </div>
        <HelpLocaleToggle />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            {t({ en: "Quick Start", ko: "빠른 시작" })}
          </CardTitle>
          <CardDescription>{t({ en: "Explore your catalogs in 3 steps", ko: "3단계로 카탈로그 둘러보기" })}</CardDescription>
        </CardHeader>
        <CardContent className="pt-1">
          {QUICK_START.map((s, i) => (
            <div key={i} className={`relative flex gap-3 ${i < QUICK_START.length - 1 ? "pb-6" : ""}`}>
              {i < QUICK_START.length - 1 && (
                <span aria-hidden className="absolute left-4 top-10 bottom-0 w-px -translate-x-1/2 bg-border" />
              )}
              <div className="relative z-10 flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold">
                {i + 1}
              </div>
              <div>
                <h3 className="font-semibold">{t(s.title)}</h3>
                <p className="text-sm text-muted-foreground">
                  {t(s.body)}
                  {i === 0 && (
                    <>
                      {" "}
                      <Link href="/catalog" className="text-primary hover:underline">
                        /catalog
                      </Link>
                    </>
                  )}
                </p>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FolderOpen className="h-5 w-5" />
            {t({ en: "Lake catalogs, source catalogs, namespaces", ko: "레이크 카탈로그, 소스 카탈로그, 네임스페이스" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {CONCEPTS.map((c) => (
            <div key={c.badge} className="space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="outline">{c.badge}</Badge>
                <span className="text-sm text-muted-foreground">{t(c.label)}</span>
              </div>
              <p className="text-sm text-muted-foreground">{t(c.body)}</p>
            </div>
          ))}
          <Alert className="mt-4">
            <FileText className="h-4 w-4" />
            <AlertTitle>{t({ en: "Full table path", ko: "전체 테이블 경로" })}</AlertTitle>
            <AlertDescription>
              {t({
                en: "Tables are addressed as catalog.namespace.table, for example iceberg.sales.orders or src_crm.public.customers. The same name works in Analytics.",
                ko: "테이블은 catalog.namespace.table로 지정합니다. 예: iceberg.sales.orders, src_crm.public.customers. Analytics에서도 같은 이름을 씁니다.",
              })}
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Table className="h-5 w-5" />
            {t({ en: "What you can do", ko: "할 수 있는 일" })}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            {FEATURES.map((f, i) => {
              const Icon = FEATURE_ICON[f.icon]
              return (
                <div key={i} className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4 text-muted-foreground" />
                    <h3 className="font-semibold">{t(f.title)}</h3>
                  </div>
                  <p className="text-sm text-muted-foreground">{t(f.body)}</p>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Copy className="h-5 w-5" />
            {t({ en: "Export… and Mirrors", ko: "Export…와 Mirrors" })}
          </CardTitle>
          <CardDescription>
            {t({
              en: "Register a catalog's Iceberg tables in another catalog without copying data. Needs catalog:write (admins and data engineers).",
              ko: "데이터를 복사하지 않고 한 카탈로그의 Iceberg 테이블을 다른 카탈로그에 등록합니다. catalog:write 권한(admin, data engineer)이 필요합니다.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ol className="space-y-2 ml-5 list-decimal text-sm text-muted-foreground">
            {EXPORT_STEPS.map((s, i) => (
              <li key={i}>{t(s)}</li>
            ))}
          </ol>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border p-3 space-y-1">
              <Badge variant="outline">mirror</Badge>
              <p className="text-sm text-muted-foreground">
                {t({
                  en: "Default. The source catalog stays the owner and the target gets a read-only mirror. Use it to let another engine or team read the table.",
                  ko: "기본값입니다. 원본 카탈로그가 계속 소유자이고 대상에는 읽기 전용 미러가 생깁니다. 다른 엔진이나 팀이 테이블을 읽게 할 때 씁니다.",
                })}
              </p>
            </div>
            <div className="rounded-lg border p-3 space-y-1">
              <Badge variant="outline">move</Badge>
              <p className="text-sm text-muted-foreground">
                {t({
                  en: "The target becomes the owner. Use it when you are migrating from one catalog to another, for example Glue to Polaris.",
                  ko: "대상이 소유자가 됩니다. Glue에서 Polaris처럼 카탈로그를 옮길 때 씁니다.",
                })}
              </p>
            </div>
          </div>
          <div className="space-y-1">
            <h3 className="font-semibold">{t({ en: "Locations a Polaris target must allow", ko: "Polaris 대상이 허용해야 하는 위치" })}</h3>
            <p className="text-sm text-muted-foreground">
              {t({
                en: "Polaris only accepts tables whose files sit under its allowed locations. The plan returns allowed_locations_needed, the parent S3 prefix of each table. Add those to the Polaris catalog before you apply.",
                ko: "Polaris는 허용된 위치 아래에 파일이 있는 테이블만 받습니다. plan은 테이블별 상위 S3 prefix를 allowed_locations_needed로 돌려줍니다. apply 전에 이 값을 Polaris 카탈로그에 추가하세요.",
              })}
            </p>
          </div>
          <div className="space-y-1">
            <h3 className="font-semibold">Mirrors</h3>
            <p className="text-sm text-muted-foreground">
              {t({
                en: "The Mirrors list shows each mirror with its status. fresh: it points at the owner's current table. diverged: the table was committed outside DataPond. error: the check failed. A background check runs every 5 minutes and re-points stale mirrors; Check now runs it immediately.",
                ko: "Mirrors 목록은 미러별 상태를 보여 줍니다. fresh는 소유자의 현재 테이블을 가리킨다는 뜻, diverged는 DataPond 밖에서 커밋되었다는 뜻, error는 점검이 실패했다는 뜻입니다. 백그라운드 점검이 5분마다 오래된 미러를 다시 연결하며, Check now는 즉시 실행합니다.",
              })}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lock className="h-5 w-5" />
            {t({ en: "One writer per table", ko: "테이블당 writer는 하나" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            {t({
              en: "A table that two catalogs can see has exactly one owner. The other is a read-only mirror.",
              ko: "두 카탈로그에서 보이는 테이블에는 소유자가 정확히 하나 있고, 나머지는 읽기 전용 미러입니다.",
            })}
          </p>
          <ul className="text-sm text-muted-foreground space-y-1 ml-6 list-disc">
            <li>{t({ en: "Writes and DROP on a mirror are refused with 409, and the error names the owner.", ko: "미러에 대한 쓰기와 DROP은 409로 거부되며 오류에 소유자가 표시됩니다." })}</li>
            <li>{t({ en: "Reads of a mirror run against the owner, so the owner's grants, row filters and masks apply.", ko: "미러 읽기는 소유자를 대상으로 실행되므로 소유자의 권한, 행 필터, 마스킹이 적용됩니다." })}</li>
            <li>{t({ en: "Syncs take a target catalog; point them at the owner.", ko: "동기화의 대상 카탈로그는 소유자로 지정하세요." })}</li>
          </ul>
          <Alert>
            <CheckCircle2 className="h-4 w-4" />
            <AlertTitle>catalog:write</AlertTitle>
            <AlertDescription>
              {t({
                en: "Export and Mirrors need catalog:write, held by admins and data engineers. Adding, editing, defaulting and granting catalogs stay admin-only.",
                ko: "Export와 Mirrors에는 admin과 data engineer가 가진 catalog:write 권한이 필요합니다. 카탈로그의 추가, 수정, 기본값 지정, 권한 부여는 계속 admin만 할 수 있습니다.",
              })}
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5" />
            {t({ en: "Frequently Asked Questions", ko: "자주 묻는 질문" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {FAQ.map((f, i) => (
            <div key={i} className="space-y-2">
              <h3 className="font-semibold">{t(f.q)}</h3>
              <p className="text-sm text-muted-foreground">{t(f.a)}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5" />
            {t({ en: "Troubleshooting", ko: "문제 해결" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {TROUBLE.map((x, i) => (
            <Alert key={i}>
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>{t(x.title)}</AlertTitle>
              <AlertDescription>{t(x.body)}</AlertDescription>
            </Alert>
          ))}
        </CardContent>
      </Card>

      <Card className="bg-gradient-to-r from-primary/10 to-primary/5 border-primary/20">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpen className="h-5 w-5" />
            {t({ en: "Next Steps", ko: "다음 단계" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex gap-2 flex-wrap">
            <Link href="/help/sql-lab">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                {t({ en: "Analytics Guide", ko: "Analytics 가이드" })}
              </Badge>
            </Link>
            <Link href="/help/connectors">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                {t({ en: "Sources Guide", ko: "Sources 가이드" })}
              </Badge>
            </Link>
            <Link href="/docs/catalog-query">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                {t({ en: "Catalog and query docs", ko: "Catalog와 쿼리 문서" })}
              </Badge>
            </Link>
            <Link href="/help/governance">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                {t({ en: "Governance Guide", ko: "Governance 가이드" })}
              </Badge>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
