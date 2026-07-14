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
    summary: "DataPond는 AWS 위에서 프로덕션 RAG·에이전트 앱을 구동하는 AI 데이터 파운데이션입니다 — S3 + Aurora(pgvector) + Bedrock을 네이티브로 묶고 거버넌스를 내장했습니다.",
    points: [
      "거버넌스 완비형 RAG 파이프라인: S3 → 임베딩 → pgvector → Bedrock 인용답변",
      "AWS 매니지드 코어: 스토리지=S3, 벡터/DB=Aurora Serverless v2(pgvector), 모델=Bedrock(LiteLLM 경유)",
      "차별화: 오픈소스 거버넌스 내장 — RLS·컬럼 마스킹·PII 가드레일·비용/spend 거버넌스",
    ],
    related: [{ label: "대시보드 열기", href: "/dashboard" }, { label: "아키텍처", href: "/docs/architecture" }],
  },
  quickstart: {
    title: "Quick Start Guide",
    summary: "로그인 → Knowledge에 데이터 적재(텍스트·카탈로그·S3) → 임베딩 → RAG/AI SQL로 질의.",
    points: [
      "Knowledge에서 컬렉션 생성 후 텍스트·Iceberg 카탈로그·S3 객체를 적재 → Titan 임베딩(pgvector)",
      "AI에서 자연어로 질문 → Bedrock 인용답변(RAG), 또는 자연어→SQL",
      "Connectors·Catalog·SQL Lab은 파운데이션 프로파일에는 없으며, 분석 엔진(Athena/EMR 등)을 켜면 사용 가능",
    ],
    related: [{ label: "Knowledge", href: "/knowledge" }, { label: "Governance", href: "/governance" }, { label: "Settings", href: "/settings" }],
  },
  architecture: {
    title: "Architecture",
    summary: "파운데이션 프로파일: Frontend/Backend/LiteLLM/Valkey(인클러스터) + S3·Aurora(pgvector)·Bedrock(AWS 매니지드). 약 5개 워크로드.",
    points: [
      "코어 RAG 경로: Backend → LiteLLM → Bedrock(임베딩·생성), 벡터=Aurora Serverless v2(pgvector)",
      "스토리지=Amazon S3(인클러스터 MinIO 없음), 캐시/세션=Valkey",
      "무거운 분석(Trino/Spark/Polaris/Airflow/OpenMetadata)은 노드에서 구동하지 않고 AWS 매니지드(Athena/EMR/Glue/MWAA/DataZone)로 대체",
    ],
    related: [{ label: "System 사양/리소스", href: "/system" }, { label: "Services", href: "/services" }],
  },
  concepts: {
    title: "Key Concepts",
    summary: "AI 데이터 파운데이션의 핵심 개념: 벡터스토어·RAG·거버넌스·LLM 게이트웨이·AWS 매니지드 분석.",
    points: [
      "pgvector = 벡터 DB(Aurora), RAG = 검색증강 인용답변, 임베딩=Bedrock Titan",
      "LiteLLM = LLM 단일 게이트웨이(Bedrock 라우팅·폴백·비용 귀속)",
      "거버넌스 = RLS·컬럼 마스킹·PII 가드레일 / 무거운 분석은 AWS 매니지드(Athena·EMR·Glue)로 위임",
    ],
  },
  "trino-sql": {
    title: "SQL Analytics (Athena / Trino)",
    summary: "파운데이션 프로파일에서 분산 SQL 분석은 Amazon Athena(매니지드)로 제공됩니다. OSS Trino는 풀 프로파일에서 활성화 시 SQL Lab(/query)로 사용.",
    points: [
      "AWS: Athena가 S3 데이터를 서버리스 SQL로 조회(Glue Data Catalog 연동)",
      "Trino 활성 시: 완전수식 테이블명 iceberg.<schema>.<table>, 식별자는 큰따옴표",
      "AI SQL Assistant로 자연어→SQL 생성",
    ],
    related: [{ label: "SQL Lab", href: "/query" }],
  },
  duckdb: {
    title: "Notebooks (SageMaker Studio / DuckDB)",
    summary: "파운데이션 프로파일에서 노트북 탐색은 Amazon SageMaker Studio로 제공됩니다. 임베디드 DuckDB는 Jupyter가 활성화된 풀 프로파일에서 사용 가능(파운데이션에는 없음).",
    points: ["AWS: SageMaker Studio에서 boto3/PyIceberg로 S3 직접 접근", "Jupyter 활성 시: 내장 DuckDB로 소규모 탐색 쿼리"],
    related: [{ label: "Notebooks", href: "/notebooks" }],
  },
  pipelines: {
    title: "Pipeline Development (MWAA / EMR)",
    summary: "파운데이션 프로파일에서 배치/ELT 오케스트레이션은 Amazon MWAA(Airflow)와 EMR Serverless/Glue ETL로 제공됩니다. OSS Airflow는 풀 프로파일 활성화 시 Pipelines(/pipelines)에서 관리.",
    points: ["AWS: MWAA로 DAG 오케스트레이션, EMR Serverless/Glue로 변환", "Airflow 활성 시: ELT Transform(SQL→CTAS DAG), 증분 sync·스키마 진화"],
    related: [{ label: "Pipelines", href: "/pipelines" }, { label: "Jobs", href: "/jobs" }],
  },
  streaming: {
    title: "Streaming (MSK / Managed Flink)",
    summary: "파운데이션 프로파일에서 스트리밍은 Amazon MSK / Managed Service for Apache Flink로 제공됩니다. OSS RisingWave는 풀 프로파일 활성화 시 Streaming(/streaming)에서 사용.",
    points: ["AWS: MSK(Kafka) + Managed Flink로 스트림 처리 후 S3 싱크", "RisingWave 활성 시: PostgreSQL 호환 SQL·postgres-CDC 마법사"],
    related: [{ label: "Streaming", href: "/streaming" }],
  },
  polaris: {
    title: "Data Catalog (Glue / Polaris)",
    summary: "파운데이션 프로파일에서 테이블 카탈로그는 AWS Glue Data Catalog로 제공됩니다. OSS Apache Polaris(Iceberg REST 카탈로그)는 풀 프로파일 활성화 시 사용.",
    points: ["AWS: Glue Data Catalog가 Athena/EMR/Spark의 공용 메타스토어", "Polaris 활성 시: 중앙 Iceberg REST 카탈로그, 카탈로그 단위 RBAC·크로스엔진 공유"],
    related: [{ label: "Catalog", href: "/catalog" }],
  },
  storage: {
    title: "Storage (AWS S3)",
    summary: "소스 데이터와 오브젝트 스토리지는 Amazon S3(네이티브)로 제공됩니다. 노드 인스턴스 프로파일로 인증하며 인클러스터 MinIO/SeaweedFS는 없습니다.",
    points: ["S3 = 소스 데이터 + 벡터 적재 원본, 노드 인스턴스 프로파일로 접근", "Storage(/storage)에서 사용량 확인. 자체호스팅 풀 프로파일은 MinIO를 S3 호환 스토어로 사용"],
    related: [{ label: "Storage", href: "/storage" }],
  },
  optimization: {
    title: "Query & Table Optimization",
    summary: "파운데이션 프로파일에서 테이블 유지보수·쿼리 튜닝은 AWS 매니지드 분석(Athena/EMR/Glue)에서 수행됩니다. OSS Iceberg 유지보수는 엔진 활성 시 유지보수 DAG로 처리.",
    points: ["AWS: Glue/EMR 컴팩션·파티셔닝·통계로 스캔 절감", "OSS 활성 시: 유지보수 DAG가 파일 컴팩션·스냅샷/오펀 정리 수행"],
    related: [{ label: "Pipelines", href: "/pipelines" }],
  },
  monitoring: {
    title: "Monitoring & Observability",
    summary: "Services/System 페이지의 상태·리소스, LiteLLM /metrics·spend, (옵션) OpenMetadata/DataZone 리니지.",
    points: ["Services: Pod health·로그", "System: 사양/리소스/노드", "AI: 토큰·비용·사용자별 spend"],
    related: [{ label: "Services", href: "/services" }, { label: "System", href: "/system" }],
  },
  lineage: {
    title: "Data Lineage (DataZone / OpenMetadata)",
    summary: "파운데이션 프로파일에서 리니지·카탈로깅은 Amazon DataZone(매니지드)으로 제공됩니다. OSS OpenMetadata는 옵션으로 활성화(--set openmetadata.enabled=true) 시 sync에 리니지 엣지를 자동 등록.",
    points: ["AWS: DataZone이 테이블·소스 카탈로깅과 리니지 제공", "OpenMetadata 활성 시: 소스→타깃 upstream 엣지 자동 등록"],
    related: [{ label: "Catalog", href: "/catalog" }],
  },
  rbac: {
    title: "RBAC & Row-Level Security",
    summary: "역할 기반 접근제어 + RLS 엔진(행 필터·컬럼 마스킹), 벡터 컬렉션 RLS.",
    points: ["정책 관리 + PII 마스킹, 분석 엔진 활성 시 Trino 네이티브 RLS·DuckDB 가드 적용", "Knowledge 컬렉션: owner/admin/공용"],
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
    summary: "로컬 계정(JWT) + Passkey/WebAuthn + LDAP/AD(환경설정, 기본 OFF). 로컬 admin은 항상 동작.",
    points: ["Passkey/WebAuthn 등록·로그인 지원", "auth_method=ldap 시 자동 프로비저닝", "SSO(OIDC)는 엔터프라이즈 이미지에서 제공"],
    related: [{ label: "Users 설정", href: "/settings" }],
  },
  configuration: {
    title: "Configuration",
    summary: "시스템 설정은 Settings에서, 인프라는 Helm values(foundation/prod-single + AWS)로 관리.",
    points: ["AI: Settings→AI(게이트웨이·모델·비용·키)", "암호화 저장(CredentialVault) + startup 복원", "프로파일: values-foundation.yaml(린 RAG) / values-prod-single.yaml(단일노드)"],
    related: [{ label: "Settings", href: "/settings" }],
  },
  installation: {
    title: "Installation",
    summary: "AWS 위 단일노드 K3s(EC2 + Aurora + S3 + Bedrock)에 파운데이션 프로파일로 배포합니다.",
    points: ["프로파일: values-foundation.yaml / values-prod-single.yaml", "AWS 매니지드: Aurora(pgvector)·S3·Bedrock, 인스턴스 프로파일/IRSA 인증", "가이드: docs/DEPLOY_SINGLE_NODE.md"],
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
    summary: "REST API를 파이썬에서 호출하거나, 노트북(SageMaker Studio/Jupyter)에서 boto3로 S3에 직접 접근합니다.",
    points: ["boto3로 Amazon S3 직접 접근, AI/RAG는 /api/ai/* 호출", "OSS 엔진 활성 시: PyIceberg·DuckDB로 Iceberg 카탈로그(Glue/Polaris) 접근"],
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
