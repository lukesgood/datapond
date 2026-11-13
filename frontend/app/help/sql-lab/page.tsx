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
  Code2,
  Play,
  History,
  Database,
  AlertCircle,
  Lightbulb,
  BookOpen,
  Share2,
  ShieldCheck,
  Sparkles,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import Link from "next/link"
import { HelpLocaleToggle, useHelpLocale } from "@/components/help/locale"
import type { L } from "@/lib/help-locale"

const QUICK_START: { title: L; body: L }[] = [
  {
    title: { en: "Open Analytics", ko: "Analytics 열기" },
    body: {
      en: "Go to Lakehouse → Analytics. The editor runs Trino SQL, and the schema tree on the left lists every catalog you may use.",
      ko: "Lakehouse → Analytics로 이동합니다. 편집기는 Trino SQL을 실행하며, 왼쪽 스키마 트리에 사용할 수 있는 모든 catalog가 나옵니다.",
    },
  },
  {
    title: { en: "Find a table and write a query", ko: "테이블을 찾아 쿼리 작성" },
    body: {
      en: "Expand a catalog, schema and table in the tree to see columns, and click a name to insert it. Always use the full name catalog.schema.table.",
      ko: "트리에서 catalog, schema, 테이블을 펼쳐 컬럼을 확인하고, 이름을 눌러 편집기에 넣습니다. 항상 catalog.schema.table 전체 이름을 쓰세요.",
    },
  },
  {
    title: { en: "Run it", ko: "실행" },
    body: {
      en: "Click Run. Results appear below as a table; switch to a chart or save the result to a dashboard.",
      ko: "Run을 누르면 결과가 아래에 표로 나옵니다. 차트로 바꾸거나 대시보드에 저장할 수 있습니다.",
    },
  },
]

const FEATURES: { icon: "code" | "ai" | "history" | "share" | "shield"; title: L; body: L }[] = [
  {
    icon: "code",
    title: { en: "Editor and schema tree", ko: "편집기와 스키마 트리" },
    body: {
      en: "Trino SQL with a tree of every catalog the caller may use: lake catalogs and source catalogs (src_<slug>).",
      ko: "호출자가 쓸 수 있는 모든 catalog(lake catalog와 src_<slug> source catalog)가 트리로 나오는 Trino SQL 편집기입니다.",
    },
  },
  {
    icon: "ai",
    title: { en: "AI SQL generation", ko: "AI SQL 생성" },
    body: {
      en: "Describe what you want in plain language and the assistant drafts SQL from the tables you can see. Read the result before running it. Needs the AI module.",
      ko: "원하는 내용을 자연어로 적으면 볼 수 있는 테이블을 바탕으로 SQL 초안을 만들어 줍니다. 실행 전에 결과를 꼭 읽어 보세요. AI 모듈이 필요합니다.",
    },
  },
  {
    icon: "history",
    title: { en: "History", ko: "기록" },
    body: {
      en: "Past queries are listed with their status, so you can reopen and rerun them.",
      ko: "지난 쿼리가 상태와 함께 목록에 남아 있어 다시 열고 재실행할 수 있습니다.",
    },
  },
  {
    icon: "share",
    title: { en: "Charts and dashboards", ko: "차트와 대시보드" },
    body: {
      en: "Turn a result into a chart and pin it to a saved dashboard. Business analysts can build dashboards from SELECT queries.",
      ko: "결과를 차트로 만들어 저장된 대시보드에 추가합니다. business analyst도 SELECT 쿼리로 대시보드를 만들 수 있습니다.",
    },
  },
  {
    icon: "shield",
    title: { en: "Governance applies here", ko: "거버넌스가 그대로 적용됩니다" },
    body: {
      en: "Row filters and column masks apply to every result, including the Catalog preview. Korean PII is masked by role.",
      ko: "행 필터와 컬럼 마스킹은 Catalog 미리보기를 포함한 모든 결과에 적용됩니다. 한국어 PII는 역할에 따라 마스킹됩니다.",
    },
  },
]

const RULES: { title: L; body: L }[] = [
  {
    title: { en: "Three-part names", ko: "세 부분 이름" },
    body: {
      en: "Use catalog.schema.table. A bare table name resolves only in lake catalogs; tables in a source catalog need the qualified name.",
      ko: "catalog.schema.table을 사용하세요. 이름만 쓰는 방식은 lake catalog에서만 해석되고, source catalog의 테이블은 전체 이름이 필요합니다.",
    },
  },
  {
    title: { en: "Write statements", ko: "쓰기 문장" },
    body: {
      en: "SELECT is allowed for every role that can query. INSERT, MERGE, CREATE and DROP need the query:write permission (for example admins and data engineers).",
      ko: "SELECT는 조회 가능한 모든 역할이 쓸 수 있습니다. INSERT, MERGE, CREATE, DROP에는 query:write 권한이 필요합니다(예: admin, data engineer).",
    },
  },
  {
    title: { en: "Mirrors are read through their owner", ko: "mirror는 owner를 통해 읽습니다" },
    body: {
      en: "If a table is a mirror (see Catalog → Export), the query runs against the owner and uses the owner's grants and policies. Writes to a mirror are refused with 409.",
      ko: "테이블이 mirror라면(Catalog → Export 참고) 쿼리는 owner를 대상으로 실행되며 owner의 grant와 정책이 적용됩니다. mirror에 쓰면 409로 거부됩니다.",
    },
  },
  {
    title: { en: "Catalog access", ko: "catalog 접근 권한" },
    body: {
      en: "You see only catalogs you were granted. A source catalog follows the source's share list.",
      ko: "grant를 받은 catalog만 보입니다. source catalog는 해당 소스의 공유 목록을 따릅니다.",
    },
  },
]

const EXAMPLES: { title: L; body: L; sql: string }[] = [
  {
    title: { en: "Federate the lake with a live source", ko: "lake와 연결된 소스를 함께 조회" },
    body: {
      en: "Join an Iceberg table with a table in a source database in one query. No sync is needed.",
      ko: "Iceberg 테이블과 소스 데이터베이스의 테이블을 한 쿼리에서 조인합니다. 동기화가 필요 없습니다.",
    },
    sql: `SELECT c.region, count(*) AS orders, sum(o.amount) AS revenue
FROM iceberg.default.orders o
JOIN src_crm.public.customers c ON c.id = o.customer_id
GROUP BY c.region
ORDER BY revenue DESC`,
  },
  {
    title: { en: "Validate a synced table", ko: "동기화한 테이블 검증" },
    body: {
      en: "Compare row counts between the source and its Iceberg copy after a sync.",
      ko: "동기화 뒤 소스와 Iceberg 사본의 행 수를 비교합니다.",
    },
    sql: `SELECT
  (SELECT count(*) FROM src_crm.public.customers) AS source_rows,
  (SELECT count(*) FROM iceberg.default.customers) AS lake_rows`,
  },
]

const FAQ: { q: L; a: L }[] = [
  {
    q: { en: "Which SQL dialect is it?", ko: "어떤 SQL 방언인가요?" },
    a: {
      en: "Trino SQL, for every catalog. DataPond runs one engine, so the same query works on Glue, Polaris and source catalogs.",
      ko: "모든 catalog에서 Trino SQL입니다. DataPond는 엔진이 하나라서 같은 쿼리가 Glue, Polaris, source catalog에서 똑같이 동작합니다.",
    },
  },
  {
    q: { en: "Can I share a query or a result?", ko: "쿼리나 결과를 공유할 수 있나요?" },
    a: {
      en: "Save the result as a chart on a dashboard and share the dashboard with your team. Dashboard viewers see data through their own grants and masks.",
      ko: "결과를 차트로 만들어 대시보드에 저장하고 팀과 공유하세요. 대시보드를 보는 사람은 자신의 grant와 마스킹이 적용된 데이터를 봅니다.",
    },
  },
  {
    q: { en: "Where do I see who ran what?", ko: "누가 무엇을 실행했는지는 어디서 보나요?" },
    a: {
      en: "Your own runs are in History. Admins and auditors see the full query log in Governance.",
      ko: "본인의 실행 기록은 History에 있습니다. admin과 auditor는 Governance의 query log에서 전체를 볼 수 있습니다.",
    },
  },
]

const TROUBLE: { title: L; body: L }[] = [
  {
    title: { en: "Table not found", ko: "테이블을 찾을 수 없음" },
    body: {
      en: "Use the three-part name. A source table needs its src_<slug> prefix, and you need a grant on that catalog. After adding a source, wait about one minute for Trino to restart.",
      ko: "세 부분 이름을 쓰세요. 소스 테이블은 src_<slug> 접두어가 필요하고 해당 catalog에 grant가 있어야 합니다. 소스를 추가한 직후라면 Trino 재시작을 위해 1분쯤 기다리세요.",
    },
  },
  {
    title: { en: "Permission denied on a write", ko: "쓰기에서 권한 거부" },
    body: {
      en: "Your role lacks query:write, or the table is a mirror owned by another catalog. Ask an admin, or write to the owner table named in the error.",
      ko: "역할에 query:write가 없거나 다른 catalog가 소유한 mirror 테이블입니다. 관리자에게 요청하거나 오류에 나온 owner 테이블에 쓰세요.",
    },
  },
  {
    title: { en: "Query is slow", ko: "쿼리가 느립니다" },
    body: {
      en: "Select only the columns you need and filter early. Joins that pull a whole source table over the network are slower than joins on synced Iceberg copies; sync hot tables from Sources. For heavy use, an admin can add Trino workers.",
      ko: "필요한 컬럼만 선택하고 조건은 일찍 거세요. 소스 테이블 전체를 네트워크로 끌어오는 조인은 동기화된 Iceberg 사본 조인보다 느립니다. 자주 쓰는 테이블은 Sources에서 동기화하세요. 부하가 크면 관리자가 Trino worker를 늘릴 수 있습니다.",
    },
  },
  {
    title: { en: "Values look masked or rows are missing", ko: "값이 가려져 있거나 행이 없습니다" },
    body: {
      en: "That is a column mask or row filter from Governance applying to your role. It is expected, not an error.",
      ko: "Governance의 컬럼 마스킹 또는 행 필터가 내 역할에 적용된 것입니다. 오류가 아니라 정상 동작입니다.",
    },
  },
]

const ICONS = { code: Code2, ai: Sparkles, history: History, share: Share2, shield: ShieldCheck }

export default function SqlLabHelpPage() {
  const { t } = useHelpLocale()
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
            <BreadcrumbPage>Analytics</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="inline-flex p-3 rounded-lg bg-blue-500/10">
            <Code2 className="h-8 w-8 text-blue-500" />
          </div>
          <div>
            <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-primary">Guide</p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight">Analytics</h1>
            <p className="mt-2 text-muted-foreground">
              {t({
                en: "Run Trino SQL across the lake and your live source databases, then chart the result",
                ko: "lake와 연결된 소스 데이터베이스를 가로질러 Trino SQL을 실행하고 결과를 차트로 만듭니다",
              })}
            </p>
          </div>
        </div>
        <HelpLocaleToggle />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Play className="h-5 w-5" />
            {t({ en: "Quick Start", ko: "빠른 시작" })}
          </CardTitle>
          <CardDescription>{t({ en: "Run your first query in 3 steps", ko: "3단계로 첫 쿼리 실행" })}</CardDescription>
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
                      <Link href="/query" className="text-primary hover:underline">
                        Analytics
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
            <Database className="h-5 w-5" />
            {t({ en: "What Analytics gives you", ko: "Analytics 기능" })}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            {FEATURES.map((f, i) => {
              const Icon = ICONS[f.icon]
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
            <Badge variant="outline">catalog.schema.table</Badge>
            {t({ en: "Naming and permissions", ko: "이름 지정과 권한" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {RULES.map((r, i) => (
            <div key={i} className="space-y-1">
              <h3 className="font-semibold">{t(r.title)}</h3>
              <p className="text-sm text-muted-foreground">{t(r.body)}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lightbulb className="h-5 w-5" />
            {t({ en: "Examples", ko: "예제" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {EXAMPLES.map((e, i) => (
            <div key={i} className="space-y-2">
              <h3 className="font-semibold">{t(e.title)}</h3>
              <p className="text-sm text-muted-foreground">{t(e.body)}</p>
              <pre className="bg-muted p-3 rounded-lg text-xs overflow-x-auto">
                <code>{e.sql}</code>
              </pre>
            </div>
          ))}
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
            <Link href="/help/catalog">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                {t({ en: "Catalog Guide", ko: "Catalog 가이드" })}
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
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
