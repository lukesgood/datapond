# 포지셔닝 v7 — 중소 규모를 위한 가벼운 개방형 레이크하우스

**상태:** 결정 · **날짜:** 2026-11-12 · **대체:** v6.0 (`POSITIONING_REVIEW.md`, 2026-09-07)

## 결정

DataPond는 **AWS를 쓰는 중소 규모 고객에게 가벼운 데이터레이크와 데이터 플랫폼을 제공하는
제품**이다. 구성 요소마다 교체 가능한 개방 표준을 써서 벤더 종속을 최소화한다.

| 계층 | 개방 표준 | AWS 레퍼런스에서 쓰는 것 | 바꿀 수 있는 것 |
|---|---|---|---|
| 객체 저장소 | S3 API | Amazon S3 | MinIO 등 S3 호환 저장소 |
| 테이블 형식 | Apache Iceberg (Parquet) | Iceberg | — (표준 자체) |
| 카탈로그 | Iceberg 카탈로그 (Glue · Iceberg REST) | AWS Glue | Polaris 등 Iceberg REST 카탈로그 |
| 쿼리 엔진 | Trino (분산 SQL) | 클러스터 안 Trino | Trino를 어디서나 실행 |
| 앱 상태 | PostgreSQL | Aurora PostgreSQL | 일반 PostgreSQL |
| 모델 | OpenAI 호환 API (LiteLLM) | Bedrock | 다른 클라우드·로컬 모델 |
| 배포 | Helm · Kubernetes | EC2/K3s 단일 노드 | 다른 Kubernetes |

AI 기능(문서 검색과 인용 답변, 자연어 SQL, 에이전트용 MCP·REST, 호출자별 거버넌스와 비용)은
버리지 않는다. 이제는 **데이터 플랫폼 위의 활용 계층**이다.

## 왜 바꾸나

- 소유자의 제품 목적(2026-10-19, 2026-11-12 재확인): Databricks를 쓰지만 규모가 크지 않고 AWS를
  적극적으로 쓰는 고객에게 가벼운 데이터레이크 환경을 플랫폼으로 제공한다. 종속을 최소화하는
  구조가 필수다.
- v6.0("AI 에이전트용 거버넌스 데이터 도구 서버")은 수요 검증 게이트(2026-10-27)를 결과 없이
  지났다. `MARKET_REVIEW_2026-10.md`는 독립 시장이 약하거나 검증되지 않았다고 봤다.
- 제품은 이미 그 방향으로 와 있다. 2.4에서 Athena를 클러스터 안 Trino로 바꿨고(쿼리 엔진의 AWS
  종속 제거), 2.5에서 외부 DB를 Trino 카탈로그로 연합 조회하게 했다.

## 경쟁 위치

| 대안 | 강점 | DataPond가 다른 점 |
|---|---|---|
| Databricks | 완성도, Spark·노트북·Unity Catalog | 작은 팀에 무겁고 비싸다. DataPond는 단일 노드부터 시작하고 고객 계정 안에서 돈다 |
| Athena + Glue를 직접 조립 | 운영 부담 없음, 쿼리당 과금 | AWS에만 묶이고, 외부 DB 연합·행 단위 통제·제품 UI가 없다 |
| EMR, Starburst, Dremio | 대규모 성능 | 중소 규모에 과하다. 운영 인력이 필요하다 |
| Snowflake | 완성도 | 데이터가 플랫폼 안에 들어간다. 개방 형식이 기본이 아니다 |

DataPond의 자리: **작게 시작하고, 개방 형식으로 고객 계정 안에 두고, 필요하면 AWS 밖으로도
그대로 가져갈 수 있는 레이크하우스.**

## 무엇이 바뀌나

- 정본 문서(README, `PRODUCT_CONCEPT.md`, `ARCHITECTURE.md`, `PORTABILITY.md`, `CLAUDE.md`)를 이
  문장으로 다시 쓴다.
- 콘솔 메뉴가 데이터 플랫폼을 앞에 둔다: Lakehouse(Catalog, Analytics, Sources, Metrics) → Pipelines
  → Data Science → AI → Operate. 대시보드의 핵심 흐름도 쿼리 엔진이 있으면 연결 → 정리 → 쿼리 →
  거버넌스 → AI 순서다.
- 종속을 줄이는 기능을 제품에 넣었다(2.6):
  - **카탈로그 내보내기**(`POST /api/catalogs/{name}/export`): 한 카탈로그의 Iceberg 테이블을 데이터
    복사 없이 다른 카탈로그에 등록한다. Glue를 떠나는 경로이며, kind CI에서 매번 검증한다.
  - **Trino 워커**(`trino.workers.replicas`): 단일 노드에서 시작해 워커를 붙여 확장한다.

## 무엇을 하지 않나

- AWS 전용 관리형 서비스로 핵심 경로를 바꾸는 것(Athena, Lake Formation을 필수로 두는 것 등).
- 게이트웨이 기능(에이전트 레지스트리, SSO/SCIM 동기화, tool 단위 정책 엔진).
- 대규모 HA 클러스터를 첫 목표로 삼는 것. 단일 노드와 워커 확장이 먼저다.
- Delta Lake 쓰기. Databricks에서 오는 데이터는 Iceberg로 옮기는 것을 전제로 한다(이관 도구는 로드맵).

## 아직 검증되지 않은 것

- **수요.** 중소 규모 Databricks·AWS 고객과의 대화로 확인해야 한다. 이 결정은 제품 방향이지 시장
  검증이 아니다.
- **Glue → Polaris 실이관.** 내보내기 경로는 REST 카탈로그 사이에서 CI가 검증하지만, 라이브 Glue에서
  Polaris로 옮긴 적은 아직 없다.
- **워커가 붙은 대용량 성능.** CI는 워커 1대로 기능만 확인한다.
- **Delta → Iceberg 이관 절차.**

v6.0의 결정 근거와 시장 조사는 `POSITIONING_REVIEW.md`, v6 기준 적합도 감사는
`POSITIONING_FIT_AUDIT.md`에 역사 기록으로 남는다.
