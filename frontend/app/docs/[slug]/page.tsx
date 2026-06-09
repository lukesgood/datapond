"use client"

import { useParams } from "next/navigation"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { ArrowLeft, BookOpen, ExternalLink, ArrowRight } from "lucide-react"

type Related = { label: string; href: string }
type Doc = { title: string; summary: string; points: string[]; related?: Related[] }

// In-app documentation. Concise, accurate to the current platform; deep-links to the
// live feature and to the full guide in the repo (docs/*.md).
const DOCS: Record<string, Doc> = {
  overview: {
    title: "Platform Overview",
    summary: "DataPond는 자체 인프라(온프렘·에어갭) 위에서 데이터→쿼리→AI/RAG 전 경로를 운영하는 주권형 AI-Native 레이크하우스입니다.",
    points: [
      "Iceberg(ACID) + Polaris(통합 카탈로그) + 멀티엔진(Trino·Spark·RisingWave·DuckDB)",
      "AI 1급 설계: LiteLLM 게이트웨이로 자연어 SQL·RAG·임베딩 일원화",
      "주권: egress 정책(local-only=무유출)·PII 가드레일·RLS·비용 거버넌스 내장",
    ],
    related: [{ label: "대시보드 열기", href: "/dashboard" }, { label: "아키텍처", href: "/docs/architecture" }],
  },
  quickstart: {
    title: "Quick Start Guide",
    summary: "로그인 → 커넥터로 데이터 적재 → Catalog 확인 → SQL Lab/Knowledge에서 분석·RAG.",
    points: [
      "Ingestion(Connectors)에서 소스 연결·동기화 → Iceberg 테이블 생성",
      "Catalog에서 테이블·미리보기 확인, SQL Lab에서 쿼리",
      "Knowledge에서 테이블을 임베딩해 RAG, 또는 Catalog의 'Send to Knowledge'",
    ],
    related: [{ label: "커넥터 설정", href: "/connectors" }, { label: "SQL Lab", href: "/query" }, { label: "Knowledge", href: "/knowledge" }],
  },
  architecture: {
    title: "Architecture",
    summary: "Application(Frontend/Backend/Jupyter/Airflow/MLflow) · Compute(Trino/Spark/RisingWave) · Catalog(Polaris) · Storage(SeaweedFS+Iceberg) · AI(LiteLLM).",
    points: [
      "Polaris REST 카탈로그를 중심으로 모든 엔진이 같은 Iceberg 테이블 공유",
      "PostgreSQL(메타+pgvector) · Valkey(캐시) · OpenMetadata(리니지)",
      "모든 Deployment는 strategy: Recreate (단일노드 메모리 보호)",
    ],
    related: [{ label: "System 사양/리소스", href: "/system" }, { label: "Services", href: "/services" }],
  },
  concepts: {
    title: "Key Concepts",
    summary: "레이크하우스·카탈로그·멀티엔진·벡터스토어·게이트웨이의 핵심 개념.",
    points: [
      "Iceberg = ACID 테이블 포맷(스키마 진화·타임트래블)",
      "Polaris = 카탈로그/거버넌스(Unity Catalog 대체)",
      "pgvector = 벡터 DB, LiteLLM = LLM 단일 게이트웨이",
    ],
  },
  "trino-sql": {
    title: "Trino SQL Reference",
    summary: "Trino 분산 SQL로 Iceberg 테이블을 조회합니다. SQL Lab(/query)에서 실행.",
    points: [
      "정규화 식별자: 큰따옴표(\"col\"), 백틱 금지",
      "완전수식 테이블명: iceberg.<schema>.<table>",
      "AI SQL Assistant로 자연어→SQL 생성 가능",
    ],
    related: [{ label: "SQL Lab", href: "/query" }],
  },
  duckdb: {
    title: "DuckDB (Notebooks)",
    summary: "JupyterLab 내장 DuckDB로 ~100GB 이하 탐색 쿼리를 Spark 없이 Iceberg에서 직접 S3로 읽습니다.",
    points: ["노트북에서 iceberg_helper로 DuckDB↔Iceberg 연결", "탐색·프로토타이핑에 적합"],
    related: [{ label: "Notebooks", href: "/notebooks" }],
  },
  pipelines: {
    title: "Pipeline Development",
    summary: "Airflow로 배치/ELT를 오케스트레이션하고, Pipelines(/pipelines)에서 DAG를 관리합니다.",
    points: ["ELT Transform: SQL 에디터 + source/target namespace → CTAS DAG 생성", "증분 sync(watermark) + 스키마 진화"],
    related: [{ label: "Pipelines", href: "/pipelines" }, { label: "Jobs", href: "/jobs" }],
  },
  streaming: {
    title: "Streaming (RisingWave)",
    summary: "RisingWave가 PostgreSQL 호환 SQL로 스트림을 처리하고 Iceberg로 싱크합니다(Kafka+Spark Streaming 대체).",
    points: ["Streaming 탭 4단계 마법사로 postgres-CDC 구성", "Polaris 경유 Iceberg 싱크"],
    related: [{ label: "Streaming", href: "/streaming" }],
  },
  polaris: {
    title: "Apache Polaris Catalog",
    summary: "모든 컴퓨트 엔진이 REST로 연결하는 중앙 Iceberg 카탈로그(거버넌스 게이트).",
    points: ["메타데이터=PostgreSQL, 데이터=SeaweedFS(S3)", "카탈로그 단위 RBAC, 크로스엔진 테이블 공유"],
    related: [{ label: "Catalog", href: "/catalog" }],
  },
  storage: {
    title: "Storage (SeaweedFS + Iceberg)",
    summary: "SeaweedFS가 S3 호환 오브젝트 스토리지를 제공하고 Iceberg가 ACID 테이블 포맷을 얹습니다.",
    points: ["master/volume/filer는 /data PVC에 영속", "Storage(/storage)에서 사용량 확인"],
    related: [{ label: "Storage", href: "/storage" }],
  },
  optimization: {
    title: "Query & Table Optimization",
    summary: "Iceberg 유지보수(파일 컴팩션·스냅샷/오펀 정리)와 쿼리 튜닝.",
    points: ["유지보수 DAG가 file-size/스냅샷 보존/오펀 정리 수행", "파티셔닝·통계로 Trino 스캔 절감"],
    related: [{ label: "Pipelines", href: "/pipelines" }],
  },
  monitoring: {
    title: "Monitoring & Observability",
    summary: "Services/System 페이지의 상태·리소스, OpenMetadata 리니지, LiteLLM /metrics·spend.",
    points: ["Services: Pod health·로그", "System: 사양/리소스/노드", "AI: 토큰·비용·사용자별 spend"],
    related: [{ label: "Services", href: "/services" }, { label: "System", href: "/system" }],
  },
  lineage: {
    title: "Data Lineage (OpenMetadata)",
    summary: "sync 시 OpenMetadata에 테이블·소스·리니지 엣지를 자동 등록합니다.",
    points: ["FQN: datapond-trino.iceberg.<schema>.<table>", "소스→타깃 upstream 엣지 자동"],
    related: [{ label: "Catalog", href: "/catalog" }],
  },
  rbac: {
    title: "RBAC & Row-Level Security",
    summary: "역할 기반 접근제어 + RLS 엔진(행 필터·컬럼 마스킹), 벡터 컬렉션 RLS.",
    points: ["정책 관리·Trino 네이티브 RLS·DuckDB 가드", "Knowledge 컬렉션: owner/admin/공용"],
    related: [{ label: "Governance", href: "/governance" }, { label: "Settings", href: "/settings" }],
  },
  audit: {
    title: "Audit Logging",
    summary: "인증·정책 변경 등 보안 이벤트 감사 로그(auth_audit_log) + LiteLLM spend_logs.",
    points: ["RLS 정책 생성/변경 감사", "AI 호출 사용자별 비용·토큰 기록"],
    related: [{ label: "Governance", href: "/governance" }],
  },
  authentication: {
    title: "Authentication",
    summary: "로컬 계정(JWT) + LDAP/AD(환경설정, 기본 OFF). 로컬 admin은 항상 동작.",
    points: ["auth_method=ldap 시 자동 프로비저닝", "SSO(SAML/OIDC)는 로드맵"],
    related: [{ label: "Users 설정", href: "/settings" }],
  },
  configuration: {
    title: "Configuration",
    summary: "시스템 설정은 Settings에서, 인프라는 Helm values(quicktest/onprem/aws)로 관리.",
    points: ["AI: Settings→AI(게이트웨이·모델·비용·키)", "암호화 저장(CredentialVault) + startup 복원"],
    related: [{ label: "Settings", href: "/settings" }],
  },
  installation: {
    title: "Installation",
    summary: "K3s+Helm 부트스트랩(scripts/install.sh) 또는 에어갭 번들(bundle-airgap.sh).",
    points: ["프로파일: values-quicktest/onprem/aws", "에어갭: 오프라인 번들로 K3s·Helm·이미지 적재"],
    related: [{ label: "System", href: "/system" }],
  },
  api: {
    title: "REST API",
    summary: "FastAPI 백엔드. 대화형 스펙은 Swagger UI에서 확인.",
    points: ["/api/* — connectors·catalog·queries·ai·settings 등", "AI: /api/ai/{sql,embed,collections,search,rag}"],
    related: [{ label: "API Docs (Swagger)", href: "/api/docs" }],
  },
  "python-sdk": {
    title: "Python SDK / Notebooks",
    summary: "JupyterLab에서 DuckDB·PyIceberg·boto3로 Iceberg/S3에 직접 접근합니다.",
    points: ["iceberg_helper: connect_duckdb_iceberg, q()", "S3=SeaweedFS, 카탈로그=Polaris"],
    related: [{ label: "Notebooks", href: "/notebooks" }],
  },
  troubleshooting: {
    title: "Troubleshooting",
    summary: "일반적 장애 모드와 해결 (Pod 상태, 카탈로그, 스토리지, AI 게이트웨이).",
    points: ["Services/System에서 Pod·리소스 확인", "AI 미동작 시 Settings→AI 게이트웨이/모델 점검"],
    related: [{ label: "Services", href: "/services" }],
  },
}

function humanize(slug: string) {
  return slug.replace(/-/g, " ").replace(/\b\w/g, c => c.toUpperCase())
}

export default function DocArticlePage() {
  const params = useParams()
  const slug = String(params?.slug || "")
  const doc = DOCS[slug]

  return (
    <div className="flex-1 space-y-5 p-8 pt-6 max-w-3xl">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/docs">Docs</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>{doc?.title || humanize(slug)}</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-center gap-2">
        <BookOpen className="h-5 w-5 text-primary" />
        <h1 className="text-2xl font-semibold">{doc?.title || humanize(slug)}</h1>
      </div>

      {doc ? (
        <Card>
          <CardContent className="py-5 space-y-4">
            <p className="text-sm text-muted-foreground">{doc.summary}</p>
            <ul className="list-disc pl-5 space-y-1 text-sm">
              {doc.points.map((p, i) => <li key={i}>{p}</li>)}
            </ul>
            {doc.related && doc.related.length > 0 && (
              <div className="pt-2 flex flex-wrap gap-2">
                {doc.related.map((r, i) => (
                  <Button key={i} size="sm" variant="outline" className="gap-1.5" render={<Link href={r.href} />}>{r.label}<ArrowRight className="h-3.5 w-3.5" /></Button>
                ))}
              </div>
            )}
            <p className="text-[11px] text-muted-foreground pt-2 flex items-center gap-1">
              <ExternalLink className="h-3 w-3" /> 전체 가이드는 저장소 <span className="font-mono">docs/</span> 를 참고하세요.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="py-8 text-center space-y-3">
            <p className="text-sm text-muted-foreground">이 문서(<span className="font-mono">{slug}</span>)는 아직 준비 중입니다.</p>
            <Button size="sm" variant="outline" render={<Link href="/docs" />}><ArrowLeft className="h-3.5 w-3.5 mr-1.5" />문서 홈</Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
