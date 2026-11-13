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
  Plug,
  Database,
  HardDrive,
  Radio,
  Shield,
  AlertCircle,
  Lightbulb,
  BookOpen,
  Settings,
  Activity,
  Users,
  CalendarClock,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import Link from "next/link"
import { HelpLocaleToggle, useHelpLocale } from "@/components/help/locale"
import type { L } from "@/lib/help-locale"

type Step = { title: L; body: L }
type Block = { title: L; body: L; badges?: L[] }

const QUICK_START: Step[] = [
  {
    title: { en: "Open Sources", ko: "Sources 열기" },
    body: {
      en: "Go to Lakehouse → Sources. The menu appears when the query engine (Trino) is enabled in your deployment.",
      ko: "Lakehouse → Sources로 이동합니다. 배포에서 쿼리 엔진(Trino)이 켜져 있어야 이 메뉴가 보입니다.",
    },
  },
  {
    title: { en: "Add a database source", ko: "데이터베이스 소스 추가" },
    body: {
      en: "Click Add Source, choose PostgreSQL, MySQL, SQL Server, Oracle or MongoDB, and enter host, port, database and a read-only user. Use Test Connection before you save.",
      ko: "Add Source를 눌러 PostgreSQL, MySQL, SQL Server, Oracle, MongoDB 중 하나를 고르고 호스트, 포트, 데이터베이스, 읽기 전용 사용자를 입력합니다. 저장하기 전에 Test Connection으로 확인하세요.",
    },
  },
  {
    title: { en: "Wait for the engine restart", ko: "엔진 재시작 대기" },
    body: {
      en: "A new database source becomes a Trino catalog named src_<slug>. Trino restarts to load it, which takes about one minute. Queries and syncs resume on their own.",
      ko: "새 데이터베이스 소스는 src_<slug>라는 Trino catalog가 됩니다. 이를 불러오기 위해 Trino가 재시작되며 약 1분 걸립니다. 쿼리와 동기화는 재시작 후 자동으로 다시 동작합니다.",
    },
  },
  {
    title: { en: "Browse, then sync tables into Iceberg", ko: "탐색하고 Iceberg로 동기화" },
    body: {
      en: "Pick the tables to copy, choose a sync mode and a Target catalog, then click Sync Now. You can also skip the copy and query the source live from Analytics.",
      ko: "복사할 테이블을 고르고 동기화 모드와 Target catalog를 정한 뒤 Sync Now를 누릅니다. 복사하지 않고 Analytics에서 소스를 바로 조회할 수도 있습니다.",
    },
  },
  {
    title: { en: "Check the sync history", ko: "동기화 이력 확인" },
    body: {
      en: "Open the source to see each run, its row counts and any error. The synced table appears in Catalog under the target catalog.",
      ko: "소스를 열면 실행별 행 수와 오류를 볼 수 있습니다. 동기화된 테이블은 Catalog의 대상 catalog 아래에 나타납니다.",
    },
  },
]

const KINDS: (Block & { icon: "db" | "sample" | "backend" | "stream" })[] = [
  {
    icon: "db",
    title: { en: "Database sources (Trino catalogs)", ko: "데이터베이스 소스 (Trino catalog)" },
    body: {
      en: "PostgreSQL, MySQL, SQL Server, Oracle and MongoDB are mounted in Trino as src_<slug>. You browse them in Catalog, join them with lake tables in Analytics, and copy them into Iceberg with a sync. The copy runs inside Trino as INSERT … SELECT or MERGE.",
      ko: "PostgreSQL, MySQL, SQL Server, Oracle, MongoDB는 Trino에 src_<slug>로 연결됩니다. Catalog에서 탐색하고, Analytics에서 lake 테이블과 조인하고, 동기화로 Iceberg에 복사할 수 있습니다. 복사는 Trino 안에서 INSERT … SELECT 또는 MERGE로 실행됩니다.",
    },
    badges: [{ en: "Federated query", ko: "페더레이션 쿼리" }, { en: "Full / Incremental / Merge", ko: "Full / Incremental / Merge" }, { en: "PII masked", ko: "PII 마스킹" }],
  },
  {
    icon: "sample",
    title: { en: "Sample sources", ko: "샘플 소스" },
    body: {
      en: "Two SQL samples let you try the whole flow without your own database. They connect as the read-only datapond_sample role, so they cannot change anything.",
      ko: "자체 데이터베이스 없이도 전체 흐름을 체험할 수 있는 SQL 샘플 두 개가 있습니다. 읽기 전용 datapond_sample 역할로 연결되므로 데이터를 바꿀 수 없습니다.",
    },
    badges: [{ en: "Read-only", ko: "읽기 전용" }],
  },
  {
    icon: "backend",
    title: { en: "REST, custom Python and S3 sources", ko: "REST, 커스텀 Python, S3 소스" },
    body: {
      en: "These are read by the DataPond backend, not by Trino. S3 and S3-compatible storage (such as MinIO) support CSV, JSON/JSONL and Parquet with prefix discovery. They are not Trino catalogs, so they do not appear as src_<slug>.",
      ko: "Trino가 아니라 DataPond 백엔드가 읽는 소스입니다. S3와 S3 호환 스토리지(MinIO 등)는 prefix 탐색과 함께 CSV, JSON/JSONL, Parquet을 지원합니다. Trino catalog가 아니므로 src_<slug>로 나타나지 않습니다.",
    },
    badges: [{ en: "S3 API", ko: "S3 API" }, { en: "CSV / JSON / Parquet", ko: "CSV / JSON / Parquet" }],
  },
  {
    icon: "stream",
    title: { en: "Streaming (optional add-on)", ko: "스트리밍 (선택 add-on)" },
    body: {
      en: "Kafka and PostgreSQL CDC belong to the optional RisingWave add-on and appear only when it is enabled. Batch sync is enough for most teams.",
      ko: "Kafka와 PostgreSQL CDC는 선택 add-on인 RisingWave에 속하며 켜져 있을 때만 나타납니다. 대부분의 팀은 배치 동기화로 충분합니다.",
    },
    badges: [{ en: "Optional add-on", ko: "선택 add-on" }],
  },
]

const MODES: { name: string; body: L }[] = [
  {
    name: "Full",
    body: {
      en: "Rewrites the whole table in one atomic replace. Readers see either the old table or the new one, never a half-loaded state. Best for small tables and the first load.",
      ko: "테이블 전체를 한 번의 원자적 교체로 다시 씁니다. 읽는 쪽은 이전 테이블 또는 새 테이블만 보고, 중간 상태는 보지 않습니다. 작은 테이블과 첫 적재에 알맞습니다.",
    },
  },
  {
    name: "Incremental",
    body: {
      en: "Copies only rows past a watermark column (a timestamp or increasing ID) since the last run. Index that column at the source.",
      ko: "마지막 실행 이후 watermark 컬럼(타임스탬프 또는 증가하는 ID)을 넘은 행만 복사합니다. 소스에서 해당 컬럼에 인덱스를 두세요.",
    },
  },
  {
    name: "Merge",
    body: {
      en: "Upserts on key columns you choose, so updated rows replace their old versions. Use it when rows change after they are first written.",
      ko: "지정한 키 컬럼 기준으로 upsert 합니다. 처음 쓴 뒤 값이 바뀌는 행이 있을 때 사용합니다.",
    },
  },
]

const SYNC_DETAILS: { title: L; body: L }[] = [
  {
    title: { en: "Target catalog", ko: "Target catalog" },
    body: {
      en: "Each table has its own Target catalog: the lake catalog (Glue or Polaris) that receives the Iceberg table. The choice is remembered for the next sync. Source catalogs cannot be a target; leaving it empty uses the default catalog.",
      ko: "테이블마다 Target catalog를 정합니다. Iceberg 테이블을 받을 lake catalog(Glue 또는 Polaris)입니다. 선택은 다음 동기화에도 기억됩니다. 소스 catalog는 대상이 될 수 없고, 비워 두면 기본 catalog를 씁니다.",
    },
  },
  {
    title: { en: "PII columns", ko: "PII 컬럼" },
    body: {
      en: "PII (including Korean resident numbers, phone numbers and so on) is masked inside the sync, in the SELECT, with the same rules as at read time. The unmasked value never lands in the lake.",
      ko: "주민등록번호, 전화번호 같은 PII는 동기화 안의 SELECT 단계에서 읽기 때와 같은 규칙으로 마스킹됩니다. 원본 값은 lake에 저장되지 않습니다.",
    },
  },
  {
    title: { en: "Partitioning", ko: "파티셔닝" },
    body: {
      en: "For large tables that are usually filtered by date, choose a partition column so queries read fewer files. Iceberg partitioning is hidden: queries do not need a separate partition column.",
      ko: "날짜로 자주 필터링하는 큰 테이블은 파티션 컬럼을 지정하면 쿼리가 읽는 파일이 줄어듭니다. Iceberg 파티셔닝은 숨김 방식이라 쿼리에 별도 파티션 컬럼을 쓰지 않아도 됩니다.",
    },
  },
  {
    title: { en: "Schema changes", ko: "스키마 변경" },
    body: {
      en: "New source columns are added to the Iceberg table automatically. Compatible type widening (for example int to bigint) is applied. Any other type change is refused with an error instead of rewriting data.",
      ko: "소스에 새 컬럼이 생기면 Iceberg 테이블에 자동으로 추가됩니다. 호환되는 타입 확장(예: int → bigint)은 적용됩니다. 그 외 타입 변경은 데이터를 다시 쓰지 않고 오류로 거부됩니다.",
    },
  },
]

const PRACTICES: { icon: "shield" | "activity"; title: L; items: L[] }[] = [
  {
    icon: "shield",
    title: { en: "Security", ko: "보안" },
    items: [
      { en: "Use a read-only database user for every source.", ko: "모든 소스에 읽기 전용 데이터베이스 사용자를 사용하세요." },
      { en: "DataPond encrypts saved connector secrets and leaves them out of exports.", ko: "저장된 커넥터 비밀값은 DataPond가 암호화하며 export에는 포함되지 않습니다." },
      { en: "Enable SSL/TLS on database connections.", ko: "데이터베이스 연결에 SSL/TLS를 켜세요." },
      { en: "For S3, prefer the runtime credential chain (instance role) over long-lived keys.", ko: "S3는 장기 키보다 런타임 자격 증명 체인(인스턴스 역할)을 권장합니다." },
    ],
  },
  {
    icon: "activity",
    title: { en: "Performance", ko: "성능" },
    items: [
      { en: "Use Incremental or Merge for large tables with a stable timestamp or ID.", ko: "안정적인 타임스탬프나 ID가 있는 큰 테이블은 Incremental 또는 Merge를 쓰세요." },
      { en: "Run heavy first loads outside the source database's peak hours.", ko: "무거운 첫 적재는 소스 데이터베이스의 피크 시간을 피하세요." },
      { en: "Select only the tables you need.", ko: "필요한 테이블만 선택하세요." },
      { en: "Compare source and destination row counts after the first load.", ko: "첫 적재 뒤 소스와 대상의 행 수를 비교하세요." },
    ],
  },
]

const FAQ: { q: L; a: L }[] = [
  {
    q: { en: "Who can see or sync a source?", ko: "소스는 누가 보고 동기화할 수 있나요?" },
    a: {
      en: "Access to a source is its share list: the owner plus the members added as readers or editors. Readers can browse and query; editors can also change and sync it. The share list is also the grant list of the source's catalog, so Analytics honours it. Creating sources and syncing need a role such as admin or data_engineer.",
      ko: "소스 접근 권한은 공유 목록으로 정해집니다. 소유자와 reader 또는 editor로 추가된 멤버입니다. reader는 탐색과 조회, editor는 변경과 동기화도 할 수 있습니다. 공유 목록은 해당 소스 catalog의 grant와 같아서 Analytics에도 그대로 적용됩니다. 소스 생성과 동기화에는 admin, data_engineer 같은 역할이 필요합니다.",
    },
  },
  {
    q: { en: "Can I pause or cancel a running sync?", ko: "실행 중인 동기화를 일시 중지하거나 취소할 수 있나요?" },
    a: {
      en: "No. Check the run in the history, fix the cause if it failed, and run Sync Now again.",
      ko: "아니요. 이력에서 실행 결과를 확인하고, 실패했다면 원인을 고친 뒤 Sync Now를 다시 실행하세요.",
    },
  },
  {
    q: { en: "How do I see past syncs and errors?", ko: "이전 동기화와 오류는 어디서 보나요?" },
    a: {
      en: "Open the source. The sync history lists every run with its status, rows processed and the error text of failed runs.",
      ko: "소스를 열면 동기화 이력에 실행별 상태, 처리 행 수, 실패한 실행의 오류 메시지가 나옵니다.",
    },
  },
  {
    q: { en: "Can I keep the same table in two catalogs?", ko: "같은 테이블을 두 catalog에 둘 수 있나요?" },
    a: {
      en: "Sync into one catalog. To make the table visible in a second catalog without copying data, use Export from Catalog; the second catalog gets a read-only mirror (one writer per table).",
      ko: "한 catalog로 동기화하세요. 데이터 복사 없이 다른 catalog에서도 보이게 하려면 Catalog의 Export를 사용합니다. 두 번째 catalog에는 읽기 전용 mirror가 생깁니다(테이블당 writer는 하나).",
    },
  },
]

const TROUBLE: { title: L; body: L }[] = [
  {
    title: { en: "The engine is restarting", ko: "엔진이 재시작 중입니다" },
    body: {
      en: "After you add, edit or remove a database source, Trino restarts for about one minute. Queries, previews and syncs may fail during that time. Wait, then retry.",
      ko: "데이터베이스 소스를 추가, 수정, 삭제하면 Trino가 약 1분간 재시작합니다. 이 동안 쿼리, 미리보기, 동기화가 실패할 수 있습니다. 잠시 기다린 뒤 다시 시도하세요.",
    },
  },
  {
    title: { en: "Sync refused: column type changed", ko: "동기화 거부: 컬럼 타입 변경" },
    body: {
      en: "The source column's type is no longer compatible with the Iceberg table (only widening such as int to bigint is applied). Restore the type at the source, or sync into a new table name and switch readers over.",
      ko: "소스 컬럼 타입이 Iceberg 테이블과 더 이상 호환되지 않습니다(int → bigint 같은 확장만 적용됩니다). 소스의 타입을 되돌리거나, 새 테이블 이름으로 동기화한 뒤 읽는 쪽을 옮기세요.",
    },
  },
  {
    title: { en: "Connection test fails", ko: "연결 테스트가 실패합니다" },
    body: {
      en: "Check firewall and security-group rules between the cluster and the database, the credentials, and that the user has SELECT on the tables.",
      ko: "클러스터와 데이터베이스 사이의 방화벽·보안 그룹, 자격 증명, 그리고 사용자의 테이블 SELECT 권한을 확인하세요.",
    },
  },
  {
    title: { en: "Sync is slow or fails on a required column", ko: "동기화가 느리거나 필수 컬럼에서 실패합니다" },
    body: {
      en: "Switch large tables to Incremental and index the watermark column. For NULLs in required columns or mixed types in CSV/JSON files, clean the values at the source before retrying.",
      ko: "큰 테이블은 Incremental로 바꾸고 watermark 컬럼에 인덱스를 두세요. 필수 컬럼의 NULL이나 CSV/JSON의 혼합 타입은 소스에서 정리한 뒤 다시 시도하세요.",
    },
  },
  {
    title: { en: "Write to a table was refused (409)", ko: "테이블 쓰기가 거부되었습니다 (409)" },
    body: {
      en: "The target table is a mirror of a table owned by another catalog. The error names the owner; sync into the owner catalog instead.",
      ko: "대상 테이블이 다른 catalog가 소유한 테이블의 mirror입니다. 오류에 소유자가 표시되므로 소유자 catalog로 동기화하세요.",
    },
  },
]

const KIND_ICON = { db: Database, sample: Lightbulb, backend: HardDrive, stream: Radio }

export default function ConnectorsHelpPage() {
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
            <BreadcrumbPage>Sources</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="inline-flex p-3 rounded-lg bg-purple-500/10">
            <Plug className="h-8 w-8 text-purple-500" />
          </div>
          <div>
            <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-primary">Guide</p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight">Sources</h1>
            <p className="mt-2 text-muted-foreground">
              {t({
                en: "Connect databases and storage, query them live, and sync them into Iceberg",
                ko: "데이터베이스와 스토리지를 연결해 바로 조회하고, Iceberg로 동기화합니다",
              })}
            </p>
          </div>
        </div>
        <HelpLocaleToggle />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plug className="h-5 w-5" />
            {t({ en: "Quick Start", ko: "빠른 시작" })}
          </CardTitle>
          <CardDescription>
            {t({ en: "From a database to an Iceberg table in 5 steps", ko: "데이터베이스에서 Iceberg 테이블까지 5단계" })}
          </CardDescription>
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
                      <Link href="/connectors" className="text-primary hover:underline">
                        Sources
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
            {t({ en: "Kinds of sources", ko: "소스의 종류" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {KINDS.map((k) => {
            const Icon = KIND_ICON[k.icon]
            return (
              <div key={k.icon} className="flex items-start gap-3">
                <div className="inline-flex p-2 rounded-lg bg-primary/10 flex-shrink-0">
                  <Icon className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold">{t(k.title)}</h3>
                  <p className="text-sm text-muted-foreground">{t(k.body)}</p>
                  {k.badges && (
                    <div className="flex gap-2 mt-2 flex-wrap">
                      {k.badges.map((b, i) => (
                        <Badge key={i} variant="secondary">{t(b)}</Badge>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings className="h-5 w-5" />
            {t({ en: "Sync modes and options", ko: "동기화 모드와 옵션" })}
          </CardTitle>
          <CardDescription>
            {t({ en: "Set per table when you sync", ko: "동기화할 때 테이블별로 설정합니다" })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            {MODES.map((m) => (
              <div key={m.name} className="rounded-lg border p-3 space-y-1">
                <Badge variant="outline">{m.name}</Badge>
                <p className="text-sm text-muted-foreground">{t(m.body)}</p>
              </div>
            ))}
          </div>
          <pre className="bg-muted p-3 rounded-lg text-xs">
            <code>{"src_<slug>.public.orders  →  Full / Incremental / Merge  →  <target catalog>.<schema>.orders (Iceberg)"}</code>
          </pre>
          {SYNC_DETAILS.map((d, i) => (
            <div key={i} className="space-y-1">
              <h3 className="font-semibold">{t(d.title)}</h3>
              <p className="text-sm text-muted-foreground">{t(d.body)}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            {t({ en: "Access and schedules", ko: "접근 권한과 스케줄" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <h3 className="font-semibold">{t({ en: "Share list", ko: "공유 목록" })}</h3>
            <p className="text-sm text-muted-foreground">
              {t({
                en: "A source has an owner, readers and editors. That list decides who can browse, query and sync it, and it is the same as the grants on the source's catalog. Change it from the source's share dialog.",
                ko: "소스에는 소유자, reader, editor가 있습니다. 이 목록이 탐색, 조회, 동기화 권한을 정하며 소스 catalog의 grant와 같습니다. 소스의 공유 대화상자에서 바꿀 수 있습니다.",
              })}
            </p>
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <CalendarClock className="h-4 w-4 text-muted-foreground" />
              <h3 className="font-semibold">{t({ en: "Schedules", ko: "스케줄" })}</h3>
            </div>
            <p className="text-sm text-muted-foreground">
              {t({
                en: "Recurring syncs need the Airflow add-on, so scheduling controls appear only when Airflow is enabled. Without it, run Sync Now when you need fresh data.",
                ko: "정기 동기화에는 Airflow add-on이 필요하므로 스케줄 설정은 Airflow가 켜져 있을 때만 보입니다. 없으면 필요할 때 Sync Now를 실행하세요.",
              })}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            {t({ en: "Best practices", ko: "권장 사항" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {PRACTICES.map((p, i) => {
            const Icon = p.icon === "shield" ? Shield : Activity
            return (
              <div key={i} className="space-y-2">
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-semibold">{t(p.title)}</h3>
                </div>
                <ul className="text-sm text-muted-foreground space-y-1 ml-6 list-disc">
                  {p.items.map((it, j) => (
                    <li key={j}>{t(it)}</li>
                  ))}
                </ul>
              </div>
            )
          })}
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
          <p className="text-sm text-muted-foreground">
            {t({ en: "Work with your synced data:", ko: "동기화한 데이터를 활용해 보세요." })}
          </p>
          <div className="flex gap-2 flex-wrap">
            <Link href="/help/catalog">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                {t({ en: "Catalog Guide", ko: "Catalog 가이드" })}
              </Badge>
            </Link>
            <Link href="/help/sql-lab">
              <Badge variant="outline" className="cursor-pointer hover:bg-background">
                {t({ en: "Analytics Guide", ko: "Analytics 가이드" })}
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
