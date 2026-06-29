# DataPond 제품 컨셉 — AWS-Native Data Foundation for AI Apps

**작성일**: 2026-06-30
**버전**: 4.0.0-aws-pivot
**상위 설계**: [docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md](superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md)
**이전 컨셉(v3.0 OSS Lakehouse)**: `archive/oss-lakehouse` 브랜치 / `v3.0-oss-lakehouse` 태그

---

## 🎯 제품 컨셉

### Tagline
**"AWS 위에서 RAG·에이전트의 데이터 연료를 공급하는 데이터 기반"**
*S3+Bedrock 네이티브, 거버넌스·카탈로그·실시간은 오픈소스로 차별화*

### Elevator Pitch (30초)
```
DataPond는 AWS에서 AI 앱(RAG·에이전트)을 프로덕션에 올리려는 팀을 위한
데이터 기반 플랫폼입니다.

S3 데이터 → 임베딩 → 벡터 검색 → Bedrock 응답까지의 파이프라인을,
거버넌스(권한·계보·PII·비용)까지 갖춰 즉시 제공합니다.

Bedrock Knowledge Bases가 '검색'만 준다면,
DataPond는 그 위에 거버넌스·멀티테넌시·비용 관리·레이크하우스 통합을 더합니다.

고객의 AWS 계정 안에서 동작 → 데이터 주권 유지, 오픈소스 차별화 레이어로 락인 회피.
```

### 포지셔닝 전환

```yaml
Before (v3.0 — OSS Lakehouse):
  포지셔닝: "벤더 중립 OSS Databricks 대안 (1/10 비용)"
  타깃: 비용 민감 데이터팀
  경쟁축: 가격
  약점: 벤더 중립이 곧 'AWS에서 1등은 아님'

After (v4.0 — AWS-Native AI Data Foundation):
  포지셔닝: "AWS에서 AI 앱의 데이터 기반"
  타깃: AWS에서 RAG·에이전트 만드는 개발팀 + 플랫폼팀
  경쟁축: AWS 통합 깊이 + 거버넌스 + 이식성
  강점: 이미 구현된 AI 데이터 배관을 AWS 네이티브로 재프레이밍
```

---

## 🏆 핵심 가치 제안

### 1. AI 앱의 데이터 파이프라인을 거버넌스까지 완성형으로 🧩
```yaml
문제:
  - RAG를 PoC에서 프로덕션으로 올릴 때 배관이 전부 수작업
  - S3 → 청킹 → 임베딩 → 벡터 적재 → 검색 → 응답, 각 단계 직접 조립
  - 권한/계보/PII/비용 거버넌스는 사후과제로 밀림

해결 (※ 다수가 이미 구현됨 — 아래 '재활용 자산' 참조):
  - 인제스천: 청크 업서트, 재시도/부분실패 격리, PII 마스킹, 품질 게이트
  - 벡터/RAG: pgvector 기반 RAG, 리랭크, 컬렉션 단위 RLS(행수준 보안)
  - 브릿지: 레이크하우스/카탈로그 → Knowledge(벡터) 자동 전송
  - 거버넌스: OpenMetadata 계보, 사용자별 비용 귀속, 예산 알림

가치:
  - "RAG 데모"가 아니라 "거버넌스 갖춘 프로덕션 RAG 기반"
```

### 2. AWS 네이티브 코어로 운영부담 제거 ☁️
```yaml
하이브리드 원칙:
  - 상품화 가치 낮은 인프라 → AWS 매니지드로 교체 (운영부담 0)
  - 차별화되는 레이어 → OSS 유지 (락인 회피·이식성)

AWS 코어:
  - 스토리지: S3
  - 테이블/카탈로그: S3 Tables + Glue Catalog (Polaris는 옵션)
  - 쿼리/배치: Athena · EMR Serverless
  - LLM: Amazon Bedrock (Claude) + LiteLLM 멀티모델 라우팅
  - 벡터: pgvector(Aurora) 기본 / OpenSearch Serverless 확장
  - 배포: EKS + Terraform/CDK + AWS Marketplace
```

### 3. 데이터 주권 + 멀티모델 자유 🔐
```yaml
- 고객 AWS 계정 안에서 동작 (데이터 외부 반출 없음)
- Bedrock(Claude/Titan) + LiteLLM로 클라우드/로컬 모델 혼합
- 규제 산업(금융·헬스케어) 대응: PII 마스킹·RLS·계보 기본 탑재
```

---

## 🎭 타깃 고객

### Primary: "AWS에서 AI 앱 만드는 개발팀"
```yaml
직함: AI/ML 엔지니어, 백엔드 리드, 플랫폼 엔지니어
회사: AWS를 주력으로 쓰는 스타트업~중견 (10~500명)
상황:
  - RAG/에이전트 PoC는 됐는데 프로덕션 데이터 배관이 막막
  - Bedrock Knowledge Bases만으론 권한·비용·계보가 부족
  - 직접 조립하기엔 팀이 작음
원하는 것:
  - S3 데이터를 거버넌스 갖춰 AI에 연결
  - 자기 AWS 계정 안에서, 빠르게
```

### Secondary: "규제 산업 데이터 플랫폼팀"
```yaml
- 금융/헬스케어: 데이터 주권·감사·PII 필수
- On-prem/Private(고객 VPC) 배포 요구
- 멀티모델(로컬 LLM 포함) 하이브리드
```

---

## 🏗️ 아키텍처 (하이브리드)

```
                 AI 앱 (RAG / 에이전트)
                        │ RAG API
   ┌────────────────────┼────────────────────┐
   │  AI 데이터 레이어 (핵심)                  │
   │  Bedrock Knowledge Base ── 벡터 스토어    │
   │       ▲              (pgvector / AOSS)    │
   │  임베딩 파이프라인 (Bedrock Embeddings)   │
   │  인제스천(청크·재시도·PII·품질게이트)     │
   └────────────────────┼────────────────────┘
                        │
   ┌────────────────────┼────────────────────┐
   │  레이크하우스 코어                        │
   │  S3 + Iceberg/S3 Tables + Glue           │
   │  Athena · EMR Serverless · RisingWave    │
   └────────────────────┼────────────────────┘
                        │
   ┌────────────────────┼────────────────────┐
   │  거버넌스/관측 (OSS 차별화)               │
   │  OpenMetadata(계보) · Polaris(RBAC)      │
   │  벡터 RLS · 사용자별 비용·예산 알림       │
   │  Lake Formation/IAM · DuckDB(로컬 탐색)  │
   └──────────────────────────────────────────┘

   배포: EKS + Terraform/CDK + AWS Marketplace
```

상세 컴포넌트 매핑은 [설계 스펙 §3](superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md)을 참조.

---

## 🆚 경쟁 분석

| 항목 | Bedrock KB 단독 | Databricks/Snowflake | AWS DIY 조합 | **DataPond** |
|---|---|---|---|---|
| 벡터 검색 | ✅ | ✅ | ✅(직접) | ✅ |
| 거버넌스(권한·계보) | ❌ | ✅(비쌈) | ❌(직접) | ✅ **OSS** |
| 벡터 RLS/멀티테넌시 | ❌ | 제한적 | ❌ | ✅ **구현됨** |
| PII 마스킹/품질게이트 | ❌ | 일부 | ❌ | ✅ **구현됨** |
| 비용 귀속/예산 알림 | ❌ | 일부 | ❌ | ✅ **구현됨** |
| 멀티모델 라우팅 | ❌(Bedrock만) | 제한적 | 직접 | ✅ LiteLLM |
| AWS 통합 깊이 | ✅ | 중간 | ✅ | ✅ |
| 데이터 주권(고객 VPC) | ✅ | ❌(SaaS) | ✅ | ✅ |
| 즉시 배포 | ✅ | ✅ | ❌(수주) | ✅(Helm/Marketplace) |
| 락인 | 높음 | 매우 높음 | 중간 | **낮음(OSS 레이어)** |

**핵심 결론**: DataPond는 Bedrock KB의 '검색'에 **거버넌스·멀티테넌시·비용관리**를 더하고,
Databricks/Snowflake 대비 **AWS 네이티브 + 저비용 + 이식성**으로 차별화한다.

---

## ♻️ 재활용 자산 (이전 OSS 작업 → AWS 컨셉)

피보팅이 **0에서 시작이 아닌** 이유 — `main`에 이미 구현되어 있는 자산:

| 영역 | 기존 구현 | AWS 컨셉에서의 역할 |
|---|---|---|
| 벡터/RAG | pgvector RAG, 리랭크, 컬렉션 RLS | **그대로 핵심 레이어** (pgvector 기본 전략과 일치) |
| 인제스천 | 청크 업서트, 재시도, PII 마스킹, 품질 게이트 | AI 데이터 파이프라인 차별화 |
| 브릿지 | Catalog/소스 → Knowledge 전송 | 레이크하우스 → 벡터 연결 |
| 거버넌스 | OpenMetadata 계보, 벡터 RLS | OSS 차별화 레이어 |
| 비용 | 사용자별 스펜드, 예산 알림, 토큰 대시보드 | AI 비용 거버넌스 |
| LLM | LiteLLM 폴백·관측성·로컬 백엔드 | 멀티모델 라우팅 (Bedrock 위에) |
| AWS | EC2 Spot K3s PoC (`datapond.csg.fitcloud.co.kr`) | EKS·매니지드로 진화할 베이스 |

> 즉 v4.0 작업의 상당 부분은 **'신규 구축'이 아니라 'AWS 네이티브로 재배선'** 이다.

---

## 🚀 로드맵

| Phase | 내용 | 상태 |
|---|---|---|
| **0** | 보관 (OSS 컨셉 아카이브) | ✅ 완료 |
| **1** | 컨셉 재정의 (본 문서, README) | ✅ 진행 |
| **2** | 레퍼런스 아키텍처 (IaC·보안·벡터 추상화) | ⏭️ 다음 |
| **3** | MVP — S3→임베딩→벡터→Bedrock RAG end-to-end (기존 pgvector RAG 재배선) | |
| **4** | GTM 재정렬 (Marketplace·데모·콘텐츠) | |

---

## 💰 비즈니스 모델 (요약)

```yaml
Open Core:
  Community: 100% 오픈소스, 고객 AWS 계정 셀프호스팅
  Enterprise: SAML/LDAP, 멀티테넌시, 고급 RBAC, SLA, 지원
  AWS Marketplace: 종량제/구독 리스팅으로 도입 마찰 최소화

Professional Services:
  - AWS 환경 구축/마이그레이션 컨설팅
  - 규제 산업 거버넌스 커스터마이징
```

---

## 🎯 핵심 메시지 요약

1. **AI 앱의 데이터 기반** — RAG/에이전트의 연료를 거버넌스까지 완성형으로
2. **AWS 네이티브** — S3·Bedrock 코어로 운영부담 제거, 고객 계정 안에서 동작
3. **이미 만들어진 자산** — pgvector RAG·인제스천·거버넌스·비용관리가 구현 완료

### Call-to-Action
> "Bedrock Knowledge Bases로 시작했지만 권한·비용·계보가 막혔다면, DataPond."
