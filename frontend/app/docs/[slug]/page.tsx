"use client"

import { useParams } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, ArrowRight, BookOpen, ExternalLink } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useCapabilities } from "@/lib/capabilities"
import { HelpLocaleToggle, useHelpLocale } from "@/components/help/locale"
import type { L } from "@/lib/help-locale"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"

type Status = "Shipped" | "Optional" | "Reference" | "Roadmap"
type Related = { label: L; href: string; capability?: string }
type Doc = { title: L; status: Status; summary: L; points: L[]; related?: Related[] }

const STATUS_LABEL: Record<Status, L> = {
  Shipped: { en: "Shipped", ko: "제공 중" },
  Optional: { en: "Optional", ko: "선택 사항" },
  Reference: { en: "Reference", ko: "참조" },
  Roadmap: { en: "Roadmap", ko: "로드맵" },
}

const ARTICLES: Record<string, Doc> = {
  overview: {
    title: { en: "Platform Overview", ko: "플랫폼 개요" },
    status: "Shipped",
    summary: {
      en: "DataPond is a lightweight, open lakehouse for small and mid-size teams on AWS. Data lives in S3-API storage as Apache Iceberg, tables are registered in an Iceberg catalog (Glue or Polaris), and one SQL engine, Trino, queries them. Governance sits at the data layer, and AI features run on the same data.",
      ko: "DataPond는 AWS를 쓰는 중소 규모 팀을 위한 가벼운 오픈 레이크하우스입니다. 데이터는 S3 API 스토리지에 Apache Iceberg로 저장하고, 테이블은 Iceberg 카탈로그(Glue 또는 Polaris)에 등록하며, SQL 엔진은 Trino 하나로 통일합니다. 거버넌스는 데이터 계층에서 적용하고, AI 기능은 같은 데이터 위에서 동작합니다.",
    },
    points: [
      { en: "Lakehouse: Sources (databases, S3, APIs) sync into Iceberg; Catalog, Analytics and Metrics read them; Trino can also join live source databases with the lake.", ko: "레이크하우스: Sources(데이터베이스, S3, API)가 Iceberg로 동기화되고, Catalog·Analytics·Metrics가 이를 읽습니다. Trino는 운영 중인 소스 DB와 레이크를 한 쿼리에서 조인할 수도 있습니다." },
      { en: "Governance: catalog grants, row filters, column masks, Korean PII masking and an audit trail apply on the SQL path.", ko: "거버넌스: 카탈로그 권한, 행 필터, 컬럼 마스크, 한국형 PII 마스킹, 감사 기록이 SQL 경로에 적용됩니다." },
      { en: "AI layer: Knowledge/RAG with citations, natural-language SQL, approved Metrics, a read-only MCP endpoint, service-account keys and per-caller spend. It also runs alone on the Core profiles, which have no catalog or engine.", ko: "AI 계층: 인용이 붙는 Knowledge/RAG, 자연어 SQL, 승인된 Metrics, 읽기 전용 MCP 엔드포인트, 서비스 계정 키, 호출자별 비용 집계를 제공합니다. 카탈로그와 엔진이 없는 Core 프로파일에서는 AI 계층만 단독으로 실행할 수도 있습니다." },
      { en: "Open standards at every layer (S3 API, Iceberg, Iceberg REST/Glue, Trino, PostgreSQL, OpenAI-compatible models, Helm) keep storage, catalog, engine and models replaceable.", ko: "모든 계층이 개방형 표준(S3 API, Iceberg, Iceberg REST/Glue, Trino, PostgreSQL, OpenAI 호환 모델, Helm)이어서 스토리지, 카탈로그, 엔진, 모델을 교체할 수 있습니다." },
    ],
    related: [{ label: { en: "Core workflow", ko: "핵심 워크플로" }, href: "/docs/core-workflow" }, { label: { en: "Profile matrix", ko: "프로파일 비교" }, href: "/docs/profiles" }],
  },
  quickstart: {
    title: { en: "Quick Start", ko: "빠른 시작" },
    status: "Shipped",
    summary: {
      en: "With a query engine, the first path is: connect a source, sync it, query it. Profiles without a catalog and engine start from Knowledge instead.",
      ko: "쿼리 엔진이 있는 배포에서는 소스를 연결하고, 동기화한 뒤, 조회하는 순서로 시작합니다. 카탈로그와 엔진이 없는 프로파일은 Knowledge에서 시작합니다.",
    },
    points: [
      { en: "Open Sources and connect a database, or add the sample data. Adding a database source registers a Trino catalog and restarts the engine for about a minute.", ko: "Sources에서 데이터베이스를 연결하거나 샘플 데이터를 추가합니다. 데이터베이스 소스를 추가하면 Trino 카탈로그가 등록되고 엔진이 1분 정도 재시작됩니다." },
      { en: "Sync a table into Iceberg. Pick the sync mode and the Target catalog; PII is masked inside the sync.", ko: "테이블을 Iceberg로 동기화합니다. 동기화 방식과 Target catalog를 고르면, PII는 동기화 중에 마스킹됩니다." },
      { en: "Open Analytics and query the table by its three-part name, catalog.schema.table. Chart the result or save it to a dashboard.", ko: "Analytics에서 catalog.schema.table 형식의 세 부분 이름으로 테이블을 조회합니다. 결과는 차트로 만들거나 대시보드에 저장할 수 있습니다." },
      { en: "Then set grants in Governance, define a Metric, and add AI: Knowledge, or an agent through MCP.", ko: "그다음 Governance에서 권한을 설정하고, Metric을 정의하고, Knowledge나 MCP로 연결한 에이전트 같은 AI를 더합니다." },
      { en: "AI-only profile (no engine): create a Knowledge collection, ingest text or S3 objects, test semantic search, then ask a cited question.", ko: "AI 전용 프로파일(엔진 없음): Knowledge 컬렉션을 만들어 텍스트나 S3 객체를 수집하고, 의미 검색을 확인한 뒤 인용이 붙는 질문을 해봅니다." },
    ],
    related: [{ label: { en: "Sources", ko: "Sources" }, href: "/connectors", capability: "connectors" }, { label: { en: "Analytics", ko: "Analytics" }, href: "/query", capability: "query" }, { label: { en: "Knowledge", ko: "Knowledge" }, href: "/knowledge" }],
  },
  "core-workflow": {
    title: { en: "Core Workflow", ko: "핵심 워크플로" },
    status: "Shipped",
    summary: {
      en: "With a query engine the journey is Connect → Organize → Query → Govern → Add AI. Without one it is Connect → Organize → Ground → Connect your agent → Govern. The Dashboard shows the one that matches this deployment.",
      ko: "쿼리 엔진이 있으면 Connect → Organize → Query → Govern → Add AI 순서로 진행합니다. 엔진이 없으면 Connect → Organize → Ground → Connect your agent → Govern 순서입니다. 대시보드에는 이 배포에 맞는 순서가 표시됩니다.",
    },
    points: [
      { en: "Connect: add a source. Databases become Trino catalogs (src_<slug>); REST, custom Python and S3 sources are read by the backend.", ko: "Connect: 소스를 추가합니다. 데이터베이스는 Trino 카탈로그(src_<slug>)가 되고, REST·커스텀 Python·S3 소스는 백엔드가 읽습니다." },
      { en: "Organize: sync tables into Iceberg and browse them in Catalog.", ko: "Organize: 테이블을 Iceberg로 동기화하고 Catalog에서 살펴봅니다." },
      { en: "Query: Analytics runs Trino SQL, and Metrics turns approved definitions into cited numbers.", ko: "Query: Analytics에서 Trino SQL을 실행하고, Metrics는 승인된 정의를 출처가 있는 수치로 바꿔 줍니다." },
      { en: "Govern: catalog grants, row filters, column masks, PII masking and audit.", ko: "Govern: 카탈로그 권한, 행 필터, 컬럼 마스크, PII 마스킹, 감사를 설정합니다." },
      { en: "Add AI: Knowledge collections, natural-language SQL, and agents through MCP or REST. Without an engine, Ground means chunk, mask, embed and cite.", ko: "Add AI: Knowledge 컬렉션, 자연어 SQL, MCP나 REST로 연결하는 에이전트를 붙입니다. 엔진이 없을 때의 Ground는 청크 분할, 마스킹, 임베딩, 인용 단계를 뜻합니다." },
    ],
    related: [{ label: { en: "Sources", ko: "Sources" }, href: "/docs/sources" }, { label: { en: "Governance", ko: "Governance" }, href: "/docs/governance" }, { label: { en: "Knowledge", ko: "Knowledge" }, href: "/knowledge" }],
  },
  architecture: {
    title: { en: "Architecture", ko: "아키텍처" },
    status: "Shipped",
    summary: {
      en: "Data sits in S3-API storage as Iceberg, an Iceberg catalog registers the tables, Trino queries them, and the FastAPI backend and Next.js console apply governance and serve the AI features. Optional OSS add-ons stay separate from this path.",
      ko: "데이터는 S3 API 스토리지에 Iceberg로 저장되고, Iceberg 카탈로그가 테이블을 등록하며, Trino가 이를 조회합니다. FastAPI 백엔드와 Next.js 콘솔이 거버넌스를 적용하고 AI 기능을 제공합니다. 선택형 OSS 애드온은 이 경로와 분리되어 있습니다.",
    },
    points: [
      { en: "Core workloads: backend, frontend, PostgreSQL + pgvector (in-cluster or Aurora), LiteLLM and Valkey.", ko: "핵심 워크로드: 백엔드, 프론트엔드, PostgreSQL + pgvector(클러스터 내부 또는 Aurora), LiteLLM, Valkey." },
      { en: "Lakehouse path: Trino over the Glue catalog, over Polaris, or over both side by side. Source databases join as Trino catalogs.", ko: "레이크하우스 경로: Glue 카탈로그, Polaris, 또는 둘을 나란히 둔 구성 위에서 Trino가 동작합니다. 소스 데이터베이스는 Trino 카탈로그로 합류합니다." },
      { en: "Trino runs in the cluster on every profile that has a catalog; trino.workers.replicas adds workers. Athena was removed in 2.4.", ko: "카탈로그가 있는 모든 프로파일에서 Trino는 클러스터 안에서 실행되며, trino.workers.replicas로 워커를 추가합니다. Athena는 2.4에서 제거되었습니다." },
      { en: "A disabled add-on is simply absent. Helm does not provision an AWS service to replace it.", ko: "비활성화한 애드온은 그냥 없는 상태입니다. Helm이 이를 대체하는 AWS 서비스를 만들어 주지는 않습니다." },
    ],
    related: [{ label: { en: "Open contracts", ko: "개방형 계약" }, href: "/docs/open-contracts" }, { label: { en: "Services", ko: "Services" }, href: "/services" }],
  },
  profiles: {
    title: { en: "Deployment Profile Matrix", ko: "배포 프로파일 비교" },
    status: "Shipped",
    summary: {
      en: "A profile is a Helm values file that sets operating intent and enabled adapters. Runtime capability flags, not profile names, decide which modules the console shows.",
      ko: "프로파일은 운영 방향과 활성 어댑터를 정하는 Helm values 파일입니다. 콘솔에 어떤 모듈이 보이는지는 프로파일 이름이 아니라 런타임 capability 값이 결정합니다.",
    },
    points: [
      { en: "AWS Single-Node Reference (values-prod-single.yaml): EC2/K3s with Aurora, S3, Glue and Bedrock, and Trino in the cluster. Polaris can run beside Glue. Not EKS and not application-node HA.", ko: "AWS Single-Node Reference(values-prod-single.yaml): EC2/K3s에 Aurora, S3, Glue, Bedrock을 연결하고 Trino를 클러스터 안에서 실행합니다. Polaris를 Glue 옆에 둘 수 있습니다. EKS가 아니며 애플리케이션 노드 이중화도 아닙니다." },
      { en: "Sovereign OSS Extended (values-onprem.yaml): MinIO, Polaris and Trino plus selected add-ons, self-hosted. 32 GB or more for the full selection.", ko: "Sovereign OSS Extended(values-onprem.yaml): MinIO, Polaris, Trino와 선택한 애드온을 직접 운영합니다. 전체 구성에는 32 GB 이상이 필요합니다." },
      { en: "Portable Core · AWS (values-foundation.yaml) and Sovereign Core (values-sovereign-core.yaml): the AI layer only, with no catalog or query engine. The second runs MinIO and Ollama in the cluster.", ko: "Portable Core · AWS(values-foundation.yaml)와 Sovereign Core(values-sovereign-core.yaml): 카탈로그와 쿼리 엔진이 없는 AI 계층 전용 프로파일입니다. 후자는 MinIO와 Ollama를 클러스터에서 실행합니다." },
      { en: "AWS Hybrid Extended (values-aws.yaml): a compatibility overlay for an existing cluster. It preserves the add-ons already running and is not an EKS installer.", ko: "AWS Hybrid Extended(values-aws.yaml): 기존 클러스터용 호환 오버레이입니다. 이미 실행 중인 애드온은 그대로 유지하며 EKS 설치 도구가 아닙니다." },
    ],
    related: [{ label: { en: "AWS reference", ko: "AWS 레퍼런스" }, href: "/docs/aws-reference" }, { label: { en: "Sovereign", ko: "Sovereign" }, href: "/docs/sovereign" }, { label: { en: "Portable Core", ko: "Portable Core" }, href: "/docs/portable-core" }],
  },
  "portable-core": {
    title: { en: "Portable Core · AWS Starter", ko: "Portable Core · AWS 스타터" },
    status: "Shipped",
    summary: {
      en: "values-foundation.yaml is the smallest maintained profile: the AI layer without a lakehouse. The filename is historical; its product role is Portable Core on AWS.",
      ko: "values-foundation.yaml은 관리되는 프로파일 중 가장 작은 구성으로, 레이크하우스 없이 AI 계층만 제공합니다. 파일 이름은 이전 이름을 유지하고, 제품에서의 역할은 AWS 위의 Portable Core입니다.",
    },
    points: [
      { en: "Runs backend, frontend, PostgreSQL + pgvector, LiteLLM and Valkey, with external native S3 and Bedrock.", ko: "백엔드, 프론트엔드, PostgreSQL + pgvector, LiteLLM, Valkey를 실행하고, 외부 S3와 Bedrock을 사용합니다." },
      { en: "No catalog or Trino: Catalog, Analytics, Sources and Metrics are hidden. Knowledge, Agents and the AI Gateway work.", ko: "카탈로그와 Trino가 없으므로 Catalog, Analytics, Sources, Metrics는 숨겨집니다. Knowledge, Agents, AI Gateway는 동작합니다." },
      { en: "No AWS service is created as a replacement for what is off. To add the lakehouse, move to the Single-Node Reference.", ko: "꺼 둔 기능을 대체하는 AWS 서비스는 만들어지지 않습니다. 레이크하우스가 필요하면 Single-Node Reference로 옮깁니다." },
    ],
    related: [{ label: { en: "Knowledge", ko: "Knowledge" }, href: "/knowledge" }, { label: { en: "Profile matrix", ko: "프로파일 비교" }, href: "/docs/profiles" }],
  },
  "aws-reference": {
    title: { en: "AWS Single-Node Reference", ko: "AWS Single-Node Reference" },
    status: "Reference",
    summary: {
      en: "The AWS reference is one EC2 node running K3s, with managed Aurora, S3, the Glue catalog and Bedrock around it, and Trino and Polaris in the cluster.",
      ko: "AWS 레퍼런스는 K3s를 실행하는 EC2 노드 한 대에, 관리형 Aurora, S3, Glue 카탈로그, Bedrock을 연결하고 Trino와 Polaris를 클러스터 안에서 실행하는 구성입니다.",
    },
    points: [
      { en: "Our reference node is a t3.xlarge Spot instance that runs weekdays 07:30 to 18:00 KST on an EventBridge schedule; Aurora stays up at minimum capacity.", ko: "레퍼런스 노드는 t3.xlarge Spot 인스턴스이고, EventBridge 일정에 따라 평일 07:30~18:00 KST에만 실행됩니다. Aurora는 최소 용량으로 계속 켜 둡니다." },
      { en: "Terraform also creates ECR, IAM, Route53, Secrets Manager, CloudWatch/SNS and the start/stop schedule.", ko: "Terraform은 ECR, IAM, Route53, Secrets Manager, CloudWatch/SNS와 시작·중지 일정도 함께 만듭니다." },
      { en: "Glue is the default catalog and Polaris runs beside it; new data can sync into Polaris with a target catalog.", ko: "Glue가 기본 카탈로그이고 Polaris가 옆에서 실행됩니다. 대상 카탈로그를 지정하면 새 데이터를 Polaris로 동기화할 수 있습니다." },
      { en: "Production-oriented but not application-node HA; recovery is part of the operating model. EKS, EMR Serverless, S3 Tables, Lake Formation, AOSS, DataZone and Marketplace packaging remain roadmap.", ko: "운영 환경을 염두에 둔 구성이지만 애플리케이션 노드 이중화는 아니며, 복구 절차가 운영 모델에 포함됩니다. EKS, EMR Serverless, S3 Tables, Lake Formation, AOSS, DataZone, Marketplace 패키징은 로드맵입니다." },
    ],
    related: [{ label: { en: "System", ko: "System" }, href: "/services?tab=system" }, { label: { en: "Backup & restore", ko: "백업과 복구" }, href: "/docs/backup-restore" }],
  },
  sovereign: {
    title: { en: "Sovereign OSS Extended", ko: "Sovereign OSS Extended" },
    status: "Optional",
    summary: {
      en: "Use the self-hosted profile when infrastructure control, local models or disconnected operation matters more than the smallest footprint.",
      ko: "인프라 통제, 로컬 모델, 폐쇄망 운영이 최소 규모보다 중요하다면 자체 호스팅 프로파일을 사용합니다.",
    },
    points: [
      { en: "values-onprem.yaml runs MinIO (S3 API), Polaris and Trino, PostgreSQL/pgvector, LiteLLM and optional add-ons in your own Kubernetes.", ko: "values-onprem.yaml은 MinIO(S3 API), Polaris, Trino, PostgreSQL/pgvector, LiteLLM과 선택한 애드온을 자체 Kubernetes에서 실행합니다." },
      { en: "values-sovereign-core.yaml is the on-prem twin of the AI starter: MinIO and Ollama in the cluster, local-only egress, no catalog.", ko: "values-sovereign-core.yaml은 AI 스타터의 온프레미스 대응 프로파일입니다. 클러스터 안의 MinIO와 Ollama, 외부 통신 차단, 카탈로그 없음 구성입니다." },
      { en: "Turn off every add-on you do not need; open source does not mean low operations.", ko: "필요 없는 애드온은 모두 끄세요. 오픈소스라고 해서 운영 부담이 작은 것은 아닙니다." },
      { en: "Check THIRD_PARTY_NOTICES.md: some optional images use AGPL or source-available licenses.", ko: "THIRD_PARTY_NOTICES.md를 확인하세요. 일부 선택형 이미지는 AGPL이나 소스 공개형 라이선스를 사용합니다." },
    ],
    related: [{ label: { en: "Optional add-ons", ko: "선택형 애드온" }, href: "/docs/addons" }, { label: { en: "Exit strategy", ko: "이전 전략" }, href: "/docs/exit-strategy" }],
  },
  "open-contracts": {
    title: { en: "Open Contracts", ko: "개방형 계약" },
    status: "Shipped",
    summary: {
      en: "Portability comes from stable formats and protocols, not from running every open-source service at once.",
      ko: "이식성은 모든 오픈소스 서비스를 함께 돌리는 데서 나오지 않고, 안정적인 데이터 형식과 프로토콜에서 나옵니다.",
    },
    points: [
      { en: "Objects: the S3 API (S3 or MinIO/S3-compatible). Tables: Parquet and Apache Iceberg. Catalogs: Glue or Iceberg REST.", ko: "객체: S3 API(S3 또는 MinIO 등 S3 호환 스토리지). 테이블: Parquet과 Apache Iceberg. 카탈로그: Glue 또는 Iceberg REST." },
      { en: "Engine: Trino. Metadata and vectors: PostgreSQL + pgvector. Models: logical names through LiteLLM, any OpenAI-compatible provider.", ko: "엔진: Trino. 메타데이터와 벡터: PostgreSQL + pgvector. 모델: LiteLLM의 논리 이름으로 연결하는 OpenAI 호환 제공자." },
      { en: "Identity: JWT, LDAP, passkeys and optional OIDC. Deployment: containers, Helm, Kubernetes. Delta Lake writes are not supported.", ko: "인증: JWT, LDAP, 패스키, 선택형 OIDC. 배포: 컨테이너, Helm, Kubernetes. Delta Lake 쓰기는 지원하지 않습니다." },
      { en: "Provider IDs, ARNs, bucket paths, model IDs and credentials belong in adapter configuration, not in product records.", ko: "제공자 ID, ARN, 버킷 경로, 모델 ID, 자격 증명은 제품 데이터가 아니라 어댑터 설정에 둡니다." },
    ],
    related: [{ label: { en: "Architecture", ko: "아키텍처" }, href: "/docs/architecture" }, { label: { en: "Exit strategy", ko: "이전 전략" }, href: "/docs/exit-strategy" }],
  },
  "exit-strategy": {
    title: { en: "Exit Strategy", ko: "이전 전략" },
    status: "Reference",
    summary: {
      en: "Your data stays in open formats in your own bucket, so it can move. Catalog export is shipped; a single automated export/import command and Delta to Iceberg migration are not.",
      ko: "데이터가 사용자 계정의 버킷에 개방형 형식으로 남아 있으므로 옮길 수 있습니다. 카탈로그 내보내기는 제공되지만, 단일 내보내기/가져오기 명령과 Delta → Iceberg 마이그레이션은 아직 없습니다.",
    },
    points: [
      { en: "Catalogs: Export registers a catalog's Iceberg tables in another catalog (for example Glue to Polaris) without copying data. It has been exercised between Polaris catalogs in CI and in a live Glue to Polaris rehearsal.", ko: "카탈로그: Export는 한 카탈로그의 Iceberg 테이블을 다른 카탈로그(예: Glue → Polaris)에 데이터 복사 없이 등록합니다. CI에서는 Polaris 카탈로그 간, 실환경에서는 Glue → Polaris 리허설로 검증했습니다." },
      { en: "Storage and database: copy S3 objects, restore PostgreSQL from a backup, keep the encryption keys, and re-embed if the embedding model or dimension changes.", ko: "스토리지와 DB: S3 객체를 복사하고, PostgreSQL을 백업에서 복원하고, 암호화 키를 보존하며, 임베딩 모델이나 차원이 바뀌면 다시 임베딩합니다." },
      { en: "Moving the warehouse to a different bucket path still needs table re-registration, because Iceberg metadata holds object URIs.", ko: "웨어하우스를 다른 버킷 경로로 옮기는 경우에는 Iceberg 메타데이터에 객체 URI가 들어 있으므로 테이블을 다시 등록해야 합니다." },
      { en: "Still open: a long-running self-hosted install and the Bedrock to local-model switch drill.", ko: "아직 남은 일: 장기간 운영하는 자체 호스팅 설치 검증과 Bedrock → 로컬 모델 전환 연습." },
    ],
    related: [{ label: { en: "Two catalogs", ko: "두 개의 카탈로그" }, href: "/docs/catalogs" }, { label: { en: "Backup & restore", ko: "백업과 복구" }, href: "/docs/backup-restore" }, { label: { en: "Open contracts", ko: "개방형 계약" }, href: "/docs/open-contracts" }],
  },
  addons: {
    title: { en: "Optional OSS Add-ons", ko: "선택형 OSS 애드온" },
    status: "Optional",
    summary: {
      en: "Add-ons extend the platform without becoming dependencies of the lakehouse path or the AI layer. Each appears in the console only when its capability is on.",
      ko: "애드온은 레이크하우스 경로나 AI 계층의 의존성이 되지 않으면서 플랫폼을 확장합니다. 각 애드온은 capability가 켜져 있을 때만 콘솔에 나타납니다.",
    },
    points: [
      { en: "Polaris: an Iceberg REST catalog, usable beside Glue. Trino is not an add-on; it is the engine on every profile with a catalog.", ko: "Polaris: Glue와 함께 쓸 수 있는 Iceberg REST 카탈로그입니다. Trino는 애드온이 아니라, 카탈로그가 있는 모든 프로파일의 기본 엔진입니다." },
      { en: "RisingWave: streaming SQL/CDC. Airflow and Spark: orchestration and batch. OpenMetadata: external catalog and lineage UI.", ko: "RisingWave: 스트리밍 SQL과 CDC. Airflow와 Spark: 오케스트레이션과 배치. OpenMetadata: 외부 카탈로그·리니지 UI." },
      { en: "Jupyter with DuckDB: exploration. MLflow: experiments and model registry.", ko: "Jupyter와 DuckDB: 데이터 탐색. MLflow: 실험 추적과 모델 레지스트리." },
      { en: "Enable only what the use case and the resource budget justify.", ko: "사용 사례와 자원 예산에 맞는 것만 켜세요." },
    ],
    related: [{ label: { en: "Services", ko: "Services" }, href: "/services" }, { label: { en: "Profile matrix", ko: "프로파일 비교" }, href: "/docs/profiles" }],
  },
  "backup-restore": {
    title: { en: "Backup & Restore", ko: "백업과 복구" },
    status: "Reference",
    summary: {
      en: "A recoverable deployment protects the lake in object storage, PostgreSQL state, the catalog metadata, and the keys that decrypt stored credentials.",
      ko: "복구 가능한 배포는 객체 스토리지의 레이크, PostgreSQL 상태, 카탈로그 메타데이터, 저장된 자격 증명을 복호화하는 키를 함께 보호합니다.",
    },
    points: [
      { en: "AWS reference: Aurora point-in-time recovery and snapshots (they also hold Polaris metadata), S3 versioning for the data bucket, and Secrets Manager for critical secrets.", ko: "AWS 레퍼런스: Aurora 시점 복구와 스냅샷(Polaris 메타데이터도 포함), 데이터 버킷의 S3 버전 관리, 핵심 시크릿을 위한 Secrets Manager를 사용합니다." },
      { en: "Restore ENCRYPTION_KEY before the backend connects to restored data. A new key cannot decrypt existing source credentials, and the old one cannot be recovered.", ko: "복원한 데이터에 백엔드를 연결하기 전에 ENCRYPTION_KEY부터 복원하세요. 새 키로는 기존 소스 자격 증명을 복호화할 수 없고, 잃어버린 키는 되찾을 수 없습니다." },
      { en: "Keep the Secrets Manager copy of ENCRYPTION_KEY current; a stale copy is what makes a rebuild fail.", ko: "Secrets Manager에 보관한 ENCRYPTION_KEY를 항상 최신으로 유지하세요. 오래된 사본이 재구축 실패의 원인이 됩니다." },
      { en: "Test restores and record the observed RPO and RTO. The single-node reference relies on fast restore rather than node HA.", ko: "복구를 주기적으로 시험하고 실제 RPO와 RTO를 기록하세요. 단일 노드 레퍼런스는 노드 이중화 대신 빠른 복구에 의존합니다." },
    ],
    related: [{ label: { en: "Exit strategy", ko: "이전 전략" }, href: "/docs/exit-strategy" }],
  },
  "knowledge-rag": {
    title: { en: "Knowledge & RAG", ko: "Knowledge & RAG" },
    status: "Shipped",
    summary: {
      en: "Knowledge is the AI layer's retrieval workspace. It runs in every profile and starts cleanly with every lakehouse module off.",
      ko: "Knowledge는 AI 계층의 검색 작업 공간입니다. 모든 프로파일에서 동작하며, 레이크하우스 모듈이 모두 꺼진 상태에서도 문제없이 시작합니다.",
    },
    points: [
      { en: "Create collections; ingest text, S3 objects, table sources, or tables sent from Catalog. Chunks are replaced by source group, and scheduled freshness keeps them current.", ko: "컬렉션을 만들고 텍스트, S3 객체, 테이블 소스, Catalog에서 보낸 테이블을 수집합니다. 청크는 소스 그룹 단위로 교체되며, 예약된 갱신으로 최신 상태를 유지합니다." },
      { en: "Search with pgvector, optionally rerank through LiteLLM, and fall back to vector order if reranking fails.", ko: "pgvector로 검색하고, 필요하면 LiteLLM으로 재순위화하며, 재순위화가 실패하면 벡터 순서로 되돌아갑니다." },
      { en: "Answers carry citations. PII is masked at ingestion and again at retrieval, with modes per caller and collection.", ko: "답변에는 인용이 붙습니다. PII는 수집 시점과 검색 시점에 마스킹되며, 호출자와 컬렉션별로 모드를 정할 수 있습니다." },
      { en: "Collection access is application-level owner, admin and shared ACL, not database row-level security.", ko: "컬렉션 접근은 데이터베이스 행 수준 보안이 아니라 소유자·관리자·공유 ACL로 제어하는 애플리케이션 수준 방식입니다." },
    ],
    related: [{ label: { en: "Knowledge", ko: "Knowledge" }, href: "/knowledge" }, { label: { en: "Governance", ko: "Governance" }, href: "/docs/governance" }],
  },
  sources: {
    title: { en: "Sources", ko: "Sources" },
    status: "Optional",
    summary: {
      en: "Sources connect operational data to the lake. Database sources are Trino catalogs you can browse and join in SQL, and a sync copies them into Iceberg. The Connectors capability needs Trino only.",
      ko: "Sources는 운영 데이터를 레이크에 연결합니다. 데이터베이스 소스는 SQL로 둘러보고 조인할 수 있는 Trino 카탈로그이며, 동기화하면 Iceberg로 복사됩니다. Connectors capability는 Trino만 있으면 됩니다.",
    },
    points: [
      { en: "PostgreSQL, MySQL, SQL Server, Oracle and MongoDB each become a Trino catalog src_<slug>. Adding one restarts the engine for about a minute.", ko: "PostgreSQL, MySQL, SQL Server, Oracle, MongoDB는 각각 Trino 카탈로그 src_<slug>가 됩니다. 추가하면 엔진이 1분 정도 재시작됩니다." },
      { en: "Sync modes: full (one atomic replace), incremental on a watermark column, and merge on key columns. New columns are added, and compatible type widening is handled.", ko: "동기화 방식: full(한 번에 원자적으로 교체), 워터마크 컬럼 기반 incremental, 키 컬럼 기반 merge. 새 컬럼은 추가되고, 호환되는 타입 확장은 처리됩니다." },
      { en: "PII is masked inside the sync SELECT. Each table has a Target catalog, which is remembered for the next sync.", ko: "PII는 동기화 SELECT 안에서 마스킹됩니다. 테이블마다 Target catalog를 지정하며, 다음 동기화에도 기억됩니다." },
      { en: "Who can use a source is its share list (owner plus members), which is also the grant list of its catalog. The two sample SQL sources connect as the read-only datapond_sample role.", ko: "소스를 쓸 수 있는 사람은 공유 목록(소유자와 멤버)이며, 이는 해당 카탈로그의 권한 목록과 같습니다. SQL 샘플 소스 두 개는 읽기 전용 datapond_sample 역할로 연결됩니다." },
      { en: "REST, custom Python and S3 sources are read by the backend, not by Trino.", ko: "REST, 커스텀 Python, S3 소스는 Trino가 아니라 백엔드가 읽습니다." },
    ],
    related: [{ label: { en: "Sources", ko: "Sources" }, href: "/connectors", capability: "connectors" }, { label: { en: "Catalog and Analytics", ko: "Catalog와 Analytics" }, href: "/docs/catalog-query" }, { label: { en: "Two catalogs", ko: "두 개의 카탈로그" }, href: "/docs/catalogs" }],
  },
  "catalog-query": {
    title: { en: "Catalog, Analytics & Metrics", ko: "Catalog, Analytics, Metrics" },
    status: "Optional",
    summary: {
      en: "Catalog, Analytics and Metrics are the lakehouse workspace. They run on Trino over the Glue catalog, Polaris, or both, and appear only when the capability is on.",
      ko: "Catalog, Analytics, Metrics는 레이크하우스 작업 공간입니다. Glue 카탈로그, Polaris 또는 둘 모두 위에서 Trino로 동작하며, capability가 켜져 있을 때만 나타납니다.",
    },
    points: [
      { en: "Catalog: lake catalogs and source catalogs with namespace chips per catalog, a table page with preview and statistics, and Send to Knowledge.", ko: "Catalog: 카탈로그별 네임스페이스 칩이 있는 레이크·소스 카탈로그, 미리보기와 통계가 있는 테이블 페이지, Knowledge로 보내기를 제공합니다." },
      { en: "Analytics: a Trino SQL editor with a schema tree of every catalog you may use, history, charts and saved dashboards. Use three-part names; bare names resolve only in lake catalogs, so a source table needs src_<slug>.schema.table.", ko: "Analytics: 접근 가능한 모든 카탈로그의 스키마 트리, 기록, 차트, 저장된 대시보드가 있는 Trino SQL 에디터입니다. 세 부분 이름을 사용하세요. 이름만 쓰면 레이크 카탈로그에서만 찾으므로, 소스 테이블은 src_<slug>.schema.table 형식이 필요합니다." },
      { en: "Write statements need the query:write permission. Viewers and business analysts get SELECT and dashboards.", ko: "쓰기 구문에는 query:write 권한이 필요합니다. viewer와 business_analyst는 SELECT와 대시보드를 사용합니다." },
      { en: "Metrics: admin-approved, versioned definitions compiled to cited SQL, queryable by people and by agents (metric_query).", ko: "Metrics: 관리자가 승인한 버전 관리 지표 정의를 출처가 있는 SQL로 컴파일하며, 사람과 에이전트(metric_query)가 조회할 수 있습니다." },
    ],
    related: [
      { label: { en: "Catalog", ko: "Catalog" }, href: "/catalog", capability: "catalog" },
      { label: { en: "Analytics", ko: "Analytics" }, href: "/query", capability: "query" },
      { label: { en: "Metrics", ko: "Metrics" }, href: "/metrics", capability: "query" },
    ],
  },
  catalogs: {
    title: { en: "Two catalogs and the catalog export", ko: "두 개의 카탈로그와 카탈로그 내보내기" },
    status: "Shipped",
    summary: {
      en: "Several Iceberg catalogs can run side by side, for example Glue as default and Polaris beside it. One rule keeps them consistent: every table has exactly one writer.",
      ko: "여러 Iceberg 카탈로그를 나란히 운영할 수 있습니다. 예를 들어 Glue를 기본으로 두고 Polaris를 함께 씁니다. 모든 테이블에는 쓰는 주체가 정확히 하나라는 규칙이 일관성을 지킵니다.",
    },
    points: [
      { en: "Owner and mirror: a table seen by two catalogs has an owner and a read-only mirror. Writes and DROPs against a mirror are refused with a 409 that names the owner.", ko: "소유자와 미러: 두 카탈로그에서 보이는 테이블에는 소유자와 읽기 전용 미러가 있습니다. 미러에 대한 쓰기와 DROP은 소유자를 알려 주는 409로 거부됩니다." },
      { en: "Reads of a mirror run against the owner, so the owner's grants and policies apply. Stale mirrors are re-pointed every 5 minutes, and commits made outside DataPond are flagged diverged.", ko: "미러를 읽으면 소유자 쪽에서 실행되므로 소유자의 권한과 정책이 적용됩니다. 오래된 미러는 5분마다 다시 연결되고, DataPond 밖에서 커밋된 변경은 diverged로 표시됩니다." },
      { en: "Export: Settings → Data catalogs → Export… (also on the Catalog page) registers a catalog's Iceberg tables in another catalog without copying data. Review the plan, then apply.", ko: "내보내기: Settings → Data catalogs → Export…(Catalog 페이지에도 있음)는 한 카탈로그의 Iceberg 테이블을 데이터 복사 없이 다른 카탈로그에 등록합니다. 계획을 검토한 뒤 적용합니다." },
      { en: "Mode mirror keeps the source catalog as owner; mode move makes the target the owner. The Mirrors list shows fresh, diverged or error, with Check now.", ko: "mirror 모드는 원본 카탈로그가 소유자로 남고, move 모드는 대상 카탈로그가 소유자가 됩니다. Mirrors 목록에는 fresh, diverged, error 상태가 표시되며 Check now로 즉시 확인할 수 있습니다." },
      { en: "Export and Mirrors need the catalog:write permission, which admins and data engineers have. Adding, editing and granting catalogs stays admin-only. Syncs choose a catalog with target_catalog.", ko: "Export와 Mirrors에는 catalog:write 권한이 필요하며, admin과 data_engineer가 갖고 있습니다. 카탈로그 추가·수정·권한 부여는 관리자 전용입니다. 동기화는 target_catalog로 카탈로그를 고릅니다." },
    ],
    related: [{ label: { en: "Catalog", ko: "Catalog" }, href: "/catalog", capability: "catalog" }, { label: { en: "Settings", ko: "Settings" }, href: "/settings" }, { label: { en: "Exit strategy", ko: "이전 전략" }, href: "/docs/exit-strategy" }],
  },
  "ai-gateway": {
    title: { en: "AI Gateway", ko: "AI Gateway" },
    status: "Shipped",
    summary: {
      en: "LiteLLM is the one model boundary for Bedrock and for cloud or local providers. It also carries the tool surface that lets agents use governed data.",
      ko: "LiteLLM은 Bedrock과 클라우드·로컬 제공자를 잇는 단일 모델 경계입니다. 에이전트가 거버넌스가 적용된 데이터를 쓰는 도구 인터페이스도 함께 제공합니다.",
    },
    points: [
      { en: "Use logical model names for chat, embedding and reranking, so provider IDs stay in adapter configuration.", ko: "채팅, 임베딩, 재순위화에는 논리 모델 이름을 사용해 제공자 ID를 어댑터 설정에만 둡니다." },
      { en: "Every call carries the caller's identity, so usage and spend aggregate per caller. Per-caller budgets are enforced (HTTP 402 when exceeded).", ko: "모든 호출에 호출자 신원이 실려 사용량과 비용이 호출자별로 집계됩니다. 호출자별 예산은 강제 적용되며, 초과하면 HTTP 402가 반환됩니다." },
      { en: "Read-only MCP at POST /api/mcp offers 30 read actions, including approved metrics. Service-account keys are scoped, expiring, rotatable and rate-limited.", ko: "POST /api/mcp의 읽기 전용 MCP는 승인된 Metrics를 포함해 30개의 읽기 작업을 제공합니다. 서비스 계정 키는 범위 제한, 만료, 교체, 호출 제한을 지원합니다." },
      { en: "Restrict provider management, budgets and global spend to administrators.", ko: "제공자 관리, 예산, 전체 비용 설정은 관리자에게만 허용하세요." },
    ],
    related: [{ label: { en: "AI Gateway", ko: "AI Gateway" }, href: "/ai" }, { label: { en: "Connect an agent", ko: "에이전트 연결" }, href: "/help/integrate" }],
  },
  governance: {
    title: { en: "Governance", ko: "거버넌스" },
    status: "Shipped",
    summary: {
      en: "Governance is applied at the data layer, so it holds for the console, for SQL and for agents alike.",
      ko: "거버넌스는 데이터 계층에서 적용되므로 콘솔, SQL, 에이전트 모두에 똑같이 적용됩니다.",
    },
    points: [
      { en: "Catalog grants decide who reads a catalog. Row filters and column masks are policies on catalog + schema + table, enforced on the SQL path (Analytics, previews, queries). Trino Layer 2 is optional.", ko: "카탈로그 권한이 카탈로그를 읽을 수 있는 사람을 정합니다. 행 필터와 컬럼 마스크는 catalog + schema + table 단위 정책이며 SQL 경로(Analytics, 미리보기, 쿼리)에서 강제됩니다. Trino Layer 2는 선택 사항입니다." },
      { en: "Korean PII masking runs during sync and ingestion and again at retrieval, with sensitivity labels and per-caller or per-collection modes.", ko: "한국형 PII 마스킹은 동기화·수집 중과 검색 시점에 모두 적용되며, 민감도 라벨과 호출자별·컬렉션별 모드를 지원합니다." },
      { en: "Audit: tool calls (including refused ones), the query log, access decisions, and NDJSON export.", ko: "감사: 거부된 호출을 포함한 도구 호출, 쿼리 로그, 접근 결정 기록, NDJSON 내보내기를 제공합니다." },
      { en: "Roles: admin, data_engineer, ai_engineer, data_scientist, business_analyst, auditor and viewer. A service-account key or IdP token never passes admin checks.", ko: "역할: admin, data_engineer, ai_engineer, data_scientist, business_analyst, auditor, viewer. 서비스 계정 키나 IdP 토큰은 관리자 권한 검사를 통과하지 못합니다." },
      { en: "Knowledge collections use owner, admin and shared ACL, which is application-level, not database RLS.", ko: "Knowledge 컬렉션은 소유자·관리자·공유 ACL을 사용하며, 이는 데이터베이스 RLS가 아닌 애플리케이션 수준 제어입니다." },
    ],
    related: [{ label: { en: "Governance", ko: "Governance" }, href: "/governance" }, { label: { en: "Governance guide", ko: "거버넌스 가이드" }, href: "/help/governance" }, { label: { en: "AI Gateway", ko: "AI Gateway" }, href: "/docs/ai-gateway" }],
  },
  configuration: {
    title: { en: "Configuration", ko: "설정" },
    status: "Shipped",
    summary: {
      en: "Helm component flags decide what runs and which capabilities are on. Profile metadata only describes the result.",
      ko: "무엇이 실행되고 어떤 capability가 켜지는지는 Helm 컴포넌트 플래그가 정합니다. 프로파일 메타데이터는 그 결과를 설명할 뿐입니다.",
    },
    points: [
      { en: "Use profile files as overlays. Keep domains, bucket paths, database endpoints, image repositories and secrets out of version control.", ko: "프로파일 파일은 오버레이로 사용하세요. 도메인, 버킷 경로, DB 엔드포인트, 이미지 저장소, 시크릿은 버전 관리에 넣지 않습니다." },
      { en: "Data catalogs (Glue, Polaris) are added, tested, edited and granted in Settings → Data catalogs. Trino workers scale with trino.workers.replicas.", ko: "데이터 카탈로그(Glue, Polaris)는 Settings → Data catalogs에서 추가·테스트·수정하고 권한을 부여합니다. Trino 워커는 trino.workers.replicas로 늘립니다." },
      { en: "The app shell shows profile and adapter hints from /api/capabilities. Changing a label never enables a feature.", ko: "앱 셸은 /api/capabilities의 프로파일·어댑터 정보를 보여 줍니다. 레이블을 바꾼다고 기능이 켜지지는 않습니다." },
    ],
    related: [{ label: { en: "Settings", ko: "Settings" }, href: "/settings" }, { label: { en: "Configuration guide", ko: "설정 가이드" }, href: "/help/operate" }, { label: { en: "Profile matrix", ko: "프로파일 비교" }, href: "/docs/profiles" }],
  },
  monitoring: {
    title: { en: "Monitoring & Observability", ko: "모니터링" },
    status: "Shipped",
    summary: {
      en: "Use Services and System for runtime health, and AI Gateway and Governance for model usage, spend and audit.",
      ko: "런타임 상태는 Services와 System에서, 모델 사용량·비용·감사는 AI Gateway와 Governance에서 확인합니다.",
    },
    points: [
      { en: "A capability means configured, not healthy. Check workload health separately.", ko: "capability가 켜져 있다는 것은 설정되어 있다는 뜻이지 정상이라는 뜻이 아닙니다. 워크로드 상태는 따로 확인하세요." },
      { en: "Query history and the query log show who ran what in Analytics; tool-call audit shows what agents did.", ko: "쿼리 기록과 쿼리 로그에서 누가 Analytics에서 무엇을 실행했는지, 도구 호출 감사에서 에이전트가 무엇을 했는지 볼 수 있습니다." },
      { en: "The AWS reference emits CloudWatch metrics and SNS alerts; OSS observability stacks are not required.", ko: "AWS 레퍼런스는 CloudWatch 지표와 SNS 알림을 보내며, OSS 관측 스택은 필수가 아닙니다." },
    ],
    related: [{ label: { en: "Services", ko: "Services" }, href: "/services" }, { label: { en: "System", ko: "System" }, href: "/services?tab=system" }],
  },
  authentication: {
    title: { en: "Authentication", ko: "인증" },
    status: "Shipped",
    summary: {
      en: "People sign in with local JWT accounts, passkeys (WebAuthn) or LDAP; Enterprise adds OIDC SSO. Applications and agents use service-account keys.",
      ko: "사람은 로컬 JWT 계정, 패스키(WebAuthn), LDAP로 로그인하며, Enterprise에서는 OIDC SSO를 추가로 쓸 수 있습니다. 애플리케이션과 에이전트는 서비스 계정 키를 사용합니다.",
    },
    points: [
      { en: "The local administrator remains available for recovery. Passkeys need a secure origin.", ko: "복구를 위해 로컬 관리자 계정은 그대로 유지됩니다. 패스키는 보안 출처(HTTPS)가 필요합니다." },
      { en: "The console uses an HttpOnly session cookie, accepted only same-origin on state-changing requests.", ko: "콘솔은 HttpOnly 세션 쿠키를 사용하며, 상태를 바꾸는 요청에서는 같은 출처의 요청만 허용합니다." },
      { en: "Service-account keys are scoped, expiring and rotatable. A key never passes admin or human-only checks and cannot set a password.", ko: "서비스 계정 키는 범위 제한, 만료, 교체가 가능합니다. 키는 관리자 검사나 사람 전용 검사를 통과하지 못하고 비밀번호도 설정할 수 없습니다." },
      { en: "OAuth resource-server mode for IdP tokens exists but is off by default and has not been exercised against a live IdP. SAML is roadmap.", ko: "IdP 토큰용 OAuth 리소스 서버 모드는 기본으로 꺼져 있고 실제 IdP로 검증한 적은 없습니다. SAML은 로드맵입니다." },
    ],
    related: [{ label: { en: "Settings", ko: "Settings" }, href: "/settings" }, { label: { en: "Connect an agent", ko: "에이전트 연결" }, href: "/help/integrate" }],
  },
  troubleshooting: {
    title: { en: "Troubleshooting", ko: "문제 해결" },
    status: "Shipped",
    summary: {
      en: "Start with the profile and capability, then workload health, then the adapter boundary that is failing.",
      ko: "프로파일과 capability를 먼저 확인하고, 그다음 워크로드 상태, 마지막으로 문제가 되는 어댑터 경계를 점검합니다.",
    },
    points: [
      { en: "A module is missing: compare the active profile and capability flag before debugging something that was never installed.", ko: "모듈이 보이지 않을 때: 설치된 적 없는 서비스를 디버깅하기 전에 활성 프로파일과 capability 값을 먼저 비교합니다." },
      { en: "A query says table not found: use the three-part name. Source tables are src_<slug>.schema.table.", ko: "쿼리에서 테이블을 찾을 수 없다고 나올 때: 세 부분 이름을 사용하세요. 소스 테이블은 src_<slug>.schema.table 형식입니다." },
      { en: "A write returns 409: the table is a mirror. The error names the owner catalog; write there instead.", ko: "쓰기가 409로 거부될 때: 해당 테이블은 미러입니다. 오류 메시지에 나온 소유 카탈로그에 쓰세요." },
      { en: "Sources are briefly unavailable after adding a database: the engine restarts for about a minute.", ko: "데이터베이스를 추가한 직후 잠시 조회가 안 될 때: 엔진이 1분 정도 재시작됩니다." },
      { en: "An AI call returns 402: the caller's budget is used up. For RAG failures check pgvector, object access, LiteLLM, model access and embedding dimensions. For catalog failures check Trino, the catalog adapter and its credentials.", ko: "AI 호출이 402를 반환할 때: 호출자의 예산이 소진된 것입니다. RAG 오류는 pgvector, 객체 접근, LiteLLM, 모델 접근, 임베딩 차원을 확인하고, 카탈로그 오류는 Trino, 카탈로그 어댑터와 자격 증명을 확인하세요." },
    ],
    related: [{ label: { en: "Services", ko: "Services" }, href: "/services" }, { label: { en: "Profile matrix", ko: "프로파일 비교" }, href: "/docs/profiles" }],
  },
  api: {
    title: { en: "REST API", ko: "REST API" },
    status: "Shipped",
    summary: {
      en: "The FastAPI backend exposes sources and sync, catalogs, queries, metrics, Knowledge/RAG, the AI gateway, governance and storage over REST and OpenAPI. A read-only MCP endpoint serves the same data to agents.",
      ko: "FastAPI 백엔드는 소스·동기화, 카탈로그, 쿼리, 메트릭, Knowledge/RAG, AI 게이트웨이, 거버넌스, 스토리지를 REST와 OpenAPI로 제공합니다. 읽기 전용 MCP 엔드포인트는 같은 데이터를 에이전트에 제공합니다.",
    },
    points: [
      { en: "Interactive OpenAPI documentation is at /api/docs; the gateway OpenAPI document is at GET /api/tools/openapi.json.", ko: "대화형 OpenAPI 문서는 /api/docs에 있고, 게이트웨이용 OpenAPI 문서는 GET /api/tools/openapi.json에 있습니다." },
      { en: "MCP: POST /api/mcp with 30 read actions. Authenticate with a service-account key.", ko: "MCP: POST /api/mcp에서 30개의 읽기 작업을 제공합니다. 서비스 계정 키로 인증하세요." },
      { en: "Capability discovery is GET /api/capabilities; it reports configuration, not live health.", ko: "capability 조회는 GET /api/capabilities이며, 라이브 상태가 아니라 설정 상태를 알려 줍니다." },
    ],
    related: [{ label: { en: "Open Swagger", ko: "Swagger 열기" }, href: "/api/docs" }, { label: { en: "AI Gateway", ko: "AI Gateway" }, href: "/docs/ai-gateway" }],
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
  "catalog-export": ARTICLES.catalogs,
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
  "knowledge-rag", "sources", "catalog-query", "catalogs", "ai-gateway", "governance",
  "configuration", "monitoring", "authentication", "troubleshooting", "api",
]

// Match lifecycle status to color, consistent with the docs index badges.
const STATUS_STYLES: Record<Status, string> = {
  Shipped: "bg-[var(--dp-good)]/10 text-[var(--dp-good-text)] border-[var(--dp-good)]/25",
  Optional: "bg-[var(--dp-warn)]/10 text-[var(--dp-warn-text)] border-[var(--dp-warn)]/25",
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
  const { t } = useHelpLocale()
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
          <BreadcrumbItem><BreadcrumbLink href="/help?tab=docs">{t({ en: "Docs", ko: "문서" })}</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>{doc ? t(doc.title) : humanize(slug)}</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {doc ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <BookOpen className="h-5 w-5 text-primary" />
            <h1 className="text-2xl font-semibold">{t(doc.title)}</h1>
            <Badge variant="outline" className={STATUS_STYLES[doc.status]}>{t(STATUS_LABEL[doc.status])}</Badge>
            <div className="ml-auto"><HelpLocaleToggle /></div>
          </div>
          <Card>
            <CardContent className="space-y-4 py-5">
              {/* Lead paragraph reads at body weight/foreground; bullets carry the detail. */}
              <p className="text-base leading-relaxed text-foreground">{t(doc.summary)}</p>
              <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed text-muted-foreground marker:text-primary/60">
                {doc.points.map((point) => <li key={point.en}>{t(point)}</li>)}
              </ul>
              {related && related.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-2">
                  {related.map((item) => (
                    <Link key={item.href} href={item.href} className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-muted">
                      {t(item.label)}<ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  ))}
                </div>
              )}
              <p className="flex items-center gap-1 pt-2 text-2xs text-muted-foreground">
                <ExternalLink className="h-3 w-3" /> {t({ en: "Canonical operator guides live in the repository", ko: "운영 가이드의 원문은 저장소의" })} <span className="font-mono">docs/</span> {t({ en: "directory.", ko: "디렉터리에 있습니다." })}
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
                    <span className="block text-2xs uppercase tracking-wide text-muted-foreground">{t({ en: "Previous", ko: "이전" })}</span>
                    <span className="block truncate text-sm font-medium">{t(ARTICLES[prevSlug].title)}</span>
                  </span>
                </Link>
              ) : <span className="hidden flex-1 sm:block" />}
              {nextSlug ? (
                <Link
                  href={`/docs/${nextSlug}`}
                  className="group flex flex-1 items-center justify-end gap-2 rounded-md border px-3 py-2.5 text-right transition-colors hover:border-primary/40 hover:bg-muted"
                >
                  <span className="min-w-0">
                    <span className="block text-2xs uppercase tracking-wide text-muted-foreground">{t({ en: "Next", ko: "다음" })}</span>
                    <span className="block truncate text-sm font-medium">{t(ARTICLES[nextSlug].title)}</span>
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
            <p className="text-sm text-muted-foreground">{t({ en: "The article", ko: "문서" })} <span className="font-mono">{slug}</span> {t({ en: "is not part of the active documentation set.", ko: "는 현재 문서 목록에 없습니다." })}</p>
            <Link href="/help?tab=docs" className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-muted">
              <ArrowLeft className="h-3.5 w-3.5" /> {t({ en: "Documentation home", ko: "문서 홈" })}
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
